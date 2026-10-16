/**
 * Spec step 3: "always provide at least few cameras that are located in
 * 'day-time-zone' in big cities".
 *
 * This is not an error path. A sunset terminator is 20,015 km long and most of
 * it crosses water at any given moment, so "the primary list is thin" is the
 * routine case, not the exceptional one. The fallback is computed on every
 * request, in parallel with the terminator sweep, so the guarantee holds
 * regardless of what the primary search finds.
 */

import { config } from '../config.js';
import { BIG_CITIES } from '../data/big-cities.js';
import { geometricAltitude, sunsetEvents } from './solar.js';
import { ANY_ALTITUDE_DEG, rankCandidates } from './scoring.js';

/**
 * Which big cities are in daylight right now, most populous first.
 *
 * "Daylight" is a strictly positive geometric solar altitude. Geometric rather
 * than apparent, to match the terminator drawn on the map - a city on the drawn
 * line is one the map says is at the boundary.
 */
export function citiesInDaylight(date, sunEq, cities = BIG_CITIES) {
  return cities
    .map((city) => ({
      ...city,
      sunAltitudeDeg: geometricAltitude(city.lat, city.lon, date, sunEq),
    }))
    .filter((city) => city.sunAltitudeDeg > 0)
    .sort((a, b) => b.population - a.population || a.name.localeCompare(b.name));
}

/** How many roster cities must be represented before the candidate count can end the sweep. */
const MIN_FALLBACK_CITIES = 3;

/**
 * How many cameras one roster city may contribute.
 *
 * Two, so a city still contributes a second angle if the list would otherwise be
 * short, but never dominates it.
 */
const MAX_PER_CITY = 2;

/**
 * Pick a spread of fallback cameras rather than the top N overall.
 *
 * `selectPrimary` is not usable here. It dedupes on Windy's own city string, and
 * Windy gives every Tokyo ward its own name - Chiyoda, Shinjuku, Shibuya, Ota,
 * Suginami, Itabashi - so all six look like distinct cities and the "big cities"
 * fallback rendered as six views of one skyline. The cap has to be on the
 * curated roster city that was actually queried, which is what `fallbackCity`
 * records.
 */
function selectSpread(ranked, want) {
  const perCity = new Map();
  const usedSkylines = new Set();
  const chosen = new Set();
  const out = [];

  const take = (camera) => {
    chosen.add(camera.webcamId);
    // Windy's own city name, which within one metropolis is the district. Two
    // cameras in Chiyoda are two views of one view.
    usedSkylines.add(camera.city ?? '');
    out.push(camera);
  };

  // Pass 1: honour the per-roster-city cap.
  for (const camera of ranked) {
    if (out.length >= want) break;
    const key = camera.fallbackCity ?? camera.city ?? camera.webcamId;
    const count = perCity.get(key) ?? 0;
    if (count >= MAX_PER_CITY) continue;
    perCity.set(key, count + 1);
    take(camera);
  }

  // Pass 2: the cap left the list short, so top up - but only with a skyline the
  // gallery does not already show. Without this the top-up simply refilled from
  // whichever city had the most cameras, and the result was two Chiyodas and two
  // Shinjukus in a six-card gallery.
  if (out.length < want) {
    for (const camera of ranked) {
      if (out.length >= want) break;
      if (chosen.has(camera.webcamId)) continue;
      if (usedSkylines.has(camera.city ?? '')) continue;
      take(camera);
    }
  }

  // Pass 3: still short, so the choice is a repeated view or a shorter list than
  // promised. The repeat wins - the spec asks for cameras, not for variety.
  if (out.length < want) {
    for (const camera of ranked) {
      if (out.length >= want) break;
      if (chosen.has(camera.webcamId)) continue;
      take(camera);
    }
  }

  return out;
}

/**
 * Query the daylight cities until enough cameras turn up or the budget runs out.
 *
 * Walking in population order and stopping early means the common case - the
 * first big city has cameras - costs one call instead of four. The budget is
 * hard: these calls share Windy's quota with the terminator sweep.
 */
export async function collectFallback({
  date,
  sunEq,
  subsolar,
  client,
  resolveEvents,
  maxCities = config.chase.fallbackCityCount,
  radiusKm = config.windy.radiusKm,
  limit = config.windy.limit,
  want = config.chase.maxFallbackReturned,
}) {
  const daylight = citiesInDaylight(date, sunEq);
  const tried = [];
  const candidates = [];

  for (const city of daylight) {
    if (tried.length >= maxCities) break;
    // Stop once there is enough to fill the gallery, plus a small margin so
    // ranking has something to choose between - but not on the strength of one
    // city alone. Tokyo can return fifty cameras by itself, and stopping there
    // would make this list a single skyline when the point is big cities,
    // plural.
    if (candidates.length >= want * 2 && tried.length >= MIN_FALLBACK_CITIES) break;

    tried.push(city.name);
    const result = await client.nearby({ lat: city.lat, lon: city.lon, radiusKm, limit });
    for (const webcam of result.webcams) {
      candidates.push({
        ...webcam,
        // Windy's own city field is often empty or oddly cased; the roster's is
        // curated, so prefer it for the fallback list.
        city: webcam.city ?? city.name,
        country: webcam.country ?? city.country,
        fallbackCity: city.name,
      });
    }
  }

  // The fallback set is tiny - at most a few dozen cameras - so unlike the
  // primary sweep it can afford to measure every one of them exactly, rather
  // than ordering cheaply first and measuring a head.
  //
  // `maxAltitudeDeg` is wide open on purpose. These are cameras specifically
  // chosen for standing in daylight, so applying the terminator's 15-degree
  // window would reject every one of them: the fallback would fetch cameras and
  // then discard them, and always report zero.
  const ranked = rankCandidates(candidates, {
    date,
    sunEq,
    subsolar,
    maxAltitudeDeg: ANY_ALTITUDE_DEG,
    resolveEvents:
      resolveEvents ??
      ((webcam) => sunsetEvents(webcam.latitude, webcam.longitude, date, sunEq)),
  });

  return {
    // Ranked within the fallback list, 1..n: these are not competing with the
    // terminator cameras, so a shared rank would be meaningless.
    cameras: selectSpread(ranked, want).map((camera, index) => ({
      ...camera,
      source: 'fallback',
      rank: index + 1,
    })),
    candidatesConsidered: candidates.length,
    citiesTried: tried,
    daylightCityCount: daylight.length,
  };
}
