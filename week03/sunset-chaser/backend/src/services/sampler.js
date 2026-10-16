/**
 * Choosing where on a 20,015 km arc to spend a query.
 *
 * The sunset terminator is always a half great circle. Windy's `nearby` radius
 * maxes out at 250 km, so covering it without gaps would take 41 calls - more
 * than this app wants to spend, and mostly wasted. Roughly 22% of the arc's
 * length lies poleward of 72 degrees, running through the Southern Ocean and the
 * Arctic pack ice, where there are essentially no webcams to find.
 *
 * So this is a yield optimisation rather than a coverage problem. Missing a few
 * cameras is fine; returning bad ones is not. Points are placed at *weighted*
 * equal-arc quantiles, where the weight encodes how likely a segment is to hold
 * a camera worth showing.
 */

import { haversineKm, longitudeDelta, normalize180, round, toDeg, toRad } from '../lib/geo.js';

/** Beyond this latitude the arc is ocean and ice; no cameras, so no calls. */
export const MAX_ABS_LAT = 72;

/**
 * Relative camera density (and sunset drama) by latitude band.
 *
 * The 25-62 degree band carries the app's whole premise: long sunsets, and the
 * population centres of Europe, the US, Japan, Chile and New Zealand.
 */
export function densityWeight(latDeg) {
  const abs = Math.abs(latDeg);
  if (abs > MAX_ABS_LAT) return 0;
  if (abs >= 25 && abs <= 62) return 1.0;
  if (abs < 25) return 0.6;
  return 0.45;
}

/**
 * Latitude of the sunset terminator at a given hour angle.
 *
 * Solves cos H = -tan(phi) tan(dec) for phi. Plain `atan` rather than `atan2`,
 * for the reason documented in solar.js.
 */
function latitudeAtHourAngle(hourAngleDeg, declinationDeg) {
  const sinDec = Math.sin(toRad(declinationDeg));
  const cosDec = Math.cos(toRad(declinationDeg));
  if (Math.abs(sinDec) < 1e-7) return 0; // equinox: the arc is a meridian
  return toDeg(Math.atan((-Math.cos(toRad(hourAngleDeg)) * cosDec) / sinDec));
}

/**
 * The latitude band the terminator actually occupies, intersected with the
 * camera-bearing cut. Returns null when nothing in the band is worth querying.
 */
export function terminatorBand(subsolar, maxAbsLat = MAX_ABS_LAT) {
  const span = 90 - Math.abs(subsolar.declinationDeg);
  const hi = Math.min(span, maxAbsLat);
  const lo = Math.max(-span, -maxAbsLat);
  if (hi <= lo) return null;
  return { lo, hi, span };
}

/**
 * Place `count` sample points along the sunset terminator.
 *
 * Walks the arc in fine hour-angle steps - monotone in latitude, so the segment
 * lengths accumulate in order - then picks each sample at the weighted quantile
 * `W_total * (k + 0.5) / count`. Offsetting by a half step keeps the first and
 * last samples off the extreme ends of the band, where a disc would be half
 * wasted.
 *
 * Returns `[{ lat, lon, weight }]`, ordered from the northern tangent point to
 * the southern one (or the reverse, when the declination is northern). Both
 * orderings are fine: callers query the points independently.
 */
export function sampleTerminator(subsolar, count, options = {}) {
  const { maxAbsLat = MAX_ABS_LAT, resolution = 2000 } = options;
  const k = Math.max(1, Math.floor(count));
  const band = terminatorBand(subsolar, maxAbsLat);
  if (!band) return [];

  const subsolarLon = subsolar.subsolarLonDeg;
  const dec = subsolar.declinationDeg;
  const n = Math.max(64, Math.min(8000, Math.floor(resolution)));

  // In-band segments with their weighted ground length.
  const segments = [];
  let totalWeighted = 0;

  let prev = null;
  for (let i = 0; i <= n; i += 1) {
    const hDeg = (180 * i) / n;
    const lat = latitudeAtHourAngle(hDeg, dec);
    const lon = normalize180(subsolarLon + hDeg);
    const point = { lat, lon };
    const inBand = lat >= band.lo && lat <= band.hi;

    if (prev && prev.inBand && inBand) {
      const lengthKm = haversineKm(prev.point.lat, prev.point.lon, lat, lon);
      const midLat = (prev.point.lat + lat) / 2;
      const weight = densityWeight(midLat);
      const weighted = lengthKm * weight;
      if (weighted > 0) {
        segments.push({
          from: prev.point,
          to: point,
          weightedLength: weighted,
          cumulative: totalWeighted + weighted,
        });
        totalWeighted += weighted;
      }
    }

    prev = { point, inBand };
  }

  if (segments.length === 0 || totalWeighted <= 0) return [];

  const samples = [];
  for (let i = 0; i < k; i += 1) {
    const target = (totalWeighted * (i + 0.5)) / k;
    const segment = segments.find((s) => s.cumulative >= target) ?? segments[segments.length - 1];

    // Interpolate within the chosen segment, in longitude-aware fashion so a
    // segment straddling +-180 does not interpolate the long way round.
    const before = segment.cumulative - segment.weightedLength;
    const t =
      segment.weightedLength > 0
        ? Math.min(1, Math.max(0, (target - before) / segment.weightedLength))
        : 0;
    const lat = segment.from.lat + (segment.to.lat - segment.from.lat) * t;
    const lon = normalize180(
      segment.from.lon + longitudeDelta(segment.to.lon, segment.from.lon) * t,
    );

    samples.push({
      lat: round(lat, 4),
      lon: round(lon, 4),
      weight: densityWeight(lat),
    });
  }

  return samples;
}
