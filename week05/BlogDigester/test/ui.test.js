import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderHome, renderRunPage } from '../src/ui.js';

const SETTINGS = { theme: 'Testing & typing', topN: 3 };

function run(overrides = {}) {
  return {
    runId: '20261030120000-1',
    status: 'done',
    phase: 'done',
    startedAt: '2026-10-30T12:00:00Z',
    finishedAt: '2026-10-30T12:00:05Z',
    progress: { phase: 'done', completed: 1, total: 1 },
    error: null,
    result: {
      status: 'ok',
      error: null,
      warnings: [],
      counts: { fetched: 1, failed: 0 },
      stories: [],
    },
    ...overrides,
  };
}

test('the desk links to the edition through the app, not through safeHref', () => {
  const html = renderHome({
    settings: SETTINGS,
    articles: [],
    notice: null,
    digestHref: '/output/index.html',
  });

  assert.match(html, /href="\/output\/index\.html"/);
  assert.doesNotMatch(html, /Latest edition: <a href="#"/);
});

test('the desk marks the compose button disabled with an empty collection', () => {
  const html = renderHome({ settings: SETTINGS, articles: [], notice: 'empty' });

  assert.match(html, /<button type="submit" disabled>/);
  assert.match(html, /Add at least one article/);
});

test('the run page escapes model and warning text and sanitises story links', () => {
  const html = renderRunPage({
    run: run({
      result: {
        status: 'degraded',
        error: null,
        warnings: ['<script>alert(1)</script>'],
        counts: { fetched: 1, failed: 0 },
        stories: [{ id: 'x', headline: 'Head <b>line</b>', url: 'javascript:alert(1)', source: 'deepseek' }],
      },
    }),
    digestHref: '/output/index.html',
  });

  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;alert/);
  assert.match(html, /Head &lt;b&gt;line&lt;\/b&gt;/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.match(html, /href="#"/);
  assert.match(html, /href="\/output\/index\.html"/);
  assert.doesNotMatch(html, /http-equiv="refresh"/);
});

test('a running report refreshes itself and shows progress', () => {
  const html = renderRunPage({
    run: run({ status: 'running', phase: 'scrape', finishedAt: null, progress: { phase: 'scrape', completed: 1, total: 4 } }),
  });

  assert.match(html, /http-equiv="refresh" content="2"/);
  assert.match(html, /1 of 4 complete/);
  assert.match(html, /This page refreshes itself/);
});
