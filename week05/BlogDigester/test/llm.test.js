import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  MAX_HEADLINE_LENGTH,
  deterministicRank,
  rankArticles,
  summarizeAll,
  summarizeArticle,
  validateRanking,
} from '../src/llm.js';

const NOW = new Date('2026-10-30T12:00:00Z');

const ARTICLES = [
  {
    id: 'aaaaaaaaaaaa',
    title: 'A practical guide to compiler diagnostics',
    siteName: 'Example',
    publishedAt: '2026-10-28',
    addedAt: '2026-10-28T10:00:00Z',
    wordCount: 1200,
    excerpt: 'How good error messages make a compiler easier to use.',
    markdown: '# Diagnostics\n\nGood error messages are the user interface of a compiler.',
  },
  {
    id: 'bbbbbbbbbbbb',
    title: 'A tournament of sorting algorithms',
    siteName: 'Example',
    publishedAt: '2026-09-01',
    addedAt: '2026-09-01T10:00:00Z',
    wordCount: 500,
    excerpt: 'A light-hearted comparison of sorting routines.',
    markdown: '# Sorting\n\nSorting algorithms compared.',
  },
  {
    id: 'cccccccccccc',
    title: 'Notes on compiler testing',
    siteName: 'Example',
    publishedAt: '2024-01-01',
    addedAt: '2024-01-01T10:00:00Z',
    wordCount: 900,
    excerpt: 'Testing a compiler with programs that must fail to compile.',
    markdown: '# Testing\n\nPrograms that must fail to compile.',
  },
];

function stubClient(content) {
  const calls = [];
  return {
    calls,
    chat: {
      completions: {
        create: async (params) => {
          calls.push(params);
          const value = typeof content === 'function' ? content(params) : content;
          if (value instanceof Error) throw value;
          return { choices: [{ message: { content: value } }] };
        },
      },
    },
  };
}

test('no key produces a deterministic ranking with a reason', async () => {
  const result = await rankArticles(ARTICLES, { apiKey: '', theme: 'compilers', topN: 2, now: NOW });

  assert.equal(result.source, 'deterministic');
  assert.equal(result.error, 'no_key');
  assert.equal(result.ranking.length, 2);
  assert.ok(result.ranking.every((pick) => pick.reason.length > 0));
  assert.equal(result.ranking[0].id, 'aaaaaaaaaaaa');
});

