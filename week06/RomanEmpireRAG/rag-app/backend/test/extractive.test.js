import { test } from 'node:test';
import assert from 'node:assert/strict';

import { composeExtractiveAnswer, selectQuotes } from '../src/services/extractive.js';
import { chunks } from './fixtures.js';

// Retrieval results in the shape the services receive, independent of how the
// passages were found.
const asResults = (list) =>
  list.map((chunk, index) => ({
    chunk,
    score: 1 - index * 0.1,
    rank: index + 1,
    matchedTerms: [],
  }));

const results = asResults(chunks.slice(0, 3));

test('selectQuotes finds a sentence that answers the question', () => {
  const quotes = selectQuotes('What did Caracalla grant?', results);
  assert.ok(quotes.length >= 1);
  assert.match(quotes[0].text, /Caracalla|Antonine/i);
  assert.ok(quotes.every((quote) => quote.text.length <= 421));
});

test('selectQuotes never returns more than four quotes', () => {
  const many = asResults(chunks);
  assert.ok(selectQuotes('Roman empire Goths emperor', many).length <= 4);
});

test('selectQuotes falls back to opening sentences when nothing matches', () => {
  // No query term occurs in the corpus, but passages were retrieved for the
  // test anyway - the fallback must still say something.
  const quotes = selectQuotes('zzzzz', results);
  assert.ok(quotes.length >= 1);
  assert.ok(quotes.every((quote) => quote.text.length > 0));
});

test('the extractive answer is labelled and quoted, with citations', () => {
  const answer = composeExtractiveAnswer(
    'What did Caracalla grant?',
    results,
    'no_key',
  );

  assert.match(answer, /No model-generated answer is available/);
  assert.match(answer, /no DEEPSEEK_API_KEY is configured/);
  assert.match(answer, /\[1\] “/);
});

test('the extractive answer explains a timeout', () => {
  const answer = composeExtractiveAnswer('What did Caracalla grant?', results, 'timeout');
  assert.match(answer, /timed out/);
});
