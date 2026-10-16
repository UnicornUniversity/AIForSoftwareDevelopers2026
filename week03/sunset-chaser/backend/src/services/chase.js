/**
 * The orchestrator: sun -> sample -> Windy -> score -> curate -> payload.
 *
 * Two properties drive the shape of this function.
 *
 * 1. **It never 5xxes.** The map and the terminator are computed locally from
 *    the ephemeris and are always available; only the camera lists depend on
 *    upstream services. So a missing key, a rejected key or an upstream outage
 *    produces a 200 with complete geometry and empty (or fallback) camera lists,
 *    plus warnings explaining why. A user with no `.env` still gets a working
 *    app that tells them what to configure.
 *
 * 2. **It is deterministic.** Everything here is a pure function of the instant
 *    and the upstream data. The only nondeterminism is which selection the LLM
 *    makes, and that is bounded to reordering and rewording cameras that were
 *    already chosen.
 */

import { config } from '../config.js';
import { cacheAgeSeconds, singleFlight } from '../cache.js';
import { log } from '../logger.js';
import { round } from '../lib/geo.js';
import { subsolarPoint, sunEquatorial, sunsetEvents, terminatorArcs } from './solar.js';
import { sampleTerminator } from './sampler.js';
import { createWindyClient } from './windy.js';
import { rankCandidates, selectPrimary } from './scoring.js';
import { collectFallback } from './fallback.js';
import { applyCuration, curate } from './llm.js';

export const SCHEMA_VERSION = 1;

/**
 * The cache key is a coarse grid on the subsolar point, not a timestamp.
 *
 * Keying on a time bucket would be a mistake: the key would change every bucket
 * no matter how little the sun moved, so the entry could never actually be
 * reused and `CACHE_TTL_SECONDS` would do nothing. Keying on position means the
 * entry survives exactly as long as the terminator has not moved meaningfully.
 *
 * The longitude grid is 1 degree. The terminator sweeps west at 15 degrees per
 * hour, so a key is stable for about four minutes and the terminator moves at
 * most 111 km across its life - comfortably inside the 250 km query radius, so a
 * reused sweep is still the right sweep. Declination moves under 0.4 degrees per
 * day, so two decimals keeps it stable for hours. `CACHE_TTL_SECONDS` then caps
 * the life at five minutes regardless.
 */
export const LON_GRID_DEG = 1;

function cacheKey(subsolar) {
  const dec = subsolar.declinationDeg.toFixed(2);
  const lonGrid = Math.round(subsolar.subsolarLonDeg / LON_GRID_DEG);
  return `chase:${lonGrid}:${dec}:${config.windy.sampleCount}:${config.windy.radiusKm}`;
}

/**
 * The cache key for a model curation.
 *
 * The model call is cached under the sweep's key, and for a stronger reason than
 * the sweep is: it is by far the slowest thing in a request. Live, a
 * `deepseek-flash` curation measures 13-46 seconds, because it is a reasoning
 * model that thinks before it answers. Left uncached, every request bought those
 * seconds again for the same cameras under the same sun, so a warm request cost
 * exactly what a cold one did.
 *
 * The sweep key alone is the right basis, and deliberately so. Keying on the
 * *offered* twelve ids looks more precise and is worse: the Tier-2 pass
 * re-measures the head of the ranking on every request, so a few seconds later
 * the twelfth candidate is a different camera, the key misses, and the cache
 * never hits at all. What defines a curation is the candidate pool it chose
 * from, and the sweep key already identifies that pool for as long as the entry
 * lives. Picks are resolved against the current ranking by id, and
 * `applyCuration` requires three of them to survive, so a curation reused after
 * a small shift can never attach a reason to the wrong kind of camera.
 */
function curationKey(sweepKey) {
  return `${sweepKey}:curate:${config.llm.candidatesOffered}`;
}

/**
 * Rank in two passes so the expensive Tier-2 search is spent on the cameras that
 * will actually be displayed.
 *
 * Gating Tier 2 on iteration order - "the first 60 candidates" - meant the
 * measurement landed on whichever cameras Windy happened to return first, and
 * the cameras that actually reached the page kept a null duration. The reason
 * text then reported the wrong thing about real places.
 *
 * Pass 1 uses cheap geometry only and orders the field. Pass 2 measures the head
 * of that list, which is a superset of everything the payload will show, and
 * re-ranks it. The tail keeps its cheap ordering and is never displayed.
 */
const TIER2_HEAD = 60;

