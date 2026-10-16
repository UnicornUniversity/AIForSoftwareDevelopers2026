import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, fetchChase } from '../api.js';

/**
 * How often to re-fetch the payload.
 *
 * Deliberately under the free tier's ~10 minute image-token lifetime: refreshing
 * at 5 minutes means the URLs are usually swapped before any of them expire, so
 * the refresh path is a safety net rather than the normal case.
 */
export const POLL_INTERVAL_MS = 300_000;

/**
 * Fetch the chase payload, keep it fresh, and never leave the last good one on
 * screen unlabelled.
 *
 * The states are the point. `stale` is separate from `error` because a poll that
 * fails after a successful load should keep showing real cameras with a warning,
 * not replace them with an error page - the data on screen is still true, just
 * older.
 */
export function useChase({ pollMs = POLL_INTERVAL_MS } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stale, setStale] = useState(false);

  // A ref, not state: the poll and the visibility handler both read it, and
  // neither should restart when it changes.
  const controllerRef = useRef(null);

  const load = useCallback(async ({ isRefresh = false } = {}) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const payload = await fetchChase({ signal: controller.signal });
      if (controller.signal.aborted) return;
      setData(payload);
      setError(null);
      setStale(false);
    } catch (err) {
      if (controller.signal.aborted) return;
      // A failed poll keeps the previous payload and flags it. A failed first
      // load has nothing to keep, so it becomes the error state.
      setError(err instanceof ApiError ? err : new ApiError(String(err?.message ?? err)));
      setStale(true);
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    load();
    return () => controllerRef.current?.abort();
  }, [load]);

  useEffect(() => {
    if (!pollMs) return undefined;

    let timer = null;
    const start = () => {
      if (timer) return;
      timer = setInterval(() => load({ isRefresh: true }), pollMs);
    };
    const stop = () => {
      clearInterval(timer);
      timer = null;
    };

    // A hidden tab polling every five minutes wastes quota on data nobody is
    // looking at. Refreshing on the way back in also fixes the common case of a
    // laptop waking to a payload that is hours old.
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        load({ isRefresh: true });
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [load, pollMs]);

  const refresh = useCallback(() => load({ isRefresh: true }), [load]);

  return { data, error, loading, refreshing, stale, refresh };
}
