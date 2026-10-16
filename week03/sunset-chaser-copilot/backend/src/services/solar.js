/**
 * The single astronomy seam.
 *
 * Everything astronomical goes through this module, and everything in it goes
 * through `astronomy-engine` (MIT, zero dependencies, +-1 arcminute, VSOP87 +
 * NOVAS, validated against JPL Horizons). Nothing here is hand-rolled: an
 * earlier draft computed the subsolar point from NOAA low-precision formulas and
 * carried a 4x unit error in the equation-of-time term, which put the subsolar
 * longitude 2.7 degrees (about 11 minutes of time) off. Deriving the subsolar
 * longitude as `ra - GAST` removes that arithmetic - and that bug class - entirely.
 */

import * as Astronomy from 'astronomy-engine';
import {
  clamp,
  dedupePath,
  longitudeDelta,
  normalize180,
  round,
  splitAtAntimeridian,
  toDeg,
  toRad,
} from '../lib/geo.js';

/**
 * Geocentric equatorial coordinates of the Sun.
 *
 * The observer sits at the Earth's centre, which makes this geocentric and
 * removes any parallax to correct. Computed once per request and reused for
 * every camera: the Sun's parallax is ~8.8 arcseconds (~0.27 km on the ground),
 * far below anything that could affect a terminator ranking.
 */
export function sunEquatorial(date) {
  const observer = new Astronomy.Observer(0, 0, 0);
  const { ra, dec } = Astronomy.Equator(Astronomy.Body.Sun, date, observer, true, true);
  return { ra, dec };
}

/**
 * The point on Earth where the Sun is directly overhead, plus the derived
 * quantities the rest of the app needs.
 */
export function subsolarPoint(date, sunEq = sunEquatorial(date)) {
  const gastHours = Astronomy.SiderealTime(date);
  const gastDeg = gastHours * 15;
  // Local sidereal time equals right ascension exactly at the subsolar point,
  // so longitude = ra - GAST.
  const subsolarLonDeg = normalize180(sunEq.ra * 15 - gastDeg);
  const declinationDeg = sunEq.dec;

  // Equation of time, in minutes: apparent solar time minus mean solar time.
  //
  // The mean sun sits over longitude 15 * (12 - utcHour); the true sun sits over
  // subsolarLonDeg. Their difference, scaled by 4 minutes per degree, is the
  // equation of time. The mean term is not optional: at 17:00 UTC the subsolar
  // longitude is near -78, and dropping the mean term reports an EoT of 314
  // minutes instead of 14.5. Reported for readers who expect the familiar
  // quantity; nothing in the ranking depends on it.
  const meanSubsolarLonDeg = 15 * (12 - (date.getUTCHours() + date.getUTCMinutes() / 60));
  const equationOfTimeMin = -4 * longitudeDelta(subsolarLonDeg, meanSubsolarLonDeg);

  return {
    utcIso: date.toISOString(),
    utcHour: date.getUTCHours() + date.getUTCMinutes() / 60,
    declinationDeg,
    subsolarLatDeg: declinationDeg,
    subsolarLonDeg,
    equationOfTimeMin: round(equationOfTimeMin, 3),
    gastDeg,
    // How far the terminator reaches toward each pole.
    spanDeg: 90 - Math.abs(declinationDeg),
    polarDayNorth: declinationDeg > 0 && 90 - declinationDeg <= 0,
    polarDaySouth: declinationDeg < 0 && 90 + declinationDeg <= 0,
  };
}

/** Signed hour angle in degrees: positive means past the meridian (afternoon). */
export function hourAngleDeg(lon, date, sunEq, gastDeg) {
  const gast = gastDeg ?? Astronomy.SiderealTime(date) * 15;
  return normalize180(gast + lon - sunEq.ra * 15);
}

/**
 * Geometric solar altitude in degrees, ignoring refraction.
 *
 * Geometric rather than apparent on purpose: the terminator is defined as the
 * geometric day/night boundary, so the drawn arc and the ranking must use the
 * same convention. Apparent sunrise/sunset times come from `sunsetEvents`.
 */
export function geometricAltitude(lat, lon, date, sunEq) {
  const observer = new Astronomy.Observer(lat, lon, 0);
  return Astronomy.Horizon(date, observer, sunEq.ra, sunEq.dec, null).altitude;
}

/**
 * The sunset and sunrise terminator arcs, split at the antimeridian.
 *
 * The terminator is the great circle 90 degrees from the subsolar point, so once
 * the subsolar point is precise this is exact closed-form geometry - no ephemeris
 * call, no approximation.
 *
 * Sampling is uniform in hour angle rather than in latitude. That spaces the
 * points evenly in longitude, which is what a world map wants visually; sampling
 * uniformly in latitude would bunch points near the equator and leave the
 * tangent latitudes (where longitude moves fastest) almost unrepresented.
 *
 *   cos H = -tan(phi) tan(dec)   =>   phi = atan(-cos H cos(dec) / sin(dec))
 *
 * Plain `atan`, not `atan2`: a latitude must land in (-90, 90), and `atan2` with
 * a negative second argument (the southern-hemisphere half of the year) returns
 * angles beyond +-90 - it produced latitudes of 180 before this was caught. The
 * division is safe because the near-equinox case is branched away below.
 */
