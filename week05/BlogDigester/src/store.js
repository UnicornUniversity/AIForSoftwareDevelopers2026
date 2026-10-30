import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

export class InvalidUrlError extends Error {
  constructor(message) {
    super(message);
    this.name = 'InvalidUrlError';
    this.status = 400;
  }
}

export class StoreError extends Error {
  constructor(message) {
    super(message);
    this.name = 'StoreError';
  }
}

/** Tracking parameters that never change which article a URL points at. */
const TRACKING_PARAMS = /^(utm_.*|fbclid|gclid|mc_cid|mc_eid|igshid)$/i;

/**
 * Canonical form used for identity and deduplication: absolute http(s) only, no
 * credentials, no fragment, no tracking parameters, sorted query, and no
 * trailing slash on a non-root path. Two URLs that differ only in those ways
 * are the same article.
 */
export function normalizeUrl(input) {
  const raw = typeof input === 'string' ? input.trim() : '';
  if (raw === '') throw new InvalidUrlError('Provide a URL.');

  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new InvalidUrlError('That is not a valid absolute URL.');
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new InvalidUrlError('Only http and https URLs are supported.');
  }
  if (url.username !== '' || url.password !== '') {
    throw new InvalidUrlError('URLs with embedded credentials are not supported.');
  }

  url.hash = '';

  const params = [...url.searchParams.entries()]
    .filter(([key]) => !TRACKING_PARAMS.test(key))
    .sort(([a, av], [b, bv]) => a.localeCompare(b) || av.localeCompare(bv));

  url.search = '';
  for (const [key, value] of params) url.searchParams.append(key, value);

  if (url.pathname.length > 1 && url.pathname.endsWith('/')) {
    url.pathname = url.pathname.slice(0, -1);
  }
  return url.href;
}

/**
 * Stable, filename-safe identity. Twelve hex characters of a SHA-256 over the
 * normalised URL: never derived from page text, so a hostile title cannot
 * influence a path.
 */
export function articleId(normalizedUrl) {
  return createHash('sha256').update(normalizedUrl).digest('hex').slice(0, 12);
}

const ID_PATTERN = /^[a-f0-9]{12}$/;

async function writeAtomic(filePath, content) {
  const tmp = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmp, content, 'utf8');
  await rename(tmp, filePath);
}

function frontmatterValue(value) {
  return value === null || value === undefined ? 'null' : JSON.stringify(String(value));
}

function emptyArticle(url, now) {
  const id = articleId(url);
  return {
    id,
    url,
    addedAt: now().toISOString(),
    title: null,
    siteName: null,
    byline: null,
    publishedAt: null,
    fetchedAt: null,
    status: 'pending',
    error: null,
    file: `articles/${id}.md`,
    wordCount: 0,
    excerpt: null,
  };
}

/**
 * The article list, persisted as data/store.json with its Markdown archive in
 * data/articles/. One instance per process; all writes are whole-file atomic
 * replacements, serialised through `writeQueue`.
 */
