import test from 'node:test';
import assert from 'node:assert/strict';

import { haversineKm } from '../src/lib/geo.js';
import {
  geometricAltitude,
  hourAngleDeg,
  subsolarPoint,
  sunEquatorial,
  sunsetEvents,
  terminatorArcs,
} from '../src/services/solar.js';

const at = (iso) => new Date(iso);

/**
 * Regression oracle.
 *
 * These declination and equation-of-time values were derived independently, from
 * closed-form NOAA formulas, *before* astronomy-engine was chosen. They pin the
 * library integration: the declination checks the ephemeris, and the equation of
 * time - recovered from the subsolar longitude as `EoT = -lon / 4` - checks the
 * sidereal-time path. Matching both annual extremes pins the sign, magnitude and
 * phase far better than any single city's sunset time.
 *
 * This is precisely the arithmetic where a hand-rolled draft had a 4x unit error:
 * `EoT/60` divides degrees where minutes were meant, which put the subsolar
 * longitude at -0.90 instead of -3.61 for the 2026-10-16 row below.
 */
const ORACLE = [
  { iso: '2026-02-11T12:00:00Z', dec: -13.92, eotMin: -14.2, note: 'EoT annual minimum' },
  { iso: '2026-03-20T12:00:00Z', dec: -0.04, eotMin: -7.46, note: 'March equinox' },
  { iso: '2026-06-21T12:00:00Z', dec: 23.44, eotMin: -1.83, note: 'June solstice' },
  { iso: '2026-10-16T12:00:00Z', dec: -8.99, eotMin: 14.45, note: 'mid-October' },
  { iso: '2026-11-03T12:00:00Z', dec: -15.15, eotMin: 16.45, note: 'EoT annual maximum' },
  { iso: '2026-12-21T12:00:00Z', dec: -23.44, eotMin: 1.94, note: 'December solstice' },
];

test('subsolar declination matches the regression oracle', () => {
  for (const row of ORACLE) {
    const sun = subsolarPoint(at(row.iso));
    assert.ok(
      Math.abs(sun.declinationDeg - row.dec) < 0.1,
      `${row.note} (${row.iso}): declination ${sun.declinationDeg.toFixed(3)}, expected ~${row.dec}`,
    );
  }
});

test('equation of time matches the regression oracle, including both extremes', () => {
  for (const row of ORACLE) {
    const sun = subsolarPoint(at(row.iso));
    assert.ok(
      Math.abs(sun.equationOfTimeMin - row.eotMin) < 0.15,
      `${row.note} (${row.iso}): EoT ${sun.equationOfTimeMin.toFixed(2)} min, expected ~${row.eotMin}`,
    );
  }
});

test('equation of time is referenced to the mean sun, not raw subsolar longitude', () => {
  // The oracle rows all sit at 12:00 UTC, where the mean-sun term vanishes and
  // `-4 * subsolarLon` happens to be correct. Away from noon it is not: at 17:00
  // UTC the subsolar longitude is near -78, so dropping the mean term reports
  // ~314 minutes instead of ~14.5. The equation of time is a property of the
  // date, so the two hours below must agree to well under a minute.
  const noon = subsolarPoint(at('2026-10-16T12:00:00Z'));
  const evening = subsolarPoint(at('2026-10-16T17:00:00Z'));

  assert.ok(
    Math.abs(evening.equationOfTimeMin - 14.45) < 0.3,
    `17:00 UTC EoT ${evening.equationOfTimeMin.toFixed(2)}, expected ~14.45`,
  );
  assert.ok(
    Math.abs(evening.equationOfTimeMin - noon.equationOfTimeMin) < 0.2,
    `EoT drifted ${(evening.equationOfTimeMin - noon.equationOfTimeMin).toFixed(2)} min across five hours of one day`,
  );
});

test('subsolar longitude is not the buggy 4x-off value', () => {
  // Guards the specific defect found in the hand-rolled prototype.
  const sun = subsolarPoint(at('2026-10-16T12:00:00Z'));
  assert.ok(Math.abs(sun.subsolarLonDeg - -3.61) < 0.1, `got ${sun.subsolarLonDeg}`);
  assert.ok(Math.abs(sun.subsolarLonDeg - -0.9) > 1, 'regressed to the EoT/60 value');
});

