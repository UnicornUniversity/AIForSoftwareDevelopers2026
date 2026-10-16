/**
 * Windy Webcams API v3 client.
 *
 * https://api.windy.com/webcams/api/v3/webcams, authenticated with an
 * `x-windy-api-key` header. Two upstream limits shape the design: `limit` caps at
 * 50, and `nearby`'s radius caps at 250 km. A free-tier `offset` may not exceed
 * 1000, which is a non-issue here - this client only ever sends offset 0 or 50.
 *
 * `nearby` is used rather than `bbox` on purpose. A 250 km disc and a 4x4 degree
 * box have almost the same area, but the box is axis-aligned and drags in
 * off-terminator cameras that waste the 50-result `limit`.
 */

import pLimit from 'p-limit';

import { config as defaultConfig } from '../config.js';
import { log as defaultLogger } from '../logger.js';
import { fetchJson as defaultFetchJson, UpstreamError } from '../http.js';
import { clamp, normalize180, round } from '../lib/geo.js';

/**
 * Windy does not return a token expiry, so the frontend's pre-emptive refresh is
 * driven by an estimate rather than a fact. Ten minutes is the observed free-tier
 * lifetime. Named as an estimate wherever it surfaces so nobody treats it as
 * authoritative - the `onError` refresh path is the real guarantee.
 */
export const ASSUMED_TOKEN_TTL_SECONDS = 600;

const INCLUDE = 'images,location,player,urls,categories';

/** Windy's public page for a webcam. Free-tier terms require linking back. */
export function windyPageUrl(webcamId) {
  return `https://www.windy.com/webcams/${webcamId}`;
}

/**
 * Upstream free text as a nullable string.
 *
 * Windy sends the literal string `"unknown"` where it has no value, so passing
 * it through would print "unknown" as a city on a card and score the camera as
 * if it had a city name. Treated as absent, since that is what it means.
 */
function textOrNull(value) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (trimmed === '' || trimmed.toLowerCase() === 'unknown') return null;
  return trimmed;
}

/**
 * Turn one raw v3 webcam into the shape the rest of the app uses.
 *
 * Everything downstream - scoring, the LLM prompt, the frontend - reads this
 * shape, so field renames happen exactly once, here. `title`, `city`, `region`
 * and `country` are untrusted upstream text and are never interpreted as
 * instructions; see llm.js for the prompt-injection handling.
 */
export function normalizeWebcam(raw, { fetchedAt = Date.now() } = {}) {
  if (!raw || raw.webcamId === undefined || raw.webcamId === null) return null;

  const location = raw.location ?? {};
  const current = raw.images?.current ?? {};
  const latitude = Number(location.latitude);
  const longitude = Number(location.longitude);

  // A camera with no coordinates cannot be placed on the terminator, and one
  // with no preview image cannot be shown. Both are dropped rather than
  // rendered as blanks.
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (latitude < -90 || latitude > 90) return null;
  if (typeof current.preview !== 'string' || current.preview === '') return null;

  const webcamId = String(raw.webcamId);
  const lastUpdated = raw.lastUpdatedOn ? new Date(raw.lastUpdatedOn) : null;

  return {
    webcamId,
    status: raw.status ?? 'unknown',
    // `title` keeps the raw string: it is display text, and an empty one is
    // handled by the card rather than by inventing a value.
    title: typeof raw.title === 'string' ? raw.title : '',
    city: textOrNull(location.city),
    region: textOrNull(location.region),
    country: textOrNull(location.country),
    countryCode: textOrNull(location.country_code),
    latitude: round(clamp(latitude, -90, 90), 6),
    // Longitude wraps rather than clamps: 185 and -175 are the same meridian, so
    // clamping would move the camera. Latitude is a real range, so it clamps.
    longitude: round(normalize180(longitude), 6),
    imagePreviewUrl: current.preview,
    imageThumbnailUrl: typeof current.thumbnail === 'string' ? current.thumbnail : null,
    imageIconUrl: typeof current.icon === 'string' ? current.icon : null,
    imageExpiresAt: new Date(fetchedAt + ASSUMED_TOKEN_TTL_SECONDS * 1000).toISOString(),
    playerUrl: raw.player?.day ?? raw.player?.lifetime ?? null,
    windyPageUrl: windyPageUrl(webcamId),
    viewCount: Number.isFinite(Number(raw.viewCount)) ? Number(raw.viewCount) : 0,
    categories: Array.isArray(raw.categories)
      ? raw.categories.map((c) => c?.id ?? c).filter((c) => typeof c === 'string')
      : [],
    lastUpdatedOn: lastUpdated && !Number.isNaN(lastUpdated.getTime()) ? lastUpdated.toISOString() : null,
  };
}

