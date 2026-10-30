/**
 * The digest pipeline: scrape every saved article, rank the survivors against
 * the theme, summarise the top N, render the front page, and update the store.
 *
 * Every network dependency is injected. Failures are per-article: one paywalled
 * page never aborts the edition, and a missing DeepSeek key only means the page
 * is composed from deterministic fallbacks.
 */

import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

import pLimit from 'p-limit';

import { createHtmlFetcher } from './fetch-html.js';
import { extractArticle } from './extract.js';
import { fallbackSummary, rankArticles, summarizeAll } from './llm.js';
import { renderNewspaper } from './render.js';
import { createRobotsChecker } from './robots.js';
import { APP_ROOT, SETTINGS_PATH, loadSettings } from './settings.js';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class RobotsDisallowedError extends Error {
  constructor(url) {
    super(`robots.txt disallows ${url}.`);
    this.name = 'RobotsDisallowedError';
    this.code = 'robots_disallowed';
  }
}

/**
 * Serialise requests to one host so a run never hammers a small blog. The slot
 * is reserved before sleeping, so concurrent callers queue behind each other.
 */
export function createHostGate(delayMs, { sleepImpl = sleep, now = Date.now } = {}) {
  const nextSlot = new Map();

  return async function waitForHost(host, overrideDelayMs = delayMs) {
    const delay = Math.max(0, overrideDelayMs);
    if (delay === 0) return;

    const current = now();
    const slot = Math.max(current, nextSlot.get(host) ?? 0);
    nextSlot.set(host, slot + delay);

    if (slot > current) await sleepImpl(slot - current);
  };
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return String(url);
  }
}

function failureLabel(code) {
  switch (code) {
    case 'robots_disallowed': return 'robots.txt disallows it';
    case 'timeout': return 'the request timed out';
    case 'too_large': return 'the page was too large';
    case 'unsupported_content_type': return 'it was not an HTML page';
    case 'too_little_content': return 'no readable article text was found';
    case 'http_error':
    case 'upstream_error': return 'the site answered with an error';
    case 'rate_limited': return 'the site rate-limited the request';
    case 'blocked_host':
    case 'blocked_address': return 'the host is not safe to fetch';
    case 'dns_failed': return 'the host did not resolve';
    default: return 'the page could not be read';
  }
}

function plainArticle(article) {
  return {
    id: article.id,
    url: article.url,
    title: article.title,
    siteName: article.siteName,
    byline: article.byline,
    publishedAt: article.publishedAt,
    fetchedAt: article.fetchedAt,
    wordCount: article.wordCount,
  };
}

async function writeAtomic(filePath, content) {
  const tmp = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmp, content, 'utf8');
  await rename(tmp, filePath);
}

/**
 * Build the run function that the run manager starts. `run({ runId, onProgress })`
 * resolves to a summary the web UI can display; it never rejects for an expected
 * per-article failure.
 */
