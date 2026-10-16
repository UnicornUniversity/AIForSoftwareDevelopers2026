/**
 * Turning a heap of candidate webcams into a ranked, explainable list.
 *
 * Two tiers of astronomy meet here. Tier 1 is one `Horizon` call per candidate -
 * cheap enough to run across every camera Windy returns - and decides the phase
 * bucket. Tier 2 is the iterative rise/set search, expensive enough to be worth
 * reserving for the shortlist that survives filtering, and supplies the real
 * sunset time and twilight duration.
 *
 * The deterministic ranking below is not a degradation path. It is the ranking.
 * DeepSeek re-orders and narrates the top of it, but if the model is missing,
 * slow or wrong, the app falls back to exactly these numbers and reasons.
 */

import { config } from '../config.js';
import { clamp, greatCircleOffsetKm, round } from '../lib/geo.js';
import { classifyPhase, geometricAltitude, hourAngleDeg } from './solar.js';

/**
 * Relative importance of each score component.
 *
 * Proximity dominates because the entire premise is "cameras near the
 * terminator". Duration is weighted almost as heavily: the spec explicitly asks
 * us to count on "latitude and duration of the sunset", and a 2-hour Arctic
 * sunset is the payoff this app exists to find. Popularity is deliberately the
 * weakest signal - a high view count says a camera is famous, not that it is
 * looking at anything good right now.
 */
export const SCORE_WEIGHTS = Object.freeze({
  proximity: 0.40,
  duration: 0.20,
  phase: 0.20,
  latitude: 0.10,
  popularity: 0.05,
  cityName: 0.05,
});

/**
 * Cameras further than this from the terminator great circle are not on it in
 * any useful sense. 15 degrees is ~1670 km.
 */
export const MAX_ALTITUDE_DEG = 15;

/**
 * The furthest a sunset can be from a camera worth showing.
 *
 * `sunsetEvents` now returns a measured interval, and its natural range is
 * bounded: it is always the *nearer* of the previous and next sunset, so it can
 * never exceed about 12 hours. Clamping to +-180 (the old guard against the
 * Tier-1 descent-rate ratio blowing up) would report a camera that set eight
 * hours ago as "three hours ago" - the same class of confident falsehood the
 * unmeasured-duration bug produced. This bound is therefore slack by design: it
 * only ever catches a genuinely broken value.
 */
export const MAX_MINUTES_TO_SUNSET = 720;

/** Phase desirability. A sunset in progress is the ideal; plain daylight is not. */
const PHASE_SCORE = Object.freeze({
  sunset: 1.0,
  civil_twilight: 0.85,
  golden_hour: 0.8,
  day: 0.25,
  polarDay: 0.15,
  polarNight: 0,
});

/**
 * Normalise the sunset duration onto 0..1.
 *
 * 20 minutes is roughly an equatorial sunset; 120 minutes is a good Arctic
 * summer one. A `null` duration means the sun never reaches -6 degrees - which
 * near a solstice at high latitude means it does not get dark, not that the
 * camera is bad. Scoring it 0 would systematically punish exactly the
 * high-latitude cameras the spec asks for, so it takes a neutral 0.5.
 */
export function durationScore(sunsetDurationMin) {
  if (sunsetDurationMin === null || sunsetDurationMin === undefined) return 0.5;
  return clamp((sunsetDurationMin - 20) / 100, 0, 1);
}

/** Latitude desirability: rewards the 25-62 degree band, fades toward the poles. */
export function latitudeScore(latDeg) {
  const abs = Math.abs(latDeg);
  if (abs > 66) return 0.2;
  if (abs >= 25 && abs <= 62) return 1.0;
  if (abs >= 62) return 0.5;
  return clamp(abs / 25, 0, 1) * 0.7;
}

/** Log-scaled popularity: view counts span orders of magnitude. */
export function popularityScore(viewCount) {
  if (!Number.isFinite(viewCount) || viewCount <= 0) return 0;
  return clamp(Math.log10(viewCount + 1) / 6, 0, 1);
}

/**
 * An ordering that is total, deterministic and stable.
 *
 * Ties are broken by `webcamId` so two runs over the same data produce the same
 * list in the same order - a requirement, since the adaptive Windy paging and
 * the LLM prompt both depend on a stable top-N.
 */
export function compareScored(a, b) {
  if (b.score !== a.score) return b.score - a.score;
  return a.webcamId.localeCompare(b.webcamId);
}

