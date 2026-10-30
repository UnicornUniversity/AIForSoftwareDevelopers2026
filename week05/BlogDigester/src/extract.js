import { Readability } from '@mozilla/readability';
import { JSDOM } from 'jsdom';
import TurndownService from 'turndown';

export class ExtractionError extends Error {
  constructor(message, { code = 'extraction_failed' } = {}) {
    super(message);
    this.name = 'ExtractionError';
    this.code = code;
    this.status = 422;
    this.expose = true;
  }
}

export const MIN_CONTENT_CHARS = 400;
const MAX_MARKDOWN_CHARS = 200_000;

const STRIP_SELECTORS = [
  'script', 'style', 'noscript', 'iframe', 'object', 'embed', 'form', 'input',
  'button', 'select', 'textarea', 'svg', 'canvas', 'template',
].join(',');

/** Strip control characters, collapse whitespace, trim and cap. */
export function sanitizeText(value, maxLength = 1000) {
  if (typeof value !== 'string') return '';
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
}

function metaContent(document, selectors) {
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (!element) continue;
    const value = element.getAttribute('content') ?? element.getAttribute('datetime') ?? element.textContent;
    if (value && value.trim() !== '') return value.trim();
  }
  return null;
}

function parsePublishedAt(value, now = new Date()) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const year = date.getUTCFullYear();
  if (year < 1990 || year > now.getUTCFullYear() + 1) return null;
  return date.toISOString().slice(0, 10);
}

function titleFromUrl(url) {
  try {
    const pathname = new URL(url).pathname.replace(/\/+$/, '');
    const segment = pathname.split('/').filter(Boolean).at(-1) ?? '';
    const humanised = decodeURIComponent(segment)
      .replace(/\.(html?|php|aspx?)$/i, '')
      .replace(/[-_]+/g, ' ')
      .trim();
    return humanised || new URL(url).hostname;
  } catch {
    return '';
  }
}

function fallbackHtml(document) {
  const candidates = [...document.querySelectorAll('article, main, [role="main"]')];
  candidates.push(document.body);

  let best = null;
  let bestLength = 0;
  for (const candidate of candidates) {
    if (!candidate) continue;
    const length = (candidate.textContent ?? '').trim().length;
    if (length > bestLength) {
      best = candidate;
      bestLength = length;
    }
  }

  if (!best) return { html: '', textLength: 0 };

  const clone = best.cloneNode(true);
  for (const element of clone.querySelectorAll(STRIP_SELECTORS)) element.remove();
  return { html: clone.innerHTML, textLength: bestLength };
}

function cleanContent(document, html, url) {
  const container = document.createElement('div');
  container.innerHTML = html;

  for (const element of container.querySelectorAll(STRIP_SELECTORS)) element.remove();

  for (const anchor of [...container.querySelectorAll('a[href]')]) {
    let target = null;
    try {
      target = new URL(anchor.getAttribute('href'), url);
    } catch {
      // Leave the link but make it inert below.
    }

    if (!target || (target.protocol !== 'http:' && target.protocol !== 'https:')) {
      anchor.replaceWith(...anchor.childNodes);
      continue;
    }
    anchor.setAttribute('href', target.href);
    anchor.setAttribute('rel', 'noopener noreferrer');
  }

  return container.innerHTML;
}

function createTurndown() {
  const turndown = new TurndownService({
    headingStyle: 'atx',
    hr: '---',
    bulletListMarker: '-',
    codeBlockStyle: 'fenced',
    emDelimiter: '*',
    strongDelimiter: '**',
    linkStyle: 'inlined',
  });

  turndown.remove(['script', 'style', 'noscript', 'iframe', 'form', 'svg', 'canvas', 'template']);

  // The digest is text: keep the caption, never the remote image. This avoids
  // tracking pixels and hotlink failures in the archive and the front page.
  turndown.addRule('image-alt-text', {
    filter: 'img',
    replacement: (_content, node) => {
      const alt = sanitizeText(node.getAttribute('alt') ?? '', 200);
      return alt === '' ? '' : alt;
    },
  });

  return turndown;
}

/**
 * Turn a fetched page into clean Markdown plus metadata.
 *
 * Extraction failures are expected on paywalls and JavaScript-only sites; they
 * throw `ExtractionError` so the orchestrator can mark that one article failed
 * and carry on.
 */
export function extractArticle(html, { url, minContentChars = MIN_CONTENT_CHARS, now = new Date() } = {}) {
  const dom = new JSDOM(String(html ?? ''), { url });
  const { document } = dom.window;

  const publishedAt = parsePublishedAt(
    metaContent(document, [
      'meta[property="article:published_time"]',
      'meta[property="og:article:published_time"]',
      'meta[name="date"]',
      'meta[name="pubdate"]',
      'time[datetime]',
    ]),
    now,
  );

  const siteName = sanitizeText(
    metaContent(document, ['meta[property="og:site_name"]']) ?? new URL(url).hostname,
    200,
  );
  const metaAuthor = sanitizeText(metaContent(document, ['meta[name="author"]']) ?? '', 200);
  const metaTitle = sanitizeText(
    metaContent(document, ['meta[property="og:title"]', 'meta[name="twitter:title"]']) ?? '',
    300,
  );

  let readability = null;
  try {
    readability = new Readability(document.cloneNode(true), { charThreshold: 500 }).parse();
  } catch {
    readability = null;
  }

  let contentHtml = readability?.content ?? '';
  let textLength = (readability?.textContent ?? '').trim().length;

  if (!readability || textLength < minContentChars) {
    const fallback = fallbackHtml(document);
    if (fallback.textLength >= Math.max(minContentChars, textLength)) {
      contentHtml = fallback.html;
      textLength = fallback.textLength;
    }
  }

  if (!contentHtml || textLength < minContentChars) {
    throw new ExtractionError('The page did not contain enough readable text.', { code: 'too_little_content' });
  }

  const cleaned = cleanContent(document, contentHtml, url);
  const markdown = createTurndown()
    .turndown(cleaned)
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .slice(0, MAX_MARKDOWN_CHARS);

  if (markdown.length < minContentChars) {
    throw new ExtractionError('The page did not contain enough readable text.', { code: 'too_little_content' });
  }

  const title = sanitizeText(readability?.title ?? metaTitle ?? document.title, 300)
    || sanitizeText(titleFromUrl(url), 300)
    || new URL(url).hostname;

  // Readability sometimes calls a one-line byline the excerpt; prefer it only
  // when it is long enough to read as a summary, otherwise take the opening of
  // the body text.
  const excerptSource =
    readability?.excerpt && readability.excerpt.trim().length >= 80
      ? readability.excerpt
      : (readability?.textContent ?? '').trim();
  const excerpt = sanitizeText(excerptSource, 300);

  return {
    title,
    byline: sanitizeText(readability?.byline ?? metaAuthor, 200) || null,
    siteName,
    publishedAt,
    excerpt,
    markdown,
    wordCount: markdown.split(/\s+/).filter(Boolean).length,
  };
}
