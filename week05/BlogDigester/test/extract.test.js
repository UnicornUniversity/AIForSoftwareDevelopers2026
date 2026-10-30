import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { ExtractionError, extractArticle, sanitizeText } from '../src/extract.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = await readFile(path.join(here, 'fixtures', 'article.html'), 'utf8');
const URL_UNDER_TEST = 'https://journal.example/posts/compiler';

test('extractArticle captures metadata and readable Markdown', () => {
  const article = extractArticle(fixture, { url: URL_UNDER_TEST });

  assert.equal(article.title, 'How a Small Team Shipped a Compiler');
  assert.equal(article.byline, 'Ada Lovelace');
  assert.equal(article.siteName, 'Example Journal');
  assert.equal(article.publishedAt, '2026-05-01');
  assert.ok(article.wordCount > 100);
  assert.match(article.excerpt, /compiler/i);
});

test('navigation, scripts, forms and footer junk are excluded', () => {
  const { markdown } = extractArticle(fixture, { url: URL_UNDER_TEST });

  assert.doesNotMatch(markdown, /Navigation junk/);
  assert.doesNotMatch(markdown, /alert\(/);
  assert.doesNotMatch(markdown, /Footer junk/);
  assert.doesNotMatch(markdown, /Related links/);
  assert.doesNotMatch(markdown, /Subscribe/);
  assert.doesNotMatch(markdown, /<script/i);
});

test('relative links are absolutised and javascript links are unwrapped', () => {
  const { markdown } = extractArticle(fixture, { url: URL_UNDER_TEST });

  assert.match(markdown, /\(https:\/\/journal\.example\/notes\/reproducible-builds\)/);
  assert.match(markdown, /This link should be neutralised/);
  assert.doesNotMatch(markdown, /javascript:/);
});

test('images keep their alt text and never become remote images', () => {
  const { markdown } = extractArticle(fixture, { url: URL_UNDER_TEST });

  assert.match(markdown, /The four engineers at a whiteboard/);
  assert.doesNotMatch(markdown, /!\[/);
  assert.doesNotMatch(markdown, /team\.jpg/);
});

test('a page without enough readable text fails with a typed error', () => {
  const thin = '<html><body><nav>Menu</nav><p>Too short.</p></body></html>';

  assert.throws(
    () => extractArticle(thin, { url: URL_UNDER_TEST }),
    (err) => err instanceof ExtractionError && err.code === 'too_little_content',
  );
});

test('sanitizeText strips control characters and caps length', () => {
  assert.equal(sanitizeText('  a\u0000b\n\n c  ', 10), 'a b c');
  assert.equal(sanitizeText('x'.repeat(50), 5), 'xxxxx');
  assert.equal(sanitizeText(null), '');
});