/**
 * The altitude window a caller wants to accept.
 *
 * The terminator search wants cameras near the terminator, so it uses
 * MAX_ALTITUDE_DEG. The fallback wants big cities in daylight - the sun can be
 * 40 degrees up and that is the point - so it passes 90 and accepts anything
 * above the horizon. Without this, the fallback's own filter removed every
 * camera it had just gone and fetched, and `fallbackCount` was structurally
 * always zero.
 */
export const ANY_ALTITUDE_DEG = 90;

/**
 * Is this camera worth putting in front of a person at all?
 *
 * Applied before scoring, so the Tier-2 searches only run on cameras that can
 * actually appear in the output.
 */
export function passesFilters(webcam, { maxAltitudeDeg = MAX_ALTITUDE_DEG } = {}) {
  if (webcam.status !== 'active') return false;
  if (!webcam.imagePreviewUrl) return false;
  if (!Number.isFinite(webcam.latitude) || !Number.isFinite(webcam.longitude)) return false;
  if (Math.abs(webcam.sunAltitudeDeg) > maxAltitudeDeg) return false;
  return true;
}

/**
 * Cheap distance to the terminator great circle.
 *
 * Exact, not an approximation: the terminator is a great circle, so the
 * perpendicular distance is R times the angular offset. No polyline search.
 *
 * Note what this measures. It is the distance to the great circle, which equals
 * the distance to the *sunset* arc only when the hour angle is positive. A
 * southern-hemisphere camera in its morning can sit on the great circle while
 * being nowhere near the sunset arc, which is why `isDescending` is surfaced
 * alongside it.
 */
export function distanceToTerminatorKm(sunAltitudeDeg) {
  return round(greatCircleOffsetKm(sunAltitudeDeg), 1);
}

/**
 * Tier 1: cheap geometric evaluation of one candidate against the current sun.
 * Mutates nothing and calls no search, so it is safe across hundreds of cameras.
 */
export function evaluateGeometry(webcam, { date, sunEq, subsolar }) {
  const sunAltitudeDeg = geometricAltitude(webcam.latitude, webcam.longitude, date, sunEq);
  const hourAngle = hourAngleDeg(webcam.longitude, date, sunEq, subsolar.gastDeg);

  return {
    sunAltitudeDeg: round(sunAltitudeDeg, 4),
    hourAngleDeg: round(hourAngle, 3),
    isDescending: hourAngle > 0,
    distanceToTerminatorKm: distanceToTerminatorKm(sunAltitudeDeg),
  };
}

/**
 * A deterministic, human-readable reason. Used when the LLM is unavailable, and
 * merged in for any camera the LLM skipped.
 *
 * Written from the numbers rather than from a template with blanks, so it stays
 * true when the numbers are unusual - a camera in polar day, or one with no
 * measurable twilight.
 */
export function deterministicReason(camera) {
  const {
    phase,
    minutesToSunset,
    sunsetDurationMin,
    distanceToTerminatorKm: distance,
    sunsetMeasured = false,
  } = camera;

  if (phase === 'polarDay') return 'Midnight sun: the sun does not set here today.';
  if (phase === 'polarNight') return 'Polar night: the sun stays below the horizon.';

  // A null duration has two very different causes and they must not read the
  // same. Either twilight genuinely never ends (high latitude near a solstice,
  // a real and interesting fact) or the expensive search was never run for this
  // camera. Claiming the first when the second is true would put a confident
  // falsehood in front of a reader - it said "the sun never fully sets" about
  // England in October.
  const duration = !sunsetMeasured
    ? 'Twilight length has not been measured for this camera'
    : sunsetDurationMin === null
      ? 'The sun never fully sets, so twilight lasts all night'
      : `Twilight runs about ${Math.round(sunsetDurationMin)} minutes`;

  if (phase === 'sunset') {
    return `The sun is on the horizon right now, ${distance} km from the terminator line. ${duration}.`;
  }
  if (phase === 'civil_twilight') {
    const ago = minutesToSunset === null ? null : Math.abs(Math.round(minutesToSunset));
    return ago === null
      ? `Just past sunset, still in civil twilight. ${duration}.`
      : `The sun set ${ago} minutes ago and the sky is still lit. ${duration}.`;
  }
  if (phase === 'golden_hour') {
    const away = minutesToSunset === null ? null : Math.round(minutesToSunset);
    return away === null
      ? `Low golden-hour light. ${duration}.`
      : `Golden hour: the sun sets in about ${away} minutes. ${duration}.`;
  }
  return `Daylight, ${distance} km from the terminator line - the sunset arrives later here.`;
}

