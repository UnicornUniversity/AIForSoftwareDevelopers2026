import { createSingleFlightCache } from './cache.js';
import { isPlaylistId, isVideoId } from './store.js';

export class YouTubeError extends Error {
  constructor(code, message, { status = 0, retryAfterMs = null, cause = null } = {}) {
    super(message, cause ? { cause } : undefined);
    this.name = 'YouTubeError';
    this.code = code;
    this.status = status;
    this.retryAfterMs = retryAfterMs;
  }
}

export const YOUTUBE_ERROR_CODES = Object.freeze([
  'youtube_no_key',
  'youtube_404',
  'youtube_quota',
  'youtube_rate_limited',
  'youtube_timeout',
  'youtube_failed',
]);

const DEFAULT_BASE_URL = 'https://www.googleapis.com/youtube/v3';
const ID_CHUNK = 50;
const SEARCH_COST = 100;
const READ_COST = 1;

export function parseIsoDuration(iso) {
  const match = /^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$/.exec(String(iso ?? ''));
  if (!match || (iso && !match[0]) || /^P$/.test(iso)) return 0;
  const [, days = 0, hours = 0, minutes = 0, seconds = 0] = match;
  return (
    Number(days) * 86_400 +
    Number(hours) * 3_600 +
    Number(minutes) * 60 +
    Math.round(Number(seconds))
  );
}

function reasonOf(payload) {
  const errors = payload?.error?.errors;
  return Array.isArray(errors) && errors.length > 0 ? String(errors[0].reason ?? '') : '';
}

function messageOf(payload, fallback) {
  const message = payload?.error?.message;
  return typeof message === 'string' && message.trim() !== '' ? message.trim() : fallback;
}

function retryAfterMsOf(response) {
  const header = response.headers?.get?.('retry-after');
  if (header === null || header === undefined || String(header).trim() === '') return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 30_000);
  return null;
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * YouTube Data API v3 client. The API key is appended to the outgoing request
 * only; it never appears in error messages, logs or cache keys.
 */
