import { test } from 'node:test';
import assert from 'node:assert/strict';

import { splitSentences, stem, tokenize } from '../src/lib/text.js';

test('tokenize lower-cases, removes stopwords and folds diacritics', () => {
  assert.deepEqual(tokenize('The HbA1c levels of Róme'), ['hba1c', 'level', 'rome']);
});

test('tokenize drops single characters and separates apostrophes', () => {
  // "patient's" -> "patient" + "s"; the lone "s" is dropped.
  assert.deepEqual(tokenize("The patient's glucose"), ['patient', 'glucose']);
});

test('tokenize returns nothing for a stopword-only question', () => {
  assert.deepEqual(tokenize('What was it that they did?'), []);
});

test('stem only removes safe plural endings', () => {
  assert.equal(stem('therapies'), 'therapy');
  assert.equal(stem('doses'), 'dose');
  assert.equal(stem('cases'), 'case');
  // Words ending in ss/us/is are not plurals.
  assert.equal(stem('status'), 'status');
  assert.equal(stem('this'), 'this');
  assert.equal(stem('was'), 'was');
  assert.equal(stem('dose'), 'dose');
});

test('splitSentences keeps titles and initials inside a sentence', () => {
  const sentences = splitSentences(
    'Dr. Smith reviewed the case. The dose was 10 mg. The patient improved.',
  );
  assert.deepEqual(sentences, [
    'Dr. Smith reviewed the case.',
    'The dose was 10 mg.',
    'The patient improved.',
  ]);

  assert.deepEqual(
    splitSentences('The findings were reviewed by J. Smith. The dose changed.'),
    ['The findings were reviewed by J. Smith.', 'The dose changed.'],
  );
});

test('splitSentences does not break on a mid-sentence e.g.', () => {
  assert.deepEqual(
    splitSentences('Metformin is first-line, e.g. in type 2 diabetes. Insulin is used later.'),
    [
      'Metformin is first-line, e.g. in type 2 diabetes.',
      'Insulin is used later.',
    ],
  );
});
