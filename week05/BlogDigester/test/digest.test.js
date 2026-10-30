import assert from 'node:assert/strict';
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, test } from 'node:test';

import { createDigestRunner } from '../src/digest.js';
import { createStore } from '../src/store.js';

const FIXTURE = await readFile(new URL('./fixtures/article.html', import.meta.url), 'utf8');
const cleanups = [];

afterEach(async () => {
  await Promise.all(cleanups.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function makeWorkspace(settingsOverrides = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-run-'));
  cleanups.push(root);

  const settings = {
    topN: 2,
    theme: 'Software testing',
    fetch: { concurrency: 2, perHostDelayMs: 0 },
    llm: { rankingCandidates: 40, summaryConcurrency: 2 },
    output: { dir: 'output', file: 'index.html' },
    ...settingsOverrides,
  };
  const settingsPath = path.join(root, 'settings.json');
  await writeFile(settingsPath, JSON.stringify(settings), 'utf8');

  const store = createStore({ dataDir: path.join(root, 'data') });
  return { root, store, settingsPath };
}

function rankPicks(ids) {
  return async (articles, options) => ({
    source: 'deepseek',
    model: 'test',
    ranking: articles
      .filter((article) => ids.includes(article.id))
      .slice(0, options.topN)
      .map((article, index) => ({
        id: article.id,
        rank: index + 1,
        reason: 'Chosen for the test.',
      })),
    error: null,
    latencyMs: 1,
    accepted: ids.length,
    rejected: 0,
  });
}

function summaryAll(prefix = 'Headline') {
  return async (articles) => articles.map((article, index) => ({
    source: 'deepseek',
    headline: `${prefix} ${index + 1}`,
    dek: 'A deck.',
    summary: 'A paragraph.\n\nAnother paragraph.',
    pullQuote: null,
    error: null,
    latencyMs: 1,
  }));
}

test('a run archives markdown, records failures and renders the edition', async () => {
  const { root, store, settingsPath } = await makeWorkspace();
  const good = [
    await store.add('https://example.com/one'),
    await store.add('https://example.com/two'),
    await store.add('https://example.com/three'),
  ];
  await store.add('https://broken.example/post');

  const phases = [];
  const runner = createDigestRunner({
    store,
    settingsPath,
    appRoot: root,
    fetchArticle: async (article) => {
      if (article.url.includes('broken')) {
        throw Object.assign(new Error('boom'), { code: 'http_error' });
      }
      return { html: FIXTURE, finalUrl: article.url };
    },
    rank: rankPicks([good[0].article.id, good[2].article.id]),
    summarize: summaryAll(),
    now: () => new Date('2026-10-30T12:00:00Z'),
  });

  const result = await runner({ runId: 'test-run', onProgress: (progress) => phases.push(progress.phase) });

  assert.equal(result.status, 'ok');
  assert.equal(result.counts.fetched, 3);
  assert.equal(result.counts.failed, 1);
  assert.equal(result.stories.length, 2);
  assert.ok(phases.includes('scrape') && phases.includes('rank') && phases.includes('summarize'));

  const output = await readFile(path.join(root, 'output', 'index.html'), 'utf8');
  assert.match(output, /Headline 1/);
  assert.match(output, /Headline 2/);
  assert.match(output, /Also on the desk/);
  assert.match(output, /broken\.example/);

  for (const entry of good) {
    const article = await store.get(entry.article.id);
    assert.equal(article.status, 'ok');
    assert.equal(article.wordCount > 100, true);

    const markdown = await readFile(store.markdownPath(entry.article.id), 'utf8');
    assert.match(markdown, /^---\n/);
    assert.ok(markdown.includes(`url: "${entry.article.url}"`));
  }

  const broken = (await store.list()).find((article) => article.url.includes('broken'));
  assert.equal(broken.status, 'failed');
  assert.equal(broken.error, 'http_error');
});

test('an empty ranking still sets a front page from readable articles', async () => {
  const { root, store, settingsPath } = await makeWorkspace({ topN: 2 });
  await store.add('https://example.com/one');
  await store.add('https://example.com/two');

  const runner = createDigestRunner({
    store,
    settingsPath,
    appRoot: root,
    fetchArticle: async (article) => ({ html: FIXTURE, finalUrl: article.url }),
    rank: async () => ({ source: 'deepseek', ranking: [], error: null, latencyMs: 1 }),
    summarize: async () => [],
    apiKey: '',
  });

  const result = await runner({ runId: 'empty-ranking' });

  assert.equal(result.status, 'degraded');
  assert.equal(result.stories.length, 2);
  assert.ok(result.warnings.some((warning) => /ranker returned no usable picks/.test(warning)));
  assert.match(await readFile(path.join(root, 'output', 'index.html'), 'utf8'), /How a Small Team Shipped a Compiler/);
});

test('a robots refusal marks the article blocked without fetching it', async () => {
  const { root, store, settingsPath } = await makeWorkspace();
  const added = await store.add('https://example.com/robots');
  let fetchCalls = 0;

  const runner = createDigestRunner({
    store,
    settingsPath,
    appRoot: root,
    fetchArticle: async (article) => {
      if (article.url.includes('robots')) {
        throw Object.assign(new Error('no'), { code: 'robots_disallowed' });
      }
      fetchCalls += 1;
      return { html: FIXTURE, finalUrl: article.url };
    },
    rank: rankPicks([]),
    summarize: summaryAll(),
  });

  const result = await runner({ runId: 'blocked-run' });
  const article = await store.get(added.article.id);

  assert.equal(fetchCalls, 0);
  assert.equal(article.status, 'blocked');
  assert.equal(result.status, 'failed');
  assert.equal(result.error, 'no_articles_fetched');
});

test('an empty collection fails without writing an edition', async () => {
  const { root, store, settingsPath } = await makeWorkspace();
  const runner = createDigestRunner({ store, settingsPath, appRoot: root });

  const result = await runner({ runId: 'empty-run' });

  assert.equal(result.status, 'failed');
  assert.equal(result.error, 'no_articles');
  await assert.rejects(access(path.join(root, 'output', 'index.html')));
});

test('a keyless run degrades to deterministic ranking and fallback summaries', async () => {
  const { root, store, settingsPath } = await makeWorkspace({ topN: 1 });
  await store.add('https://example.com/one');

  const runner = createDigestRunner({
    store,
    settingsPath,
    appRoot: root,
    fetchArticle: async (article) => ({ html: FIXTURE, finalUrl: article.url }),
    client: null,
    apiKey: '',
    now: () => new Date('2026-10-30T12:00:00Z'),
  });

  const result = await runner({ runId: 'keyless-run' });

  assert.equal(result.status, 'degraded');
  assert.equal(result.model.rankingSource, 'deterministic');
  assert.ok(result.warnings.some((warning) => /DEEPSEEK_API_KEY/.test(warning)));
  assert.match(await readFile(path.join(root, 'output', 'index.html'), 'utf8'), /summaries written locally/);
});