/** Combine the components into a single 0..1 score with a full breakdown. */
export function scoreCamera(camera, { maxAltitudeDeg = MAX_ALTITUDE_DEG } = {}) {
  const parts = {
    // Normalised against the caller's own window, so a fallback list of daylight
    // cities is still ordered by "closest to the terminator" within that list
    // rather than every entry collapsing to zero.
    proximity: clamp(1 - Math.abs(camera.sunAltitudeDeg) / maxAltitudeDeg, 0, 1),
    duration: durationScore(camera.sunsetDurationMin),
    phase: PHASE_SCORE[camera.phase] ?? 0,
    latitude: latitudeScore(camera.latitude),
    popularity: popularityScore(camera.viewCount),
    cityName: camera.city ? 1 : 0,
  };

  const score = Object.entries(SCORE_WEIGHTS).reduce(
    (sum, [key, weight]) => sum + weight * parts[key],
    0,
  );

  return {
    ...camera,
    score: round(score, 4),
    scoreParts: Object.fromEntries(
      Object.entries(parts).map(([key, value]) => [key, round(value, 4)]),
    ),
  };
}

/**
 * Rank a candidate list, attaching phase, distance and score.
 *
 * `resolveEvents(webcam)` is injected rather than imported so this stays a pure
 * function of its inputs: the caller decides whether Tier 2 runs (it is slow, so
 * production runs it on a shortlist) and tests can supply exact fixtures.
 */
export function rankCandidates(
  candidates,
  { date, sunEq, subsolar, resolveEvents, maxAltitudeDeg = MAX_ALTITUDE_DEG },
) {
  const evaluated = candidates.map((webcam) => {
    const geometry = evaluateGeometry(webcam, { date, sunEq, subsolar });
    const events = resolveEvents ? resolveEvents(webcam) : null;

    const kind = events?.kind ?? 'normal';
    const phase = classifyPhase(geometry.sunAltitudeDeg, geometry.hourAngleDeg, kind);

    const minutesToSunset =
      events?.minutesToSunset === null || events?.minutesToSunset === undefined
        ? null
        : Math.round(clamp(events.minutesToSunset, -MAX_MINUTES_TO_SUNSET, MAX_MINUTES_TO_SUNSET));

    return {
      ...webcam,
      ...geometry,
      phase,
      // Recorded so the reason text can tell "twilight never ends" apart from
      // "nobody measured this one".
      sunsetMeasured: events !== null && events !== undefined,
      minutesToSunset,
      sunsetDurationMin:
        events?.sunsetDurationMin === null || events?.sunsetDurationMin === undefined
          ? null
          : round(events.sunsetDurationMin, 1),
      nextSunsetIso: events?.nextSunsetIso ?? null,
      polarKind: kind,
    };
  });

  const passing = evaluated.filter((webcam) => passesFilters(webcam, { maxAltitudeDeg }));
  const scored = passing.map((camera) => scoreCamera(camera, { maxAltitudeDeg })).sort(compareScored);

  return scored.map((camera, index) => ({
    ...camera,
    rank: index + 1,
    reason: deterministicReason(camera),
    reasonSource: 'deterministic',
  }));
}

/**
 * Cap the list while preferring variety: two cameras in the same city are rarely
 * both worth showing, so the second one is dropped before a camera from
 * somewhere else.
 */
export function selectPrimary(ranked, max = config.chase.maxPrimaryReturned) {
  const byCity = new Map();
  const out = [];

  for (const camera of ranked) {
    if (out.length >= max) break;
    const key = camera.city ? `${camera.city}|${camera.countryCode ?? ''}` : camera.webcamId;
    const count = byCity.get(key) ?? 0;
    if (count >= 1) continue;
    byCity.set(key, count + 1);
    out.push(camera);
  }

  // If deduping by city left the list short, top it up in rank order.
  if (out.length < max) {
    const chosen = new Set(out.map((c) => c.webcamId));
    for (const camera of ranked) {
      if (out.length >= max) break;
      if (chosen.has(camera.webcamId)) continue;
      out.push(camera);
    }
  }

  return out;
}
