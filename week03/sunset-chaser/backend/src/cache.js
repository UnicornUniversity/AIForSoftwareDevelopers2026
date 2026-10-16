/**
 * A TTL cache with single-flight de-duplication.
 *
 * Single-flight matters more than the TTL here. Windy's free tier has no
 * published request quota, and a cold cache miss costs ~20 upstream calls, so
 * without it ten simultaneous page loads would issue ~200 calls instead of ~20.
 * Concurrent callers for the same key are handed the same in-flight promise.
 */

const values = new Map();
const inflight = new Map();

let hits = 0;
let misses = 0;

export function cacheGet(key) {
  const entry = values.get(key);
  if (!entry) return undefined;
  if (entry.expiresAt <= Date.now()) {
    values.delete(key);
    return undefined;
  }
  return entry.value;
}

export function cacheSet(key, value, ttlSeconds) {
  if (ttlSeconds <= 0) return value;
  const now = Date.now();
  values.set(key, { value, storedAt: now, expiresAt: now + ttlSeconds * 1000 });
  return value;
}

/** Age of a cached entry in seconds, or null if absent or expired. */
export function cacheAgeSeconds(key) {
  const entry = values.get(key);
  if (!entry || entry.expiresAt <= Date.now()) return null;
  return Math.max(0, Math.round((Date.now() - entry.storedAt) / 1000));
}

/**
 * Return the cached value, or run `fn` and cache it. Concurrent callers for the
 * same key share one execution.
 *
 * `shouldCache` exists for results that are worth sharing between callers but not
 * worth remembering. A failed DeepSeek curation is the case: it costs about half
 * a second to retry, while a successful one costs twenty, so caching the failure
 * would keep the app degraded for a whole TTL to save nothing.
 */
export async function singleFlight(key, ttlSeconds, fn, { shouldCache = () => true } = {}) {
  const cached = cacheGet(key);
  if (cached !== undefined) {
    hits += 1;
    return { value: cached, cached: true };
  }

  const pending = inflight.get(key);
  if (pending) {
    hits += 1;
    return { value: await pending, cached: true };
  }

  misses += 1;
  const promise = (async () => fn())();
  inflight.set(key, promise);
  try {
    const value = await promise;
    if (shouldCache(value)) cacheSet(key, value, ttlSeconds);
    return { value, cached: false };
  } finally {
    inflight.delete(key);
  }
}

export function cacheStats() {
  return { entries: values.size, inflight: inflight.size, hits, misses };
}

export function clearCache() {
  values.clear();
  inflight.clear();
  hits = 0;
  misses = 0;
}
