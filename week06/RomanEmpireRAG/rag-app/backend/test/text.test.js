import { test } from 'node:test';
import assert from 'node:assert/strict';

import { splitSentences, stem, tokenize } from '../src/lib/text.js';

test('tokenize lower-cases, removes stopwords and folds diacritics', () => {
  assert.deepEqual(tokenize('The Emperors of Róme'), ['emperor', 'rome']);
});

test('tokenize drops single characters and separates apostrophes', () => {
  // "emperor's" -> "emperor" + "s"; the lone "s" is dropped.
  assert.deepEqual(tokenize("The emperor's guard"), ['emperor', 'guard']);
});

test('tokenize returns nothing for a stopword-only question', () => {
  assert.deepEqual(tokenize('What was it that they did?'), []);
});

test('stem only removes safe plural endings', () => {
  assert.equal(stem('armies'), 'army');
  assert.equal(stem('churches'), 'church');
  assert.equal(stem('provinces'), 'province');
  assert.equal(stem('emperors'), 'emperor');
  // Words ending in ss/us/is are not plurals.
  assert.equal(stem('status'), 'status');
  assert.equal(stem('this'), 'this');
  assert.equal(stem('was'), 'was');
  assert.equal(stem('war'), 'war');
});

test('splitSentences keeps initials and abbreviations inside a sentence', () => {
  const sentences = splitSentences(
    'M. Guizot described the decline. He wrote in A.D. 476. The empire fell.',
  );
  assert.deepEqual(sentences, [
    'M. Guizot described the decline.',
    'He wrote in A.D. 476.',
    'The empire fell.',
  ]);
});

test('splitSentences handles St. and returns a single fragment', () => {
  assert.deepEqual(splitSentences('St. Augustine lamented the fall of Rome.'), [
    'St. Augustine lamented the fall of Rome.',
  ]);
});
