import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderNewspaper } from '../src/render.js';

function story(index, overrides = {}) {
  return {
    rank: index + 1,
    article: {
      id: `article${index}`,
      url: `https://example.com/post-${index}`,
      title: `Article ${index}`,
      siteName: 'Example Press',
      publishedAt: '2026-10-20',
    },
    summary: {
      headline: `Headline ${index}`,
      dek: `Deck ${index}`,
      summary: `First paragraph ${index}.\n\nSecond paragraph ${index}.`,
      pullQuote: index === 0 ? 'A memorable phrase.' : null,
    },
    ...overrides,
  };
}

function edition(overrides = {}) {
  return {
    runId: 'run-20261030-0001',
    theme: 'Software engineering.',
    topN: 3,
    generatedAt: '2026-10-30T12:00:00Z',
    stories: [story(0), story(1), story(2)],
    remaining: [{ id: 'extra', url: 'https://example.com/extra', title: 'Extra dispatch', siteName: 'Example Press' }],
    warnings: [],
    llm: { rankingSource: 'deepseek' },
    counts: { fetched: 4, failed: 0 },
    ...overrides,
  };
}

test('renders a self-contained newspaper page', () => {
  const html = renderNewspaper(edition());

  assert.match(html, /^<!doctype html>/);
  assert.match(html, /<h1>The Daily Digest<\/h1>/);
  assert.match(html, /Price Two Cents/);
  assert.match(html, /Headline 0/);
  assert.match(html, /Headline 2/);
  assert.match(html, /Extra dispatch/);
  assert.match(html, /Lead story/);
  assert.match(html, /<style>/);
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /<link\b/i);
  assert.doesNotMatch(html, /@import/i);
  assert.doesNotMatch(html, /url\(/i);
});

test('escapes hostile article and model text', () => {
  const hostile = edition({
    theme: 'Theme <script>alert(1)</script>',
    stories: [
      story(0, {
        summary: {
          headline: 'Headline <img src=x onerror=alert(1)>',
          dek: 'Deck & <b>bold</b>',
          summary: '<script>alert("body")</script> & more.',
          pullQuote: '"Quoted" <em>text</em>',
        },
      }),
    ],
  });

  const html = renderNewspaper(hostile);

  assert.doesNotMatch(html, /<script>alert/);
  assert.doesNotMatch(html, /<img/i);
  assert.match(html, /&lt;script&gt;alert/);
  assert.match(html, /Deck &amp; &lt;b&gt;bold&lt;\/b&gt;/);
});

test('non-http links become inert', () => {
  const html = renderNewspaper(edition({
    stories: [],
    remaining: [{ id: 'x', url: 'javascript:alert(1)', title: 'Bad link', siteName: 'Bad' }],
  }));

  assert.doesNotMatch(html, /href="javascript:/);
  assert.match(html, /href="#"/);
});

test('an empty edition explains itself instead of failing', () => {
  const html = renderNewspaper(edition({
    stories: [],
    remaining: [],
    warnings: ['example.com: fetch failed'],
    counts: { fetched: 0, failed: 2 },
    llm: { rankingSource: 'deterministic', rankingError: 'no_key' },
  }));

  assert.match(html, /No dispatches could be fetched/);
  assert.match(html, /example\.com: fetch failed/);
  assert.match(html, /summaries written locally/);
});

test('warnings are capped and escaped', () => {
  const warnings = Array.from({ length: 20 }, (_, index) => `Warning <${index}>`);
  const html = renderNewspaper(edition({ warnings }));

  assert.match(html, /&lt;0&gt;/);
  assert.doesNotMatch(html, /<0>/);
  assert.match(html, /and 8 more/);
});