test('solstice declination equals the axial tilt', () => {
  const june = subsolarPoint(at('2026-06-21T12:00:00Z'));
  const december = subsolarPoint(at('2026-12-21T12:00:00Z'));
  assert.ok(Math.abs(Math.abs(june.declinationDeg) - 23.44) < 0.05);
  assert.ok(Math.abs(Math.abs(december.declinationDeg) - 23.44) < 0.05);
  assert.ok(june.declinationDeg > 0 && december.declinationDeg < 0, 'seasons are the right way round');
});

test('the sunset terminator is a half great circle, 20015 km long', () => {
  // The single most valuable assertion in this file: any longitude unit slip
  // (degrees vs radians, wrapped vs unwrapped) shows up here as an arc length
  // that is wildly wrong - a prototype of this code once produced 25 million km.
  const expected = Math.PI * 6371;
  for (const iso of ['2026-03-20T12:00:00Z', '2026-06-21T12:00:00Z', '2026-10-16T12:00:00Z']) {
    const arcs = terminatorArcs(subsolarPoint(at(iso)));
    let total = 0;
    for (const arc of arcs.sunset.arcs) {
      for (let i = 1; i < arc.points.length; i += 1) {
        const [lon1, lat1] = arc.points[i - 1];
        const [lon2, lat2] = arc.points[i];
        total += haversineKm(lat1, lon1, lat2, lon2);
      }
    }
    assert.ok(
      Math.abs(total - expected) < 50,
      `${iso}: sunset arc is ${total.toFixed(1)} km, expected ${expected.toFixed(1)}`,
    );
  }
});

test('terminator arcs are split at the antimeridian, never streaking across the map', () => {
  for (const iso of ['2026-01-15T00:00:00Z', '2026-06-21T18:00:00Z', '2026-10-16T06:00:00Z']) {
    const arcs = terminatorArcs(subsolarPoint(at(iso)));
    for (const arc of arcs.sunset.arcs) {
      for (let i = 1; i < arc.points.length; i += 1) {
        const jump = Math.abs(arc.points[i][0] - arc.points[i - 1][0]);
        assert.ok(jump <= 180, `${iso}: an unsplit ${jump.toFixed(1)}-degree jump remains`);
      }
    }
  }
});

test('terminator reaches exactly the tangent latitude 90 - |declination|', () => {
  const sun = subsolarPoint(at('2026-10-16T12:00:00Z'));
  const arcs = terminatorArcs(sun);
  const lats = arcs.sunset.arcs.flatMap((a) => a.points.map((p) => p[1]));
  const maxAbs = Math.max(...lats.map(Math.abs));
  assert.ok(
    Math.abs(maxAbs - sun.spanDeg) < 0.2,
    `arcs reach ${maxAbs.toFixed(2)} degrees, expected ~${sun.spanDeg.toFixed(2)}`,
  );
});

test('equinox terminator degenerates to a meridian pair without NaN', () => {
  // tan(declination) -> 0 makes the hour-angle parametrisation singular; the
  // latitude sweep must take over and still produce finite coordinates.
  const sun = subsolarPoint(at('2026-03-20T12:00:00Z'));
  const arcs = terminatorArcs(sun);
  const lons = arcs.sunset.arcs.flatMap((a) => a.points.map((p) => p[0]));
  for (const lon of lons) assert.ok(Number.isFinite(lon), `non-finite longitude ${lon}`);
  const lats = arcs.sunset.arcs.flatMap((a) => a.points.map((p) => p[1]));
  assert.ok(Math.max(...lats) > 89 && Math.min(...lats) < -89, 'should span pole to pole');
});

test('distance to the terminator equals R * |altitude| for an afternoon city', () => {
  // The terminator is a great circle, so the perpendicular distance to it is
  // exactly R * |h| in radians - no haversine-to-polyline search required.
  const date = at('2026-10-16T17:00:00Z');
  const sunEq = sunEquatorial(date);
  const sun = subsolarPoint(date, sunEq);
  const arcs = terminatorArcs(sun, 3600);

  for (const [name, lat, lon] of [
    ['Lisbon', 38.72, -9.14],
    ['Reykjavik', 64.15, -21.94],
  ]) {
    const h = geometricAltitude(lat, lon, date, sunEq);
    assert.ok(hourAngleDeg(lon, date, sunEq, sun.gastDeg) > 0, `${name} should be in the afternoon`);

    let nearest = Infinity;
    for (const arc of arcs.sunset.arcs) {
      for (const [plon, plat] of arc.points) {
        if (Math.abs(plon - lon) > 180) continue;
        nearest = Math.min(nearest, haversineKm(lat, lon, plat, plon));
      }
    }
    const expected = 6371 * Math.abs((h * Math.PI) / 180);
    assert.ok(
      Math.abs(nearest - expected) < 20,
      `${name}: nearest arc vertex ${nearest.toFixed(1)} km vs R*|h| ${expected.toFixed(1)} km`,
    );
  }
});