export function createDigestRunner({
  store,
  settingsPath = SETTINGS_PATH,
  loadSettingsImpl = loadSettings,
  appRoot = APP_ROOT,
  createFetcher = createHtmlFetcher,
  createRobots = createRobotsChecker,
  fetchArticle = null,
  extract = extractArticle,
  rank = rankArticles,
  summarize = summarizeAll,
  render = renderNewspaper,
  client = null,
  apiKey = undefined,
  now = () => new Date(),
  sleepImpl = sleep,
  warn = console.warn,
} = {}) {
  if (!store) throw new TypeError('createDigestRunner requires a store.');

  return async function run({ runId, onProgress = () => {}, signal } = {}) {
    const settings = await loadSettingsImpl(settingsPath, { warn });
    const saved = await store.list();

    if (saved.length === 0) {
      return {
        status: 'failed',
        runId,
        generatedAt: now().toISOString(),
        error: 'no_articles',
        warnings: ['The collection is empty. Add at least one article before composing an edition.'],
        counts: { total: 0, fetched: 0, failed: 0 },
        stories: [],
      };
    }

    const total = saved.length;
    const report = (phase, completed, totalCount = total) => onProgress({
      phase,
      completed,
      total: totalCount,
    });

    report('scrape', 0);

    // An injected `fetchArticle` is a test seam: it replaces the whole polite
    // fetch path (SSRF guard, robots, per-host delay) with a fake.
    const injectedFetcher = typeof fetchArticle === 'function';
    const fetcher = injectedFetcher
      ? null
      : createFetcher({
        timeoutMs: settings.fetch.timeoutMs,
        maxBytes: settings.fetch.maxBytes,
        maxRedirects: settings.fetch.maxRedirects,
        userAgent: settings.fetch.userAgent,
      });

    const robots = injectedFetcher || !settings.fetch.respectRobotsTxt
      ? null
      : createRobots({ fetchText: fetcher.fetchText, userAgent: settings.fetch.userAgent, warn });

    const gate = createHostGate(settings.fetch.perHostDelayMs, { sleepImpl });

    async function fetchWithRobots(article) {
      if (injectedFetcher) return fetchArticle(article);

      if (robots) {
        const allowed = await robots.isAllowed(article.url);
        if (!allowed) throw new RobotsDisallowedError(article.url);
      }

      let crawlDelay = 0;
      if (robots) {
        try {
          crawlDelay = (await robots.crawlDelaySeconds(article.url)) * 1000;
        } catch {
          crawlDelay = 0;
        }
      }
      await gate(new URL(article.url).host, Math.max(settings.fetch.perHostDelayMs, crawlDelay));

      return fetcher.fetchHtml(article.url, { signal });
    }

    let completed = 0;
    const failures = [];
    const scrapeGate = pLimit(settings.fetch.concurrency);

    const scraped = await Promise.all(saved.map((article) => scrapeGate(async () => {
      try {
        const response = await fetchWithRobots(article);
        const html = response?.html ?? response?.text ?? '';
        const finalUrl = response?.finalUrl ?? article.url;

        if (signal?.aborted) throw Object.assign(new Error('Run aborted.'), { code: 'aborted' });

        const extracted = extract(html, { url: finalUrl, now: now() });
        const fetchedAt = now().toISOString();
        const file = await store.writeMarkdown(article.id, {
          title: extracted.title,
          url: article.url,
          siteName: extracted.siteName,
          byline: extracted.byline,
          publishedAt: extracted.publishedAt,
          fetchedAt,
          wordCount: extracted.wordCount,
        }, extracted.markdown);

        const updated = await store.update(article.id, {
          title: extracted.title,
          siteName: extracted.siteName,
          byline: extracted.byline,
          publishedAt: extracted.publishedAt,
          fetchedAt,
          status: 'ok',
          error: null,
          wordCount: extracted.wordCount,
          excerpt: extracted.excerpt,
        });

        return { article: updated ?? article, file, markdown: extracted.markdown };
      } catch (err) {
        const code = err?.code ?? 'fetch_failed';
        failures.push({ url: article.url, code });
        try {
          await store.update(article.id, {
            status: code === 'robots_disallowed' ? 'blocked' : 'failed',
            error: code,
            fetchedAt: now().toISOString(),
          });
        } catch (updateError) {
          warn(`[digest] could not record failure for ${article.url}: ${updateError.message}`);
        }
        return null;
      } finally {
        completed += 1;
        report('scrape', completed);
      }
    })));

    const readable = scraped.filter(Boolean).map((entry) => ({ ...entry.article, markdown: entry.markdown }));

    const warnings = failures.map((failure) => `${hostOf(failure.url)}: ${failureLabel(failure.code)}.`);

    if (readable.length === 0) {
      report('render', total, total);
      const generatedAt = now().toISOString();
      const edition = {
        runId,
        theme: settings.theme,
        topN: settings.topN,
        generatedAt,
        stories: [],
        remaining: [],
        warnings,
        llm: { rankingSource: 'deterministic', rankingError: 'no_articles' },
        counts: { total, fetched: 0, failed: failures.length },
      };
      const outputFile = await writeEdition({ appRoot, settings, render, edition });
      return {
        status: 'failed',
        runId,
        generatedAt,
        error: 'no_articles_fetched',
        outputFile,
        warnings,
        counts: edition.counts,
        stories: [],
      };
    }

    report('rank', readable.length, readable.length);

    const ranking = await rank(readable, {
      theme: settings.theme,
      topN: settings.topN,
      client,
      apiKey,
      timeoutMs: settings.llm.timeoutMs,
      maxTokens: settings.llm.maxTokens,
      temperature: settings.llm.temperature,
      candidatesOffered: settings.llm.rankingCandidates,
      now: now(),
      signal,
    });

    if (ranking.source !== 'deepseek') {
      warnings.push(
        ranking.error === 'no_key'
          ? 'No DEEPSEEK_API_KEY is set; ranking used the local fallback.'
          : `Ranking used the local fallback (${ranking.error ?? 'model unavailable'}).`,
      );
    }

    const byId = new Map(readable.map((article) => [article.id, article]));
    let picked = (ranking.ranking ?? [])
      .map((pick) => byId.get(pick.id))
      .filter(Boolean);

    // The real ranker always fills its slots, but an empty answer must still
    // produce a real front page rather than an empty-edition notice.
    if (picked.length === 0) {
      picked = readable.slice(0, settings.topN);
      warnings.push('The ranker returned no usable picks; the newest readable articles were used.');
    }

    report('summarize', 0, picked.length);

    const summaries = (await summarize(picked, {
      theme: settings.theme,
      client,
      apiKey,
      timeoutMs: settings.llm.timeoutMs,
      maxTokens: settings.llm.maxTokens,
      temperature: settings.llm.temperature,
      concurrency: settings.llm.summaryConcurrency,
      signal,
    })) ?? [];
    report('summarize', picked.length, picked.length);

    const stories = picked.map((article, index) => ({
      rank: index + 1,
      article: plainArticle(article),
      summary: summaries[index] ?? fallbackSummary(article, 'missing_summary'),
    }));

    const fallbackSummaries = stories
      .map((story) => story.summary)
      .filter((summary) => summary.source !== 'deepseek');
    if (fallbackSummaries.length > 0) {
      const codes = [...new Set(fallbackSummaries.map((summary) => summary.error).filter(Boolean))];
      warnings.push(
        `${fallbackSummaries.length} of ${stories.length} summaries used the local fallback`
        + (codes.length ? ` (${codes.join(', ')}).` : '.'),
      );
    }
    const pickedIds = new Set(stories.map((story) => story.article.id));
    const remaining = readable
      .filter((article) => !pickedIds.has(article.id))
      .map(plainArticle);

    const generatedAt = now().toISOString();
    const edition = {
      runId,
      theme: settings.theme,
      topN: settings.topN,
      generatedAt,
      stories,
      remaining,
      warnings,
      llm: { rankingSource: ranking.source, rankingError: ranking.error },
      counts: { total, fetched: readable.length, failed: failures.length },
    };

    report('render', 0, 1);
    const outputFile = await writeEdition({ appRoot, settings, render, edition });
    report('render', 1, 1);

    const allFromModel = ranking.source === 'deepseek' && fallbackSummaries.length === 0;

    return {
      status: allFromModel ? 'ok' : 'degraded',
      runId,
      generatedAt,
      outputFile,
      error: null,
      warnings,
      counts: edition.counts,
      stories: stories.map((story) => ({
        id: story.article.id,
        headline: story.summary.headline,
        url: story.article.url,
        source: story.summary.source,
      })),
      model: { rankingSource: ranking.source, rankingError: ranking.error },
    };
  };
}

async function writeEdition({ appRoot, settings, render, edition }) {
  const outputDir = path.resolve(appRoot, settings.output.dir);
  const outputFile = path.join(outputDir, settings.output.file);
  const html = render(edition);

  await mkdir(outputDir, { recursive: true });
  await writeAtomic(outputFile, html);
  return outputFile;
}
