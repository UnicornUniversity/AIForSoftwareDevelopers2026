/**
 * The highlight helpers are plain JavaScript, so they are tested with
 * `node --test` directly - no bundler or DOM needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { preview, queryTerms, splitHighlight } from '../src/lib/highlight.js';

test('queryTerms drops stopwords, short words and duplicates', () => {
  assert.deepEqual(queryTerms('Who was Belisarius and what did he do?'), [
    'belisarius',
  ]);
  assert.deepEqual(queryTerms('Caracalla, Caracalla and the constitution'), [
    'caracalla',
    'constitution',
  ]);
});

test('splitHighlight marks whole words case-insensitively', () => {
  const segments = splitHighlight('The Goths fought the goths.', ['goths']);
  assert.deepEqual(
    segments.map((segment) => [segment.text, segment.match]),
    [
      ['The ', false],
      ['Goths', true],
      [' fought the ', false],
      ['goths', true],
      ['.', false],
    ],
  );
});

test('splitHighlight does not match inside a longer word', () => {
  const segments = splitHighlight('Roman and Romanian', ['roman']);
  assert.deepEqual(
    segments.filter((segment) => segment.match).map((segment) => segment.text),
    ['Roman'],
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