test('a valid model ranking is accepted and ordered', async () => {
  const client = stubClient(JSON.stringify({
    picks: [
      { id: 'cccccccccccc', rank: 1, reason: 'Deep testing experience.' },
      { id: 'aaaaaaaaaaaa', rank: 2, reason: 'Useful diagnostics lesson.' },
    ],
  }));

  const result = await rankArticles(ARTICLES, {
    client, apiKey: 'test', theme: 'compilers', topN: 2, now: NOW,
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.error, null);
  assert.deepEqual(result.ranking.map((pick) => pick.id), ['cccccccccccc', 'aaaaaaaaaaaa']);
  assert.equal(result.ranking[0].reason, 'Deep testing experience.');
});

test('invented ids are rejected and missing slots are filled', async () => {
  const client = stubClient(JSON.stringify({
    picks: [
      { id: 'ffffffffffff', rank: 1, reason: 'Not in the collection.' },
      { id: 'aaaaaaaaaaaa', rank: 2, reason: 'Real article.' },
    ],
  }));

  const result = await rankArticles(ARTICLES, {
    client, apiKey: 'test', theme: 'compilers', topN: 3, now: NOW,
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.rejected, 1);
  assert.equal(result.ranking[0].id, 'aaaaaaaaaaaa');
  assert.equal(result.ranking.length, 3);
  assert.ok(new Set(result.ranking.map((pick) => pick.id)).size === 3);
});

test('fenced JSON is parsed', async () => {
  const client = stubClient('```json\n{"picks":[{"id":"bbbbbbbbbbbb","rank":1,"reason":"Chosen."}]}\n```');
  const result = await rankArticles(ARTICLES, {
    client, apiKey: 'test', theme: 'compilers', topN: 1, now: NOW,
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.ranking[0].id, 'bbbbbbbbbbbb');
});

test('unparseable output falls back deterministically', async () => {
  const result = await rankArticles(ARTICLES, {
    client: stubClient('I cannot answer that.'), apiKey: 'test', theme: 'compilers', topN: 2, now: NOW,
  });

  assert.equal(result.source, 'deterministic');
  assert.equal(result.error, 'unparseable');
  assert.equal(result.ranking.length, 2);
});

test('an API error becomes a code, never a throw', async () => {
  const failure = new Error('rate limited');
  failure.status = 429;

  const result = await rankArticles(ARTICLES, {
    client: stubClient(failure), apiKey: 'test', theme: 'compilers', topN: 2, now: NOW,
  });

  assert.equal(result.source, 'deterministic');
  assert.equal(result.error, 'http_429');
  assert.equal(result.ranking.length, 2);
});

test('validateRanking dedupes and rejects empty reasons', () => {
  const { ranking, rejected } = validateRanking(
    {
      picks: [
        { id: 'aaaaaaaaaaaa', rank: 1, reason: 'First.' },
        { id: 'aaaaaaaaaaaa', rank: 2, reason: 'Duplicate.' },
        { id: 'bbbbbbbbbbbb', rank: 3, reason: '' },
      ],
    },
    ARTICLES,
    5,
  );

  assert.deepEqual(ranking.map((pick) => pick.id), ['aaaaaaaaaaaa']);
  assert.equal(rejected, 2);
});

test('deterministicRank favours recency and theme overlap', () => {
  const ranking = deterministicRank(ARTICLES, { theme: 'compiler diagnostics', topN: 3, now: NOW });

  assert.equal(ranking[0].id, 'aaaaaaaaaaaa');
  assert.equal(ranking.length, 3);
});

test('the ranking prompt frames candidates as data', async () => {
  const client = stubClient(JSON.stringify({ picks: [] }));
  await rankArticles(ARTICLES, { client, apiKey: 'test', theme: 'compilers', topN: 1, now: NOW });

  const [request] = client.calls;
  assert.match(request.messages[0].content, /data/);
  assert.match(request.messages[1].content, /CANDIDATE_ARTICLES_JSON/);
  assert.equal(request.response_format.type, 'json_object');
});

test('a summary is sanitised and capped', async () => {
  const client = stubClient(JSON.stringify({
    headline: `  Head\u0000line ${'x'.repeat(400)}  `,
    dek: 'A short deck.',
    summary: 'First paragraph.\n\n\n\nSecond paragraph with control \u0007 characters.',
    pullQuote: 'A phrase.',
  }));

  const result = await summarizeArticle(ARTICLES[0], {
    client, apiKey: 'test', theme: 'compilers',
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.error, null);
  assert.ok(result.headline.length <= MAX_HEADLINE_LENGTH);
  assert.doesNotMatch(result.headline, /\u0000/);
  assert.equal(result.summary, 'First paragraph.\n\nSecond paragraph with control characters.');
  assert.equal(result.pullQuote, 'A phrase.');
});

test('a summary without a key falls back to the article itself', async () => {
  const result = await summarizeArticle(ARTICLES[0], { apiKey: '', theme: 'compilers' });

  assert.equal(result.source, 'fallback');
  assert.equal(result.error, 'no_key');
  assert.equal(result.headline, ARTICLES[0].title);
  assert.match(result.dek, /error messages/i);
  assert.ok(result.summary.length > 0);
});

test('a summary request failure falls back', async () => {
  const failure = new Error('timeout');
  failure.name = 'APIConnectionTimeoutError';

  const result = await summarizeArticle(ARTICLES[0], {
    client: stubClient(failure), apiKey: 'test', theme: 'compilers',
  });

  assert.equal(result.source, 'fallback');
  assert.equal(result.error, 'timeout');
  assert.equal(result.headline, ARTICLES[0].title);
});

test('summarizeAll keeps input order and summarises every article', async () => {
  const client = stubClient((params) => {
    const title = params.messages[1].content.match(/Title: (.*)/)?.[1] ?? 'Untitled';
    return JSON.stringify({ headline: `Headline: ${title}`, dek: 'Deck.', summary: 'Summary.' });
  });

  const results = await summarizeAll(ARTICLES, {
    client, apiKey: 'test', theme: 'compilers', concurrency: 2,
  });

  assert.equal(results.length, 3);
  assert.match(results[0].headline, /compiler diagnostics/);
  assert.match(results[1].headline, /sorting/);
  assert.match(results[2].headline, /compiler testing/);
});