test('sunset duration reflects the true high-latitude summer, not a linear estimate', () => {
  // The critical regression. A linearised descent-rate estimate gives ~79 minutes
  // at latitude 60 on the June solstice; the true value is ~107 minutes. That
  // case - the long, slow, high-latitude summer sunset - is the whole point of
  // the app, so it must not be approximated.
  const june = sunsetEvents(60, 0, at('2026-06-21T12:00:00Z'));
  assert.ok(
    june.sunsetDurationMin > 100,
    `latitude 60 June solstice gave ${june.sunsetDurationMin?.toFixed(1)} min; ` +
      'the linear estimate (79) has been reintroduced',
  );
  assert.ok(june.sunsetDurationMin < 130, `implausibly long: ${june.sunsetDurationMin}`);

  // Lower latitudes and other seasons, each with a sane band.
  const cases = [
    ['equator at equinox', 0, 0, '2026-03-20T12:00:00Z', 16, 26],
    ['latitude 60 at equinox', 60, 0, '2026-03-20T12:00:00Z', 36, 48],
    ['latitude 45 at December solstice', 45, 0, '2026-12-21T12:00:00Z', 28, 40],
    ['latitude 30 in mid-October', 30, 0, '2026-10-16T12:00:00Z', 18, 30],
  ];
  for (const [name, lat, lon, iso, lo, hi] of cases) {
    const e = sunsetEvents(lat, lon, at(iso));
    assert.ok(
      e.sunsetDurationMin > lo && e.sunsetDurationMin < hi,
      `${name}: ${e.sunsetDurationMin?.toFixed(1)} min, expected between ${lo} and ${hi}`,
    );
  }
});

test('sunset duration grows with latitude on a given date', () => {
  const date = at('2026-10-16T12:00:00Z');
  const durations = [0, 20, 40, 55].map((lat) => sunsetEvents(lat, 0, date).sunsetDurationMin);
  for (let i = 1; i < durations.length; i += 1) {
    assert.ok(
      durations[i] > durations[i - 1],
      `latitude band ${i} (${durations[i].toFixed(1)}) should exceed the previous (${durations[i - 1].toFixed(1)})`,
    );
  }
});

test('apparent sunset matches the published almanac time', () => {
  // London, 16 October 2026: published sunset ~18:05 BST = 17:05 UTC.
  const e = sunsetEvents(51.5074, -0.1278, at('2026-10-16T12:00:00Z'));
  const minutes = new Date(e.nextSunsetIso);
  const utcMinutes = minutes.getUTCHours() * 60 + minutes.getUTCMinutes();
  assert.ok(
    Math.abs(utcMinutes - (17 * 60 + 5)) <= 4,
    `London sunset at ${e.nextSunsetIso}, expected ~17:05Z`,
  );
});

test('London mid-summer has a long day and an evening sunset', () => {
  // A naive bisection on a wrapped hour angle returned *identical* sunrise and
  // sunset times for this exact case, so it earns an explicit regression test.
  const e = sunsetEvents(51.5074, -0.1278, at('2026-06-21T12:00:00Z'));
  assert.equal(e.kind, 'normal');
  assert.ok(e.minutesToSunset > 0, 'London at noon in June is before sunset');

  const sunset = new Date(e.nextSunsetIso);
  const utcMinutes = sunset.getUTCHours() * 60 + sunset.getUTCMinutes();
  // Published London sunset on 21 June 2026 is ~20:15Z (21:15 BST).
  assert.ok(
    Math.abs(utcMinutes - (20 * 60 + 15)) <= 6,
    `London June sunset at ${e.nextSunsetIso}, expected ~20:15Z`,
  );
});