export function terminatorArcs(subsolar, pointsPerArc = 1800) {
  const dec = subsolar.declinationDeg;
  const lon = subsolar.subsolarLonDeg;
  const n = Math.max(2, Math.min(6000, Math.floor(pointsPerArc)));
  const sinDec = Math.sin(toRad(dec));
  const cosDec = Math.cos(toRad(dec));

  const sunset = [];
  const sunrise = [];

  if (Math.abs(sinDec) < 1e-7) {
    // Equinox: the terminator degenerates to a pair of meridians, and the
    // hour-angle parametrisation above has no unique latitude for a given H.
    // Sweep latitude directly instead.
    for (let i = 0; i <= n; i += 1) {
      const lat = -90 + (180 * i) / n;
      sunset.push([round(normalize180(lon + 90), 3), round(lat, 3)]);
      sunrise.push([round(normalize180(lon - 90), 3), round(lat, 3)]);
    }
  } else {
    for (let i = 0; i <= n; i += 1) {
      const hDeg = (180 * i) / n;
      const lat = toDeg(Math.atan((-Math.cos(toRad(hDeg)) * cosDec) / sinDec));
      sunset.push([round(normalize180(lon + hDeg), 3), round(lat, 3)]);
      sunrise.push([round(normalize180(lon - hDeg), 3), round(lat, 3)]);
    }
  }

  const build = (points) => {
    const clean = dedupePath(points);
    return {
      arcs: splitAtAntimeridian(clean).map((path) => ({ points: path })),
      pointCount: clean.length,
    };
  };

  return { sunset: build(sunset), sunrise: build(sunrise) };
}

/**
 * Exact sunset / civil-twilight events for one location.
 *
 * `SearchRiseSet` corrects for atmospheric refraction (34 arcminutes) and the
 * solar disc's radius, so these are apparent times - the ones a person would
 * look up in an almanac. That is why the duration is measured here rather than
 * estimated from a descent rate: a linearised estimate is 33% low at latitude 60
 * in June (79 min against a true 118 min), which is exactly the long
 * high-latitude summer sunset this app exists to surface.
 *
 * Returns a discriminated result rather than null, because "the sun never sets"
 * and "the sun never rises" are different states, and neither is an error.
 */
export function sunsetEvents(lat, lon, date, sunEq = sunEquatorial(date)) {
  const observer = new Astronomy.Observer(lat, lon, 0);
  const nextSet = Astronomy.SearchRiseSet(Astronomy.Body.Sun, observer, -1, date, 1, 0);
  const prevSet = Astronomy.SearchRiseSet(Astronomy.Body.Sun, observer, -1, date, -1, 0);
  const altitude = geometricAltitude(lat, lon, date, sunEq);

  if (!nextSet) {
    // No sunset within a day: either the sun stays up or it never comes up.
    return {
      kind: altitude > 0 ? 'midnightSun' : 'polarNight',
      minutesToSunset: null,
      sunsetDurationMin: null,
      nextSunsetIso: null,
      sunsetAtIso: null,
    };
  }

  const civilEnd = Astronomy.SearchAltitude(Astronomy.Body.Sun, observer, -1, nextSet.date, 1, -6);
  const sunsetDurationMin = civilEnd
    ? (civilEnd.date.getTime() - nextSet.date.getTime()) / 60000
    : null;

  const now = date.getTime();
  const untilNext = (nextSet.date.getTime() - now) / 60000;
  const sincePrev = prevSet ? (now - prevSet.date.getTime()) / 60000 : null;

  // Take whichever sunset is nearer, rather than testing the sign of the
  // altitude.
  //
  // The altitude sign is the wrong discriminator, because `SearchRiseSet`
  // returns the *apparent* sunset: it fires when the refracted upper limb
  // touches the horizon, which is roughly 0.83 degrees below the geometric
  // horizon. So there is a band of about five minutes in which the geometric
  // altitude is already negative while the sunset is still ahead. Testing
  // `altitude > 0` caught Aberdeen three minutes *before* its sunset, sent it
  // down the "already set" branch, and reported -1437 minutes.
  //
  // Choosing the nearer event needs no such reasoning and is correct on both
  // sides of the boundary. It is also naturally bounded: the chosen value can
  // never exceed about 12 hours.
  let minutesToSunset;
  let sunsetAt;
  if (sincePrev === null || untilNext <= sincePrev) {
    minutesToSunset = untilNext;
    sunsetAt = nextSet.date;
  } else {
    minutesToSunset = -sincePrev;
    sunsetAt = prevSet.date;
  }

  return {
    kind: 'normal',
    minutesToSunset,
    sunsetDurationMin,
    nextSunsetIso: nextSet.date.toISOString(),
    sunsetAtIso: sunsetAt.toISOString(),
    // Retained for callers that want to know which side of the horizon the
    // geometric sun is on; distinct from which side of *sunset* we are on.
    sunIsUp: altitude > 0,
  };
}

/**
 * Cheap Tier-1 phase classification, used to filter ~300 candidates before the
 * expensive Tier-2 searches run on the shortlist.
 */
export function classifyPhase(altitudeDeg, hourAngle, kind) {
  if (kind === 'midnightSun') return 'polarDay';
  if (kind === 'polarNight') return 'polarNight';
  const descending = hourAngle > 0;
  // Only the descending (afternoon) side produces a sunset worth photographing;
  // the ascending side is sunrise.
  if (altitudeDeg > 6) return 'day';
  if (altitudeDeg > 0) return descending ? 'golden_hour' : 'day';
  if (altitudeDeg >= -6) return descending ? 'civil_twilight' : 'night';
  return 'night';
}

export const clampUnit = (x) => clamp(x, -1, 1);
