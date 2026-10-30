import pLimit from 'p-limit';
import { fetchTranscript as defaultFetchTranscript } from 'youtube-transcript';

import { isVideoId } from './store.js';

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
};

const CONTROL_CHARS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

function decodeEntities(text) {
  return String(text ?? '').replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, name) => {
    const key = name.toLowerCase();
    if (key.startsWith('#x')) {
      const code = Number.parseInt(key.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (key.startsWith('#')) {
      const code = Number.parseInt(key.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[key] ?? match;
  });
}

function cleanText(text) {
  return decodeEntities(text).replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim();
}

/**
 * YouTube's two caption formats report offsets in different units; when the
 * typical segment is shorter than a minute it is seconds, otherwise ms.
 */
function normalizeSegments(segments) {
  const durations = segments
    .map((segment) => Number(segment.duration))
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  const median = durations[Math.floor(durations.length / 2)] ?? 0;
  const scale = median > 0 && median < 60 ? 1000 : 1;

  return segments
    .map((segment) => ({
      text: cleanText(segment.text),
      offset: Number(segment.offset) * scale,
      duration: Number(segment.duration) * scale,
    }))
    .filter((segment) => segment.text !== '');
}

function truncateAt(text, maxChars) {
  if (text.length <= maxChars) return text;
  const slice = text.slice(0, maxChars);
  const lastStop = Math.max(
    slice.lastIndexOf('. '),
    slice.lastIndexOf('? '),
    slice.lastIndexOf('! '),
    slice.lastIndexOf('\n'),
  );
  if (lastStop > maxChars * 0.6) return slice.slice(0, lastStop + 1).trim();
  const lastSpace = slice.lastIndexOf(' ');
  return (lastSpace > maxChars * 0.6 ? slice.slice(0, lastSpace) : slice).trim();
}

/** Timed caption segments → readable paragraphs, capped on a clean boundary. */
export function formatTranscript(segments, { maxChars = 200_000 } = {}) {
  const normalized = normalizeSegments(Array.isArray(segments) ? segments : []);
  if (normalized.length === 0) return { text: '', wordCount: 0, excerpt: '' };

  const paragraphs = [];
  let current = '';
  let previousEnd = null;

  for (const segment of normalized) {
    const gap = previousEnd === null ? 0 : segment.offset - previousEnd;
    if (current !== '' && gap > 2_500) {
      paragraphs.push(current);
      current = '';
    }
    current = current === '' ? segment.text : `${current} ${segment.text}`;
    if (current.length > 500 && /[.!?]["')\]]?$/.test(current)) {
      paragraphs.push(current);
      current = '';
    }
    previousEnd = segment.offset + segment.duration;
  }
  if (current !== '') paragraphs.push(current);

  const text = truncateAt(paragraphs.join('\n\n').replace(/\n{3,}/g, '\n\n').trim(), maxChars);
  const words = text === '' ? [] : text.split(/\s+/);
  const excerpt = truncateAt(words.slice(0, 45).join(' '), 280);

  return { text, wordCount: words.length, excerpt };
}

function isLanguageMissing(err) {
  return err?.name === 'YoutubeTranscriptNotAvailableLanguageError';
}

function classifyError(err, { timedOut = false } = {}) {
  if (timedOut || err?.name === 'TimeoutError' || err?.name === 'AbortError') return 'timeout';
  switch (err?.name) {
    case 'YoutubeTranscriptDisabledError':
    case 'YoutubeTranscriptNotAvailableError':
      return 'no_transcript';
    case 'YoutubeTranscriptNotAvailableLanguageError':
      return 'language_missing';
    case 'YoutubeTranscriptVideoUnavailableError':
      return 'unavailable';
    case 'YoutubeTranscriptTooManyRequestError':
      return 'rate_limited';
    default:
      return 'fetch_failed';
  }
}

function failure(videoId, errorCode, startedAt, message, extra = {}) {
  return {
    ok: false,
    videoId,
    transcriptLanguage: extra.transcriptLanguage ?? null,
    text: '',
    wordCount: 0,
    excerpt: '',
    errorCode,
    errorMessage: message ?? null,
    latencyMs: Date.now() - startedAt,
  };
}

function success(videoId, lang, formatted, startedAt) {
  return {
    ok: true,
    videoId,
    transcriptLanguage: lang ?? null,
    text: formatted.text,
    wordCount: formatted.wordCount,
    excerpt: formatted.excerpt,
    errorCode: null,
    errorMessage: null,
    latencyMs: Date.now() - startedAt,
  };
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Wraps the unofficial `youtube-transcript` package. Every failure becomes a
 * typed result; the fetcher never throws for a missing or disabled transcript.
 */
export function createTranscriptFetcher({
  fetchTranscript = defaultFetchTranscript,
  fetchImpl = globalThis.fetch,
  languages = ['en'],
  allowAutoGenerated = true,
  timeoutMs = 20_000,
  maxChars = 200_000,
  rateLimitRetries = 1,
  concurrency = 3,
  sleep = defaultSleep,
  warn = console.warn,
} = {}) {
  async function attempt(videoId, lang, signal) {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException('Transcript request timed out.', 'TimeoutError'));
    }, timeoutMs);
    timer.unref?.();

    const onAbort = () => controller.abort(signal?.reason);
    if (signal) {
      if (signal.aborted) {
        clearTimeout(timer);
        return { code: 'timeout', message: 'The transcript request was cancelled.' };
      }
      signal.addEventListener('abort', onAbort, { once: true });
    }

    const scopedFetch = (url, init = {}) => fetchImpl(url, { ...init, signal: controller.signal });
    const config = lang ? { lang, fetch: scopedFetch } : { fetch: scopedFetch };

    try {
      const segments = await fetchTranscript(videoId, config);
      if (!Array.isArray(segments) || segments.length === 0) {
        return { code: 'no_transcript', message: 'The transcript is empty.' };
      }
      return { ok: true, segments, lang };
    } catch (err) {
      return { code: classifyError(err, { timedOut }), message: err?.message ?? null, err };
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }

  async function attemptWithRetry(videoId, lang, signal) {
    let retries = 0;
    for (;;) {
      const outcome = await attempt(videoId, lang, signal);
      if (outcome.code === 'rate_limited' && retries < rateLimitRetries && !signal?.aborted) {
        retries += 1;
        warn(`[transcript] YouTube is rate-limiting ${videoId}; retrying once.`);
        await sleep(2_000);
        continue;
      }
      return outcome;
    }
  }

  async function fetchOne(videoId, { signal } = {}) {
    const startedAt = Date.now();
    if (!isVideoId(videoId)) {
      return failure(videoId, 'fetch_failed', startedAt, 'Invalid video id.');
    }
    if (signal?.aborted) {
      return failure(videoId, 'timeout', startedAt, 'The transcript request was cancelled.');
    }

    const preferred = Array.isArray(languages) ? languages.filter((lang) => typeof lang === 'string' && lang) : [];
    let lastCode = 'no_transcript';
    let lastMessage = null;

    for (const lang of preferred) {
      const outcome = await attemptWithRetry(videoId, lang, signal);
      if (outcome.ok) return success(videoId, outcome.lang ?? lang, formatTranscript(outcome.segments, { maxChars }), startedAt);
      lastCode = outcome.code;
      lastMessage = outcome.message;
      if (outcome.code === 'language_missing') continue;
      if (outcome.code === 'no_transcript' || outcome.code === 'unavailable' || outcome.code === 'rate_limited' || outcome.code === 'timeout') {
        return failure(videoId, outcome.code, startedAt, outcome.message);
      }
    }

    if (allowAutoGenerated && !signal?.aborted) {
      const outcome = await attemptWithRetry(videoId, null, signal);
      if (outcome.ok) {
        return success(videoId, outcome.lang ?? null, formatTranscript(outcome.segments, { maxChars }), startedAt);
      }
      lastCode = outcome.code;
      lastMessage = outcome.message;
    }

    const code = lastCode === 'language_missing' ? 'no_transcript' : lastCode;
    return failure(videoId, code, startedAt, lastMessage);
  }

  async function fetchAll(videoIds = [], { concurrency: workerCount = concurrency, delayMs = 0, signal, onEach } = {}) {
    const limitFn = pLimit(Math.max(1, Math.min(Number(workerCount) || 1, 8)));
    const ids = [...new Set(videoIds.filter(isVideoId))];

    return Promise.all(ids.map((videoId, index) => limitFn(async () => {
      if (signal?.aborted) {
        const result = failure(videoId, 'timeout', Date.now(), 'The transcript request was cancelled.');
        await onEach?.(result);
        return result;
      }
      if (delayMs > 0 && index > 0) await sleep(delayMs);
      const result = await fetchOne(videoId, { signal });
      await onEach?.(result);
      return result;
    })));
  }

  return { fetchOne, fetchAll };
}