export function createStore({ dataDir, now = () => new Date(), warn = console.warn } = {}) {
  if (!dataDir) throw new StoreError('createStore requires a dataDir.');

  const storePath = path.join(dataDir, 'store.json');
  const articlesDir = path.join(dataDir, 'articles');

  let state = null;
  let loading = null;
  let writeQueue = Promise.resolve();

  async function ensureLoaded() {
    if (state) return state;
    if (loading) return loading;

    loading = (async () => {
      await mkdir(articlesDir, { recursive: true });
      let text;
      try {
        text = await readFile(storePath, 'utf8');
      } catch (err) {
        if (err.code !== 'ENOENT') throw err;
        state = { version: 1, articles: [] };
        return state;
      }

      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch (err) {
        throw new StoreError(`${storePath} is not valid JSON (${err.message}). Fix or remove it.`);
      }
      if (!parsed || !Array.isArray(parsed.articles)) {
        throw new StoreError(`${storePath} has an unexpected shape; expected { version, articles: [] }.`);
      }

      state = { version: 1, articles: parsed.articles.filter(isValidArticle) };
      if (state.articles.length !== parsed.articles.length) {
        warn(`[store] ignored ${parsed.articles.length - state.articles.length} malformed entries`);
      }
      return state;
    })().finally(() => {
      loading = null;
    });

    return loading;
  }

  function isValidArticle(entry) {
    return (
      entry &&
      typeof entry === 'object' &&
      typeof entry.id === 'string' &&
      ID_PATTERN.test(entry.id) &&
      typeof entry.url === 'string'
    );
  }

  function persist() {
    const snapshot = JSON.stringify(state, null, 2);
    const run = writeQueue.then(() => writeAtomic(storePath, `${snapshot}\n`));
    writeQueue = run.catch(() => {});
    return run;
  }

  return {
    paths: { dataDir, storePath, articlesDir },

    async list() {
      const { articles } = await ensureLoaded();
      return [...articles];
    },

    async get(id) {
      const { articles } = await ensureLoaded();
      const found = articles.find((article) => article.id === id);
      return found ? { ...found } : null;
    },

    async findByUrl(url) {
      const { articles } = await ensureLoaded();
      const found = articles.find((article) => article.url === url);
      return found ? { ...found } : null;
    },

    /** Returns `{ article, duplicate }`; a duplicate is not written again. */
    async add(inputUrl) {
      const url = normalizeUrl(inputUrl);
      const { articles } = await ensureLoaded();

      const existing = articles.find((article) => article.url === url);
      if (existing) return { article: { ...existing }, duplicate: true };

      const article = emptyArticle(url, now);
      articles.push(article);
      await persist();
      return { article: { ...article }, duplicate: false };
    },

    async remove(id) {
      if (!ID_PATTERN.test(id)) return false;
      const { articles } = await ensureLoaded();
      const index = articles.findIndex((article) => article.id === id);
      if (index === -1) return false;

      articles.splice(index, 1);
      await persist();

      try {
        await unlink(path.join(articlesDir, `${id}.md`));
      } catch (err) {
        if (err.code !== 'ENOENT') throw err;
      }
      return true;
    },

    /** Merge known fields into one article and persist. Returns the new copy. */
    async update(id, patch) {
      if (!ID_PATTERN.test(id)) return null;
      const { articles } = await ensureLoaded();
      const article = articles.find((entry) => entry.id === id);
      if (!article) return null;

      const allowed = [
        'title', 'siteName', 'byline', 'publishedAt', 'fetchedAt',
        'status', 'error', 'wordCount', 'excerpt',
      ];
      for (const key of allowed) {
        if (Object.hasOwn(patch, key)) article[key] = patch[key];
      }
      await persist();
      return { ...article };
    },

    markdownPath(id) {
      if (!ID_PATTERN.test(id)) throw new StoreError('Invalid article id.');
      return path.join(articlesDir, `${id}.md`);
    },

    /** Write the Markdown archive file atomically. */
    async writeMarkdown(id, metadata, body) {
      if (!ID_PATTERN.test(id)) throw new StoreError('Invalid article id.');

      const frontmatter = [
        '---',
        `title: ${frontmatterValue(metadata.title)}`,
        `url: ${frontmatterValue(metadata.url)}`,
        `site: ${frontmatterValue(metadata.siteName)}`,
        `author: ${frontmatterValue(metadata.byline)}`,
        `published: ${frontmatterValue(metadata.publishedAt)}`,
        `fetched: ${frontmatterValue(metadata.fetchedAt)}`,
        `word_count: ${metadata.wordCount ?? 0}`,
        '---',
        '',
      ].join('\n');

      await writeAtomic(path.join(articlesDir, `${id}.md`), `${frontmatter}\n${body.trim()}\n`);
      return `articles/${id}.md`;
    },
  };
}
