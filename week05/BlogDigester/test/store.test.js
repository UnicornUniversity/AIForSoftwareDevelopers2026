import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';

import {
  InvalidUrlError,
  StoreError,
  articleId,
  createStore,
  normalizeUrl,
} from '../src/store.js';

const dirs = [];

async function tempDataDir() {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-store-'));
  dirs.push(dir);
  return dir;
}

after(async () => {
  await Promise.all(dirs.map((dir) => rm(dir, { recursive: true, force: true })));
});

test('normalizeUrl canonicalises the forms that mean the same article', () => {
  assert.equal(normalizeUrl('  https://Example.COM/Post/  '), 'https://example.com/Post');
  assert.equal(normalizeUrl('https://example.com/post#section'), 'https://example.com/post');
  assert.equal(normalizeUrl('https://example.com/post/'), 'https://example.com/post');
  assert.equal(normalizeUrl('https://example.com/'), 'https://example.com/');
});

test('normalizeUrl removes tracking parameters and sorts the rest', () => {
  const url = normalizeUrl('https://example.com/post?b=2&utm_source=x&a=1&fbclid=abc');
  assert.equal(url, 'https://example.com/post?a=1&b=2');
});

test('normalizeUrl rejects non-http URLs and embedded credentials', () => {
  assert.throws(() => normalizeUrl('file:///etc/passwd'), InvalidUrlError);
  assert.throws(() => normalizeUrl('javascript:alert(1)'), InvalidUrlError);
  assert.throws(() => normalizeUrl('https://user:pass@example.com/'), InvalidUrlError);
  assert.throws(() => normalizeUrl('not a url'), InvalidUrlError);
  assert.throws(() => normalizeUrl(''), InvalidUrlError);
});

test('articleId is 12 lowercase hex characters and stable', () => {
  const id = articleId('https://example.com/post');
  assert.match(id, /^[a-f0-9]{12}$/);
  assert.equal(id, articleId('https://example.com/post'));
  assert.notEqual(id, articleId('https://example.com/other'));
});

test('add stores a pending article and deduplicates the same URL', async () => {
  const store = createStore({ dataDir: await tempDataDir() });

  const first = await store.add('https://example.com/post/');
  assert.equal(first.duplicate, false);
  assert.equal(first.article.status, 'pending');
  assert.equal(first.article.url, 'https://example.com/post');

  const second = await store.add('https://example.com/post?utm_source=newsletter');
  assert.equal(second.duplicate, true);
  assert.equal(second.article.id, first.article.id);
  assert.equal((await store.list()).length, 1);
});

test('state survives a new store instance for the same directory', async () => {
  const dataDir = await tempDataDir();

  const first = createStore({ dataDir });
  const { article } = await first.add('https://example.com/kept');
  await first.update(article.id, { title: 'Kept', status: 'ok', wordCount: 42 });

  const second = createStore({ dataDir });
  const reloaded = await second.get(article.id);

  assert.equal(reloaded.title, 'Kept');
  assert.equal(reloaded.status, 'ok');
  assert.equal(reloaded.wordCount, 42);
});

test('update ignores unknown fields', async () => {
  const store = createStore({ dataDir: await tempDataDir() });
  const { article } = await store.add('https://example.com/post');

  const updated = await store.update(article.id, { title: 'New', url: 'https://evil.example/', id: 'ffffffffffff' });

  assert.equal(updated.title, 'New');
  assert.equal(updated.url, article.url);
  assert.equal(updated.id, article.id);
});

test('remove deletes the entry and its markdown file', async () => {
  const store = createStore({ dataDir: await tempDataDir() });
  const { article } = await store.add('https://example.com/post');
  await store.writeMarkdown(article.id, { title: 'Post', url: article.url, wordCount: 2 }, '# Post\n\nBody');

  assert.equal(await store.remove(article.id), true);
  assert.equal(await store.remove(article.id), false);
  assert.equal(await store.get(article.id), null);
  assert.equal(await store.remove('not-an-id'), false);
  await assert.rejects(readFile(store.markdownPath(article.id), 'utf8'), { code: 'ENOENT' });
});

test('writeMarkdown writes frontmatter and body atomically', async () => {
  const store = createStore({ dataDir: await tempDataDir() });
  const { article } = await store.add('https://example.com/post');

  const relative = await store.writeMarkdown(
    article.id,
    {
      title: 'A "quoted" title',
      url: article.url,
      siteName: 'Example',
      byline: null,
      publishedAt: '2026-10-01',
      fetchedAt: '2026-10-30T12:00:00.000Z',
      wordCount: 4,
    },
    '# A "quoted" title\n\nBody text.',
  );

  assert.equal(relative, `articles/${article.id}.md`);
  const text = await readFile(store.markdownPath(article.id), 'utf8');
  assert.match(text, /^---\ntitle: "A \\"quoted\\" title"\n/);
  assert.match(text, /author: null/);
  assert.match(text, /word_count: 4/);
  assert.match(text, /\n---\n\n# A "quoted" title/);

  const leftovers = (await readdir(store.paths.articlesDir)).filter((name) => name.endsWith('.tmp'));
  assert.deepEqual(leftovers, []);
});

test('concurrent adds are all persisted', async () => {
  const store = createStore({ dataDir: await tempDataDir() });

  await Promise.all(
    Array.from({ length: 10 }, (_, index) => store.add(`https://example.com/post-${index}`)),
  );

  const reopened = createStore({ dataDir: store.paths.dataDir });
  assert.equal((await reopened.list()).length, 10);
});

test('a corrupt store file reports a clear error instead of discarding data', async () => {
  const dataDir = await tempDataDir();
  await writeFile(path.join(dataDir, 'store.json'), '{ broken', 'utf8');

  await assert.rejects(createStore({ dataDir }).list(), StoreError);
});