function rankInTwoPasses(candidates, { date, sunEq, subsolar }) {
  if (candidates.length === 0) return [];

  const coarse = rankCandidates(candidates, { date, sunEq, subsolar, resolveEvents: () => null });
  if (coarse.length <= config.chase.maxPrimaryReturned) {
    // Too few to bother: measure them all, since they are all displayable.
    return rankCandidates(candidates, {
      date,
      sunEq,
      subsolar,
      resolveEvents: (webcam) => sunsetEvents(webcam.latitude, webcam.longitude, date, sunEq),
    });
  }

  const head = coarse.slice(0, Math.min(TIER2_HEAD, coarse.length));
  const tail = coarse.slice(Math.min(TIER2_HEAD, coarse.length));

  const measured = new Map(
    head
      .filter((camera) => Math.abs(camera.sunAltitudeDeg) < 12)
      .map((camera) => [
        camera.webcamId,
        sunsetEvents(camera.latitude, camera.longitude, date, sunEq),
      ]),
  );

  const refinedHead = rankCandidates(head, {
    date,
    sunEq,
    subsolar,
    resolveEvents: (webcam) => measured.get(webcam.webcamId) ?? null,
  });

  // Re-number across the join so `rank` is a single ordering again.
  return [...refinedHead, ...tail].map((camera, index) => ({ ...camera, rank: index + 1 }));
}

/**
 * `fetchJson`, `windyConfig` and `llmClient` exist as injection points for tests.
 * Production passes none of them and gets the real Windy client with the real
 * configuration, and a real DeepSeek client.
 */
export async function runChase({
  at = new Date(),
  logger = log,
  fetchJson,
  windyConfig,
  llmConfig,
  llmClient,
} = {}) {
  const started = Date.now();
  const date = at instanceof Date ? at : new Date(at);
  if (Number.isNaN(date.getTime())) throw new Error('invalid date');

  const sunEq = sunEquatorial(date);
  const subsolar = subsolarPoint(date, sunEq);
  const terminator = terminatorArcs(subsolar);

  // Capture the key once: recomputing it later could land on a different grid
  // cell and report the age of an entry that does not exist.
  const sweepKey = cacheKey(subsolar);
  const { value: sweep, cached } = await singleFlight(
    sweepKey,
    config.cacheTtlSeconds,
    () => sweepUpstream({ date, sunEq, subsolar, logger, fetchJson, windyConfig }),
  );

  const warnings = [...sweep.warnings];

  // Tier 2 runs on the head of a cheap Tier-1 ranking, so the measured cameras
  // are the ones that actually reach the page.
  const ranked = rankInTwoPasses(sweep.candidates, { date, sunEq, subsolar });
  const primaryRanked = selectPrimary(ranked, config.chase.maxPrimaryReturned);

  if (primaryRanked.length < config.chase.minPrimaryCameras) {
    warnings.push(
      `Only ${primaryRanked.length} cameras near the terminator (wanted ${config.chase.minPrimaryCameras}); the rest of the arc is over ocean or ice.`,
    );
  }

  const { value: curation, cached: curationCached } = await singleFlight(
    curationKey(sweepKey),
    config.cacheTtlSeconds,
    () =>
      curate(ranked.slice(0, config.llm.candidatesOffered), {
        subsolar,
        client: llmClient,
        apiKey: llmConfig?.apiKey,
      }),
    // Only a usable answer is worth remembering. See `singleFlight`.
    { shouldCache: (result) => result.source === 'deepseek' },
  );

  if (curation.error && curation.error !== 'no_key') {
    warnings.push(`DeepSeek curation unavailable (${curation.error}); showing the deterministic ranking.`);
  }

  const primary = applyCuration(primaryRanked, curation, config.chase.maxPrimaryReturned);

  const fallbackResult = sweep.fallback ?? { cameras: [], citiesTried: [], daylightCityCount: 0 };

  return {
    generatedAt: new Date().toISOString(),
    schemaVersion: SCHEMA_VERSION,
    sun: {
      declinationDeg: round(subsolar.declinationDeg, 3),
      subsolarLatDeg: round(subsolar.subsolarLatDeg, 3),
      subsolarLonDeg: round(subsolar.subsolarLonDeg, 3),
      equationOfTimeMin: subsolar.equationOfTimeMin,
      utcHour: round(subsolar.utcHour, 3),
      sunsetTerminatorSpanDeg: round(subsolar.spanDeg, 3),
      polarDayNorth: subsolar.polarDayNorth,
      polarDaySouth: subsolar.polarDaySouth,
    },
    terminator: {
      resolutionDeg: round(180 / 1800, 4),
      sunset: terminator.sunset,
      sunrise: terminator.sunrise,
      samplePoints: sweep.samplePoints,
    },
    briefing: {
      text: curation.briefing ?? deterministicBriefing(subsolar, primary),
      source: curation.source,
      model: curation.source === 'deepseek' ? config.llm.model : null,
      generatedAt: new Date().toISOString(),
    },
    primary,
    fallback: fallbackResult.cameras,
    meta: {
      durationMs: Date.now() - started,
      // "Degraded" means the app could not do its main job: it has no cameras
      // near the terminator. A missing or failed LLM does not qualify - the
      // ranking and the reasons are then produced deterministically from the
      // same numbers, and are still true. `meta.llm.error` is what reports that.
      degraded: !sweep.windy.authOk || primary.length === 0,
      warnings,
      windy: sweep.windy,
      candidates: {
        raw: sweep.rawCount,
        deduped: sweep.candidates.length,
        passedFilters: ranked.length,
        primaryCount: primary.length,
        fallbackCount: fallbackResult.cameras.length,
      },
      cache: {
        hit: cached,
        ageSeconds: cached ? cacheAgeSeconds(sweepKey) : 0,
        ttlSeconds: config.cacheTtlSeconds,
      },
      llm: {
        used: curation.source === 'deepseek',
        source: curation.source,
        model: curation.model,
        // Kept even when the answer came from the cache: it is the model's own
        // latency, and `cached` says whether this request paid it.
        latencyMs: curation.latencyMs,
        cached: curationCached,
        picksOffered: curation.picksOffered,
        picksAccepted: curation.picksAccepted,
        picksRejected: curation.picksRejected,
        error: curation.error,
      },
      fallbackCitiesTried: fallbackResult.citiesTried,
    },
  };
}

