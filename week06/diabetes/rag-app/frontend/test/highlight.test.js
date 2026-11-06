/**
 * The highlight helpers are plain JavaScript, so they are tested with
 * `node --test` directly - no bundler or DOM needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { preview, queryTerms, splitHighlight } from '../src/lib/highlight.js';

test('queryTerms drops stopwords, short words and duplicates', () => {
  assert.deepEqual(queryTerms('What is the HbA1c threshold for diabetes?'), [
    'hba1c',
    'threshold',
    'diabetes',
  ]);
  assert.deepEqual(queryTerms('Diabetes, diabetes and the HbA1c threshold'), [
    'diabetes',
    'hba1c',
    'threshold',
  ]);
});

test('splitHighlight marks whole words case-insensitively', () => {
  const segments = splitHighlight('The insulin lowers glucose.', ['insulin']);
  assert.deepEqual(
    segments.map((segment) => [segment.text, segment.match]),
    [
      ['The ', false],
      ['insulin', true],
      [' lowers glucose.', false],
    ],
  );
});

test('splitHighlight does not match inside a longer word', () => {
  const segments = splitHighlight('Dose and dosage', ['dose']);
  assert.deepEqual(
    segments.filter((segment) => segment.match).map((segment) => segment.text),
    ['Dose'],
  );
});

test('splitHighlight escapes regular-expression characters', () => {
  const segments = splitHighlight('a.b axb', ['a.b']);
  assert.deepEqual(
    segments.filter((segment) => segment.match).map((segment) => segment.text),
    ['a.b'],
  );
});

test('splitHighlight returns the text unmarked when there are no terms', () => {
  assert.deepEqual(splitHighlight('plain text', []), [
    { text: 'plain text', match: false },
  ]);
});

test('preview cuts at a word boundary and signals the cut', () => {
  const text = 'one two three four five six seven';
  const cut = preview(text, 15);
  assert.equal(cut, 'one two three…');
  assert.equal(preview('short', 15), 'short');
});
