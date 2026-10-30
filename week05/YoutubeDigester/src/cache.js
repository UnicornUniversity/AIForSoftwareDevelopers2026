/**
 * A tiny TTL + single-flight cache. Concurrent misses for the same key share one
 * promise, and failures are never cached. TTL 0 disables reuse (useful in tests).
 */
export function createSingleFlightCache({ ttlMs = 300_000, now = Date.now } = {}) {
  const entries = new Map();
  const inflight = new Map();
  let hits = 0;
  let misses = 0;

  return {
    async run(key, fn) {
      const entry = entries.get(key);
      if (entry && entry.expiresAt > now()) {
        hits += 1;
        return { value: entry.value, cached: true };
      }
      if (inflight.has(key)) return inflight.get(key);

      misses += 1;
      const promise = (async () => {
        const value = await fn();
        if (ttlMs > 0) entries.set(key, { value, expiresAt: now() + ttlMs });
        return { value, cached: false };
      })().finally(() => inflight.delete(key));

      inflight.set(key, promise);
      return promise;
    },
    clear() {
      entries.clear();
      inflight.clear();
    },
    stats() {
      return { entries: entries.size, inflight: inflight.size, hits, misses };
    },
  };
}
