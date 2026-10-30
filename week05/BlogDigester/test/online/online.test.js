/**
 * Opt-in integration tests against the real network and the real DeepSeek key.
 *
 * `npm test` discovers this file but every case is skipped unless RUN_ONLINE=1,
 * so the default suite never touches the network. Run it with:
 *
 *   npm run test:online
 *
 * ONLINE_URLS (comma-separated) overrides the scrape targets. The local
 * DeepSeek path is sometimes slow or flaky, so model calls are retried once and
 * their latency is printed; an environment failure is reported, never hidden.
 */

import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

import { config } from '../../src/config.js';
import { createDigestRunner } from '../../src/digest.js';
import { extractArticle } from '../../src/extract.js';
import { createHtmlFetcher } from '../../src/fetch-html.js';
import { escapeHtml } from '../../src/html.js';
import { rankArticles } from '../../src/llm.js';
import { createStore } from '../../src/store.js';

const ONLINE = process.env.RUN_ONLINE === '1';
const HAS_KEY = config.llm.apiKey !== '';
const TIMEOUT_MS = 180_000;

const TARGETS = (process.env.ONLINE_URLS ?? 'https://en.wikipedia.org/wiki/World_Wide_Web')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function onlineTest(name, fn, { requiresKey = false } = {}) {
  let skip = false;
  if (!ONLINE) skip = 'set RUN_ONLINE=1, or run npm run test:online';
  else if (requiresKey && !HAS_KEY) skip = 'set DEEPSEEK_API_KEY in .env';

  test(name, { skip, timeout: TIMEOUT_MS }, fn);
}

const CANDIDATES = [
  {
    id: 'aaaaaaaaaaaa',
    title: 'Compilers are user interfaces',
    siteName: 'Example',
    publishedAt: '2026-10-01',
    wordCount: 1400,
    excerpt: 'Why compiler diagnostics are the real user interface of a language.',
  },
  {
    id: 'bbbbbbbbbbbb',
    title: 'A week in the life of a sourdough starter',
    siteName: 'Example',
    publishedAt: '2026-09-01',
    wordCount: 900,
    excerpt: 'Feeding schedules and hydration.',
  },
  {
    id: 'cccccccccccc',
    title: 'Shipping an AI feature without a research team',
    siteName: 'Example',
    publishedAt: '2026-10-15',
    wordCount: 2200,
    excerpt: 'A small team integrates a model, writes evaluations and keeps the fallback path.',
  },
];

async function rankWithRetry(options) {
  let result = await rankArticles(CANDIDATES, options);
  if (result.source !== 'deepseek') {
    console.log(`[online] ranking fell back (${result.error}) after ${result.latencyMs}ms; retrying once`);
    await sleep(2000);
    result = await rankArticles(CANDIDATES, options);
  }
  console.log(`[online] ranking: source=${result.source} latency=${result.latencyMs}ms error=${result.error}`);
  return result;
}

onlineTest('DeepSeek ranks candidates against the theme', async () => {
  const result = await rankWithRetry({
    theme: 'AI and software engineering',
    topN: 2,
    apiKey: config.llm.apiKey,
    timeoutMs: 90_000,
  });

  assert.equal(result.source, 'deepseek', `model unavailable: ${result.error} after ${result.latencyMs}ms`);
  assert.ok(result.ranking.length >= 1);
  const offered = new Set(CANDIDATES.map((candidate) => candidate.id));
  for (const pick of result.ranking) {
    assert.ok(offered.has(pick.id), `invented id ${pick.id}`);
    assert.ok(pick.reason.length > 0);
  }
}, { requiresKey: true });

onlineTest('a live page can be fetched and extracted', async () => {
  const fetcher = createHtmlFetcher({ timeoutMs: 30_000 });
  const url = TARGETS[0];
  const response = await fetcher.fetchHtml(url);
  const article = extractArticle(response.html, { url: response.finalUrl });

  console.log(`[online] ${url} -> "${article.title}" (${article.wordCount} words)`);
  assert.ok(article.wordCount > 200, `only ${article.wordCount} words extracted`);
  assert.ok(article.markdown.length > 1000);
  assert.ok(article.title.length > 0);
  assert.doesNotMatch(article.markdown, /<script/i);
});

onlineTest('a full run fetches, archives, ranks, summarises and renders', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-online-'));
  try {
    const settingsPath = path.join(root, 'settings.json');
    await writeFile(settingsPath, JSON.stringify({
      topN: 2,
      theme: 'Software engineering and the technology industry.',
      fetch: { concurrency: 2, perHostDelayMs: 0, timeoutMs: 30_000 },
      llm: { summaryConcurrency: 1, timeoutMs: 90_000 },
      output: { dir: 'output', file: 'index.html' },
    }), 'utf8');

    const store = createStore({ dataDir: path.join(root, 'data') });
    const added = await store.add(TARGETS[0]);

    const runner = createDigestRunner({
      store,
      settingsPath,
      appRoot: root,
      apiKey: config.llm.apiKey,
    });

    const result = await runner({ runId: 'online-run' });
    console.log(`[online] run: status=${result.status} error=${result.error} warnings=${JSON.stringify(result.warnings)}`);

    assert.ok(['ok', 'degraded'].includes(result.status), `run failed: ${result.error}`);
    assert.ok(result.stories.length >= 1);

    const markdown = await readFile(store.markdownPath(added.article.id), 'utf8');
    assert.match(markdown, /^---\n/);
    assert.ok(markdown.split(/\s+/).length > 200);

    const output = await readFile(path.join(root, 'output', 'index.html'), 'utf8');
    assert.match(output, /The Daily Digest/);
    assert.match(output, /<\/html>/);

    // The renderer escapes text, so compare with the escaped form (an
    // apostrophe in the headline becomes &#39;).
    const headline = escapeHtml(result.stories[0].headline);
    assert.ok(output.includes(headline), `headline not found in output: ${result.stories[0].headline}`);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}, { requiresKey: true });