/**
 * A per-request client. Stats are per-instance so a single chase run can report
 * exactly how many upstream calls it spent, and a test can assert it.
 */
export function createWindyClient(options = {}) {
  const cfg = options.config ?? defaultConfig;
  const log = options.logger ?? defaultLogger;
  const fetcher = options.fetchJson ?? defaultFetchJson;

  const stats = {
    callsMade: 0,
    callsFailed: 0,
    rateLimited: false,
    authOk: true,
    emptyPoints: 0,
    saturatedPoints: 0,
    adaptivePages: 0,
  };

  function buildUrl({ lat, lon, radiusKm, limit, offset = 0 }) {
    const url = new URL(`${cfg.windy.baseUrl}/webcams`);
    // Normalise before formatting: an unclamped 185 would be rejected upstream.
    const safeLat = clamp(lat, -90, 90);
    const safeLon = normalize180(lon);
    url.searchParams.set('nearby', `${round(safeLat, 4)},${round(safeLon, 4)},${radiusKm}`);
    url.searchParams.set('limit', String(limit));
    if (offset > 0) url.searchParams.set('offset', String(offset));
    url.searchParams.set('include', INCLUDE);
    return url.toString();
  }

  /** One `nearby` page. Never throws: a failed page degrades to zero results. */
  async function nearby({ lat, lon, radiusKm = cfg.windy.radiusKm, limit = cfg.windy.limit, offset = 0 }) {
    if (cfg.windy.apiKey === '') {
      stats.authOk = false;
      return { webcams: [], total: 0, error: 'no_key' };
    }

    const url = buildUrl({ lat, lon, radiusKm, limit, offset });
    stats.callsMade += 1;

    try {
      const body = await fetcher(url, {
        headers: { 'x-windy-api-key': cfg.windy.apiKey },
        timeoutMs: cfg.windy.timeoutMs,
        retries: 1,
      });

      const list = Array.isArray(body?.webcams) ? body.webcams : [];
      const fetchedAt = Date.now();
      const webcams = list.map((raw) => normalizeWebcam(raw, { fetchedAt })).filter(Boolean);

      return { webcams, total: Number(body?.total) || webcams.length, error: null };
    } catch (err) {
      stats.callsFailed += 1;
      if (err instanceof UpstreamError) {
        if (err.code === 'auth_failed') stats.authOk = false;
        if (err.code === 'rate_limited') stats.rateLimited = true;
      }
      log.warn('windy nearby failed', {
        lat: round(lat, 2),
        lon: round(lon, 2),
        offset,
        code: err?.code ?? 'unknown',
        message: err?.message,
      });
      return { webcams: [], total: 0, error: err?.code ?? 'failed' };
    }
  }

  /**
   * Fetch specific webcams by id, for the per-camera token refresh.
   *
   * Windy's image URLs carry a token that expires in roughly ten minutes, so a
   * long-lived page will eventually hold a dead URL. Re-fetching the one camera
   * whose image broke is far cheaper than reloading the whole chase payload.
   */
  async function byIds(ids) {
    const wanted = ids.map(String).filter(Boolean).slice(0, 20);
    if (wanted.length === 0) return { webcams: [], error: null };

    if (cfg.windy.apiKey === '') {
      stats.authOk = false;
      return { webcams: [], error: 'no_key' };
    }

    const url = new URL(`${cfg.windy.baseUrl}/webcams`);
    url.searchParams.set('webcamIds', wanted.join(','));
    url.searchParams.set('include', INCLUDE);
    stats.callsMade += 1;

    try {
      const body = await fetcher(url.toString(), {
        headers: { 'x-windy-api-key': cfg.windy.apiKey },
        timeoutMs: cfg.windy.timeoutMs,
        retries: 1,
      });
      const list = Array.isArray(body?.webcams) ? body.webcams : [];
      const fetchedAt = Date.now();
      return {
        webcams: list.map((raw) => normalizeWebcam(raw, { fetchedAt })).filter(Boolean),
        error: null,
      };
    } catch (err) {
      stats.callsFailed += 1;
      if (err instanceof UpstreamError) {
        if (err.code === 'auth_failed') stats.authOk = false;
        if (err.code === 'rate_limited') stats.rateLimited = true;
      }
      return { webcams: [], error: err?.code ?? 'failed' };
    }
  }

  /**
   * Query every sample point, then spend a few extra calls on the points that
   * came back saturated.
   *
   * A point returning exactly `limit` results was truncated. Windy does not
   * document the sort order, so the cameras nearest the terminator may be the
   * ones dropped. One follow-up page recovers them, but only for the handful of
   * points with the most to gain - otherwise the budget would double.
   */
  async function collect(points, collectOptions = {}) {
    const {
      radiusKm = cfg.windy.radiusKm,
      limit = cfg.windy.limit,
      concurrency = cfg.windy.concurrency,
      adaptivePages = 3,
    } = collectOptions;

    const gate = pLimit(concurrency);
    const perPoint = [];

    await Promise.all(
      points.map((point, index) =>
        gate(async () => {
          const result = await nearby({ lat: point.lat, lon: point.lon, radiusKm, limit, offset: 0 });
          perPoint[index] = { point, index, initial: result, extra: null };
        }),
      ),
    );

    // Saturating points, most saturated first, tie-broken by index so the choice
    // is deterministic and two identical requests make identical calls.
    const saturated = perPoint
      .filter((entry) => entry && entry.initial.webcams.length >= limit)
      .sort((a, b) => b.initial.total - a.initial.total || a.index - b.index);
    stats.saturatedPoints = saturated.length;

    const extraPoints = saturated.slice(0, Math.max(0, adaptivePages));
    if (extraPoints.length > 0) {
      stats.adaptivePages = extraPoints.length;
      await Promise.all(
        extraPoints.map((entry) =>
          gate(async () => {
            entry.extra = await nearby({
              lat: entry.point.lat,
              lon: entry.point.lon,
              radiusKm,
              limit,
              offset: limit,
            });
          }),
        ),
      );
    }

    const byId = new Map();
    let raw = 0;

    for (const entry of perPoint) {
      if (!entry) continue;
      const pages = [entry.initial, entry.extra].filter(Boolean);
      const count = entry.initial.webcams.length;
      if (count === 0) stats.emptyPoints += 1;

      for (const page of pages) {
        for (const webcam of page.webcams) {
          raw += 1;
          // First writer wins: page 0 before the adaptive page. Duplicates
          // across neighbouring sample points are expected - a city inside two
          // overlapping 250 km discs is one camera, not two.
          if (!byId.has(webcam.webcamId)) {
            byId.set(webcam.webcamId, { ...webcam, samplePointIndex: entry.index });
          }
        }
      }
    }

    const webcams = [...byId.values()];
    log.debug('windy collect complete', {
      points: points.length,
      calls: stats.callsMade,
      raw,
      deduped: webcams.length,
    });

    return { webcams, rawCount: raw, perPoint, stats };
  }

  return { nearby, byIds, collect, stats, buildUrl };
}