/**
 * Everything that costs a Windy call, behind the cache and single-flight.
 *
 * The primary sweep and the fallback run concurrently: they are independent, and
 * the fallback must succeed even when the primary finds nothing.
 */
async function sweepUpstream({ date, sunEq, subsolar, logger, fetchJson, windyConfig }) {
  const warnings = [];
  const effectiveWindy = windyConfig ? { ...config.windy, ...windyConfig } : config.windy;
  const client = createWindyClient({ logger, fetchJson, config: { windy: effectiveWindy } });

  const samplePoints = sampleTerminator(subsolar, effectiveWindy.sampleCount);

  const authOkBefore = effectiveWindy.apiKey !== '';
  if (!authOkBefore) {
    warnings.push('WINDY_API_KEY is not set, so no live cameras are shown. The terminator and sun geometry are still exact.');
  }

  const [collectResult, fallbackResult] = await Promise.all([
    client.collect(samplePoints, {
      radiusKm: effectiveWindy.radiusKm,
      limit: effectiveWindy.limit,
      concurrency: effectiveWindy.concurrency,
      adaptivePages: 3,
    }),
    collectFallback({
      date,
      sunEq,
      subsolar,
      client,
      radiusKm: effectiveWindy.radiusKm,
      limit: effectiveWindy.limit,
    }).catch((err) => {
      // The fallback is a guarantee, but a failure to compute it must not take
      // the whole payload down with it.
      logger.warn('fallback lookup failed', { message: err?.message });
      warnings.push('The big-city fallback lookup failed.');
      return { cameras: [], citiesTried: [], daylightCityCount: 0 };
    }),
  ]);

  if (client.stats.rateLimited) warnings.push('Windy rate-limited some requests; results may be incomplete.');
  if (collectResult.rawCount === 0 && authOkBefore) {
    warnings.push('Windy returned no webcams anywhere along the terminator. Most of the arc is open ocean.');
  }

  const samplePointsOut = collectResult.perPoint
    .filter(Boolean)
    .map((entry, index) => ({
      lat: entry.point.lat,
      lon: entry.point.lon,
      weight: entry.point.weight,
      results: entry.initial.webcams.length + (entry.extra?.webcams.length ?? 0),
      index,
    }));

  return {
    candidates: collectResult.webcams,
    rawCount: collectResult.rawCount,
    samplePoints: samplePointsOut,
    fallback: fallbackResult,
    warnings,
    windy: {
      callsMade: client.stats.callsMade,
      callsFailed: client.stats.callsFailed,
      rateLimited: client.stats.rateLimited,
      authOk: client.stats.authOk,
      emptyPoints: client.stats.emptyPoints,
      saturatedPoints: client.stats.saturatedPoints,
      adaptivePages: client.stats.adaptivePages,
    },
  };
}

/**
 * The briefing used when the model is unavailable.
 *
 * Written from the actual geometry, so it says something true and specific
 * rather than apologising for a missing model.
 */
export function deterministicBriefing(subsolar, primary) {
  const dec = subsolar.declinationDeg;
  const hemisphere = dec >= 0 ? 'north' : 'south';
  const where = primary.length > 0
    ? `Best light right now is around ${primary[0].city ?? primary[0].title}.`
    : 'The terminator is mostly over open ocean, so the big-city fallback carries the list.';

  return [
    `The sun is overhead at ${Math.abs(dec).toFixed(1)} degrees ${hemisphere} latitude,`,
    `so the sunset line reaches to ${(90 - Math.abs(dec)).toFixed(1)} degrees at its furthest.`,
    where,
  ].join(' ');
}