test('a camera minutes before its sunset is not reported as already set', () => {
  // `SearchRiseSet` returns the *apparent* sunset: it fires when the refracted
  // upper limb touches the horizon, about 0.83 degrees below the geometric
  // horizon. So there is a five-minute band where the geometric altitude is
  // already negative while the sunset is still ahead. Selecting the branch by
  // `altitude > 0` caught Aberdeen three minutes before its sunset, took the
  // "already set" path, and measured the *previous* day's sunset - reporting
  // -1437 minutes, which the client then clamped to a confident "-180".
  const at1700 = at('2026-10-16T17:00:00Z');
  const e = sunsetEvents(57.1497, -2.0943, at1700); // Aberdeen

  assert.equal(e.kind, 'normal');
  assert.equal(e.sunIsUp, false, 'the refracted sun is already down');

  // The sunset has not happened yet, so the countdown runs forward and is small.
  assert.ok(
    e.minutesToSunset > 0 && e.minutesToSunset < 15,
    `Aberdeen should be minutes from sunset, got ${e.minutesToSunset}`,
  );
  assert.ok(
    new Date(e.sunsetAtIso).getTime() > at1700.getTime(),
    'the chosen sunset must be in the future, not yesterday',
  );
  assert.equal(e.sunsetAtIso, e.nextSunsetIso, 'with the sunset ahead, both fields name the same event');
});

test('minutesToSunset is the nearer sunset, on both sides of the boundary', () => {
  // The rule that replaced the altitude test: whichever sunset is nearer wins.
  // Bounded by construction at about 12 hours, so it needs no clamp to stay
  // sane and never mixes a future event with a past one.
  const now = at('2026-10-16T17:00:00Z');
  const cases = [
    { name: 'Aberdeen', lat: 57.1497, lon: -2.0943, expect: 'future', max: 15 },
    { name: 'London', lat: 51.5072, lon: -0.1276, expect: 'future', max: 15 },
    { name: 'New York', lat: 40.7128, lon: -74.006, expect: 'future', max: 360 },
    { name: 'Sydney', lat: -33.8688, lon: 151.2093, expect: 'past', min: 400 },
  ];

  for (const c of cases) {
    const e = sunsetEvents(c.lat, c.lon, now);
    if (c.expect === 'future') {
      assert.ok(
        e.minutesToSunset > 0 && e.minutesToSunset < c.max,
        `${c.name}: expected a near-future sunset, got ${e.minutesToSunset}`,
      );
    } else {
      // Sydney set hours ago and its next sunset is further away, so the honest
      // answer is a large negative number - not one flattened to -180.
      assert.ok(
        e.minutesToSunset < -c.min,
        `${c.name}: expected a genuinely long-past sunset, got ${e.minutesToSunset}`,
      );
      assert.ok(
        new Date(e.sunsetAtIso).getTime() < now.getTime(),
        `${c.name}: the chosen sunset must be in the past`,
      );
    }
    assert.ok(
      Math.abs(e.minutesToSunset) <= 720,
      `${c.name}: ${e.minutesToSunset} exceeds the 12-hour bound the rule guarantees`,
    );
  }
});

test('polar day and polar night are distinguished, not returned as NaN', () => {
  const tromso = { lat: 69.6492, lon: 18.9553 };
  const june = sunsetEvents(tromso.lat, tromso.lon, at('2026-06-21T12:00:00Z'));
  const december = sunsetEvents(tromso.lat, tromso.lon, at('2026-12-21T12:00:00Z'));

  assert.equal(june.kind, 'midnightSun', 'Tromso in June has no sunset');
  assert.equal(december.kind, 'polarNight', 'Tromso in December has no sunrise');
  for (const e of [june, december]) {
    assert.equal(e.minutesToSunset, null);
    assert.equal(e.sunsetDurationMin, null);
    assert.ok(!Number.isNaN(e.minutesToSunset));
  }

  // And a normal day at the same place still works.
  const october = sunsetEvents(tromso.lat, tromso.lon, at('2026-10-16T12:00:00Z'));
  assert.equal(october.kind, 'normal');
  assert.ok(Number.isFinite(october.minutesToSunset));
});

test('hour angle is positive in the afternoon and negative in the morning', () => {
  const date = at('2026-10-16T12:00:00Z');
  const sunEq = sunEquatorial(date);
  const sun = subsolarPoint(date, sunEq);
  // The subsolar meridian is local noon; east of it is afternoon.
  assert.ok(hourAngleDeg(sun.subsolarLonDeg + 30, date, sunEq, sun.gastDeg) > 0, 'east is afternoon');
  assert.ok(hourAngleDeg(sun.subsolarLonDeg - 30, date, sunEq, sun.gastDeg) < 0, 'west is morning');
  // Directly overhead: the sun is at the zenith, 90 degrees from the terminator.
  const h = geometricAltitude(sun.subsolarLatDeg, sun.subsolarLonDeg, date, sunEq);
  assert.ok(h > 89, `subsolar altitude should be ~90, got ${h.toFixed(2)}`);
});