export function createYouTubeClient({
  apiKey = '',
  baseUrl = DEFAULT_BASE_URL,
  fetchImpl = globalThis.fetch,
  timeoutMs = 15_000,
  retries = 1,
  cache = createSingleFlightCache({ ttlMs: 300_000 }),
  sleep = defaultSleep,
  warn = console.warn,
} = {}) {
  const quota = { units: 0 };
  let calls = 0;

  function urlFor(endpoint, params) {
    const url = new URL(`${baseUrl.replace(/\/+$/, '')}/${endpoint}`);
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      url.searchParams.set(key, String(value));
    }
    url.searchParams.set('key', apiKey);
    return url;
  }

  async function fetchOnce(endpoint, params, { cost, signal }) {
    const url = urlFor(endpoint, params);
    const signals = [AbortSignal.timeout(timeoutMs)];
    if (signal) signals.push(signal);

    let response;
    try {
      quota.units += cost;
      calls += 1;
      response = await fetchImpl(url, {
        headers: { accept: 'application/json' },
        signal: signals.length === 1 ? signals[0] : AbortSignal.any(signals),
      });
    } catch (err) {
      if (signal?.aborted) {
        throw new YouTubeError('youtube_failed', 'The YouTube request was cancelled.', { cause: err });
      }
      if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
        throw new YouTubeError('youtube_timeout', 'The YouTube API did not answer in time.', { cause: err });
      }
      throw new YouTubeError('youtube_failed', 'Could not reach the YouTube API.', { cause: err });
    }

    if (response.ok) {
      try {
        return await response.json();
      } catch (err) {
        throw new YouTubeError('youtube_failed', 'The YouTube API returned invalid JSON.', { cause: err });
      }
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    const reason = reasonOf(payload);
    if (response.status === 404) {
      throw new YouTubeError('youtube_404', 'The YouTube resource was not found.', { status: 404 });
    }
    if (response.status === 429) {
      throw new YouTubeError('youtube_rate_limited', 'YouTube is rate-limiting this application.', {
        status: 429,
        retryAfterMs: retryAfterMsOf(response),
      });
    }
    if (response.status === 403) {
      if (reason === 'quotaExceeded' || reason === 'dailyLimitExceeded') {
        throw new YouTubeError('youtube_quota', 'The YouTube API daily quota is exhausted.', { status: 403 });
      }
      if (reason === 'rateLimitExceeded' || reason === 'userRateLimitExceeded') {
        throw new YouTubeError('youtube_rate_limited', 'YouTube is rate-limiting this application.', {
          status: 403,
          retryAfterMs: retryAfterMsOf(response),
        });
      }
      throw new YouTubeError('youtube_failed', messageOf(payload, 'YouTube rejected the request.'), { status: 403 });
    }
    if (response.status >= 500) {
      throw new YouTubeError('youtube_failed', 'The YouTube API is temporarily unavailable.', {
        status: response.status,
        retryAfterMs: retryAfterMsOf(response),
      });
    }
    throw new YouTubeError('youtube_failed', messageOf(payload, `YouTube returned HTTP ${response.status}.`), {
      status: response.status,
    });
  }

  async function request(endpoint, params, { cost = READ_COST, signal } = {}) {
    if (!apiKey) {
      throw new YouTubeError('youtube_no_key', 'YouTube API key is not configured.');
    }
    const cacheKey = `${endpoint}?${new URLSearchParams(params).toString()}`;
    const { value } = await cache.run(cacheKey, () => fetchWithRetry(endpoint, params, { cost, signal }));
    return value;
  }

  async function fetchWithRetry(endpoint, params, { cost, signal }) {
    let attempt = 0;
    for (;;) {
      try {
        return await fetchOnce(endpoint, params, { cost, signal });
      } catch (err) {
        const retryable = err instanceof YouTubeError
          && (err.code === 'youtube_rate_limited' || err.code === 'youtube_timeout' || err.status >= 500);
        if (!retryable || attempt >= retries || signal?.aborted) {
          if (signal?.aborted) warn('[youtube] request cancelled');
          throw err;
        }
        const wait = err.retryAfterMs ?? 250 * 2 ** attempt;
        attempt += 1;
        await sleep(wait);
      }
    }
  }

  function assertKey() {
    if (!apiKey) throw new YouTubeError('youtube_no_key', 'YouTube API key is not configured.');
  }

  return {
    hasKey: () => apiKey !== '',
    quota: () => ({ ...quota }),
    calls: () => calls,

    async getVideos(ids = [], { signal } = {}) {
      assertKey();
      const unique = [...new Set(ids.filter(isVideoId))];
      const videos = [];
      for (let index = 0; index < unique.length; index += ID_CHUNK) {
        const chunk = unique.slice(index, index + ID_CHUNK);
        const payload = await request('videos', {
          part: 'snippet,contentDetails',
          id: chunk.join(','),
          maxResults: ID_CHUNK,
        }, { signal });
        for (const item of payload.items ?? []) {
          if (!isVideoId(item?.id)) continue;
          videos.push({
            videoId: item.id,
            title: item.snippet?.title ?? '',
            channel: item.snippet?.channelTitle ?? '',
            channelId: item.snippet?.channelId ?? '',
            publishedAt: item.snippet?.publishedAt ?? null,
            durationSeconds: parseIsoDuration(item.contentDetails?.duration),
          });
        }
      }
      return videos;
    },

    async getPlaylist(id, { signal } = {}) {
      assertKey();
      if (!isPlaylistId(id)) throw new YouTubeError('youtube_failed', 'Invalid playlist id.');
      const payload = await request('playlists', {
        part: 'snippet,contentDetails',
        id,
        maxResults: 1,
      }, { signal });
      const item = payload.items?.[0];
      if (!item) throw new YouTubeError('youtube_404', 'The playlist was not found.', { status: 404 });
      return {
        playlistId: item.id,
        title: item.snippet?.title ?? '',
        channelId: item.snippet?.channelId ?? '',
        channelTitle: item.snippet?.channelTitle ?? '',
        publishedAt: item.snippet?.publishedAt ?? null,
        itemCount: item.contentDetails?.itemCount ?? null,
      };
    },

    async listPlaylistItems(id, { max = 50, signal } = {}) {
      assertKey();
      if (!isPlaylistId(id)) throw new YouTubeError('youtube_failed', 'Invalid playlist id.');
      const limit = Math.max(1, Math.min(Number(max) || 50, 500));
      const items = [];
      let pageToken;

      while (items.length < limit) {
        const payload = await request('playlistItems', {
          part: 'snippet,contentDetails',
          playlistId: id,
          maxResults: Math.min(50, limit - items.length),
          pageToken,
        }, { signal });

        for (const item of payload.items ?? []) {
          const videoId = item.contentDetails?.videoId ?? item.snippet?.resourceId?.videoId;
          if (!isVideoId(videoId)) continue;
          items.push({
            videoId,
            title: item.snippet?.title ?? '',
            channel: item.snippet?.videoOwnerChannelTitle ?? item.snippet?.channelTitle ?? '',
            channelId: item.snippet?.videoOwnerChannelId ?? item.snippet?.channelId ?? '',
            publishedAt: item.contentDetails?.videoPublishedAt ?? item.snippet?.publishedAt ?? null,
            position: item.snippet?.position ?? items.length,
          });
          if (items.length >= limit) break;
        }

        pageToken = payload.nextPageToken;
        if (!pageToken) break;
      }
      return items;
    },

    async searchChannelVideos({ channelId, query = '', max = 50, pages = 1, signal } = {}) {
      assertKey();
      if (typeof channelId !== 'string' || channelId === '') {
        throw new YouTubeError('youtube_failed', 'A channel id is required.');
      }
      const limit = Math.max(1, Math.min(Number(max) || 50, 500));
      const maxPages = Math.max(1, Math.min(Number(pages) || 1, 5));
      const results = [];
      let pageToken;

      for (let page = 0; page < maxPages && results.length < limit; page += 1) {
        const payload = await request('search', {
          part: 'snippet',
          type: 'video',
          channelId,
          q: query || undefined,
          maxResults: Math.min(50, limit - results.length),
          pageToken,
        }, { cost: SEARCH_COST, signal });

        for (const item of payload.items ?? []) {
          const videoId = item.id?.videoId;
          if (!isVideoId(videoId)) continue;
          results.push({
            videoId,
            title: item.snippet?.title ?? '',
            channel: item.snippet?.channelTitle ?? '',
            channelId: item.snippet?.channelId ?? '',
            publishedAt: item.snippet?.publishedAt ?? null,
          });
          if (results.length >= limit) break;
        }

        pageToken = payload.nextPageToken;
        if (!pageToken) break;
      }
      return results;
    },

    async searchChannelPlaylists({ channelId, query = '', max = 10, signal } = {}) {
      assertKey();
      if (typeof channelId !== 'string' || channelId === '') {
        throw new YouTubeError('youtube_failed', 'A channel id is required.');
      }
      const payload = await request('search', {
        part: 'snippet',
        type: 'playlist',
        channelId,
        q: query || undefined,
        maxResults: Math.max(1, Math.min(Number(max) || 10, 50)),
      }, { cost: SEARCH_COST, signal });

      return (payload.items ?? [])
        .filter((item) => isPlaylistId(item.id?.playlistId))
        .map((item) => ({
          playlistId: item.id.playlistId,
          title: item.snippet?.title ?? '',
          channelId: item.snippet?.channelId ?? '',
          channelTitle: item.snippet?.channelTitle ?? '',
          publishedAt: item.snippet?.publishedAt ?? null,
        }));
    },
  };
}
