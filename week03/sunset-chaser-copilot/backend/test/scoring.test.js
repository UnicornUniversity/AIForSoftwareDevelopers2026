import test from 'node:test';
import assert from 'node:assert/strict';

import { normalize180 } from '../src/lib/geo.js';
import { subsolarPoint, sunEquatorial } from '../src/services/solar.js';
import {
  ANY_ALTITUDE_DEG,
  MAX_ALTITUDE_DEG,
  MAX_MINUTES_TO_SUNSET,
  SCORE_WEIGHTS,
  deterministicReason,
  durationScore,
  latitudeScore,
  passesFilters,
  popularityScore,
  rankCandidates,
  selectPrimary,
} from '../src/services/scoring.js';

const AT = new Date('2026-10-16T17:00:00Z');
const sunEq = sunEquatorial(AT);
const subsolar = subsolarPoint(AT, sunEq);

function candidate(overrides = {}) {
  return {
    webcamId: '1',
    status: 'active',
    title: 'A camera',
    city: 'Lisbon',
    country: 'Portugal',
    countryCode: 'PT',
    latitude: 38.7071,
    longitude: -9.1365,
    imagePreviewUrl: 'https://example.test/preview',
    viewCount: 100,
    ...overrides,
  };
}

test('score weights sum to 1 so the score stays in 0..1', () => {
  const total = Object.values(SCORE_WEIGHTS).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `weights sum to ${total}`);
});

test('durationScore treats an unmeasurable twilight as neutral, not bad', () => {
  // A null duration means the sun never reaches -6 degrees. At high latitude
  // near a solstice that is the long bright evening this app exists to find -
  // scoring it 0 would punish exactly the right cameras.
  assert.equal(durationScore(null), 0.5);
  assert.equal(durationScore(undefined), 0.5);
  assert.equal(durationScore(20), 0);
  assert.equal(durationScore(120), 1);
  assert.equal(durationScore(400), 1, 'clamped');
  assert.ok(durationScore(118) > durationScore(40), 'a longer twilight scores higher');
});

test('latitudeScore rewards the mid-latitude band', () => {
  assert.equal(latitudeScore(45), 1);
  assert.equal(latitudeScore(-45), 1);
  assert.ok(latitudeScore(70) < latitudeScore(45), 'the far north is less likely to have cameras');
  assert.ok(latitudeScore(0) < latitudeScore(40), 'the equator has short sunsets');
});

test('popularityScore is log-scaled and bounded', () => {
  assert.equal(popularityScore(0), 0);
  assert.equal(popularityScore(-5), 0);
  assert.ok(popularityScore(1000) > popularityScore(10));
  assert.ok(popularityScore(10_000_000) <= 1);
});

test('passesFilters rejects cameras that cannot be shown or placed', () => {
  const evaluated = (overrides) => ({ ...candidate(), sunAltitudeDeg: 0, ...overrides });

  assert.equal(passesFilters(evaluated({})), true);
  assert.equal(passesFilters(evaluated({ status: 'inactive' })), false);
  assert.equal(passesFilters(evaluated({ imagePreviewUrl: null })), false);
  assert.equal(passesFilters(evaluated({ sunAltitudeDeg: 20 })), false, 'too far from the terminator');
  assert.equal(passesFilters(evaluated({ sunAltitudeDeg: -14.9 })), true, 'just inside the cutoff');
  assert.equal(passesFilters(evaluated({ sunAltitudeDeg: -15.1 })), false);
  assert.ok(Math.abs(MAX_ALTITUDE_DEG - 15) < 1e-9);
});

test('passesFilters honours a caller-supplied altitude window', () => {
  // The fallback exists to return big cities standing in daylight, where the sun
  // can be 40 degrees up. Applying the terminator's 15-degree window to them
  // rejected every camera the fallback had just fetched, so `fallbackCount` was
  // structurally always zero however many cameras Windy returned.
  const daylight = { ...candidate(), sunAltitudeDeg: 40.2 };

  assert.equal(passesFilters(daylight), false, 'the terminator window still rejects it by default');
  assert.equal(passesFilters(daylight, { maxAltitudeDeg: ANY_ALTITUDE_DEG }), true);
  assert.equal(ANY_ALTITUDE_DEG, 90, 'wide enough for any sun above the horizon');
});

test('a daylight fallback camera survives a wide window and scores above zero', () => {
  // Straight under the sun: the brightest a camera can be, and exactly what the
  // fallback's "big cities in the day-time zone" is asking for.
  const sunny = candidate({
    webcamId: 'day',
    latitude: subsolar.subsolarLatDeg,
    longitude: subsolar.subsolarLonDeg,
  });

  const narrow = rankCandidates([sunny], { date: AT, sunEq, subsolar, resolveEvents: () => null });
  assert.equal(narrow.length, 0, 'the terminator window rejects it, which is correct for the primary list');

  const ranked = rankCandidates([sunny], {
    date: AT,
    sunEq,
    subsolar,
    maxAltitudeDeg: ANY_ALTITUDE_DEG,
    resolveEvents: () => null,
  });

  assert.equal(ranked.length, 1, 'the wide window must admit a camera in full daylight');
  assert.equal(ranked[0].phase, 'day');
  assert.ok(ranked[0].score > 0, 'a fallback camera must not score exactly zero');
  // Proximity normalises against the caller's own window, so the fallback list
  // is still ordered by closeness within itself instead of every entry
  // collapsing to zero.
  assert.ok(ranked[0].scoreParts.proximity >= 0 && ranked[0].scoreParts.proximity <= 1);
});

/**
 * A camera sitting exactly on the terminator.
 *
 * The terminator crosses the equator at precisely 90 degrees of hour angle from
 * the subsolar meridian, so the equator is where a 90-degree offset gives an
 * altitude of exactly 0. (At the subsolar *latitude* it does not: solving
 * cos H = -tan(phi)tan(dec) with phi = dec gives H = 91.46 at this declination,
 * which put the earlier version of this fixture 1.4 degrees off the arc.)
 */
const onTerminator = (overrides = {}) =>
  candidate({
    latitude: 0,
    longitude: normalize180(subsolar.subsolarLonDeg + 90),
    ...overrides,
  });

/** Directly under the sun: the furthest a camera can be from the terminator. */
const underTheSun = (overrides = {}) =>
  candidate({
    latitude: subsolar.subsolarLatDeg,
    longitude: subsolar.subsolarLonDeg,
    ...overrides,
  });

test('the fixtures really do sit where the test claims', () => {
  // Guards the fixtures themselves: if these drift, every ranking test below
  // starts asserting against filtered-out cameras.
  const near = rankCandidates([onTerminator()], { date: AT, sunEq, subsolar, resolveEvents: () => null });
  const far = rankCandidates([underTheSun()], { date: AT, sunEq, subsolar, resolveEvents: () => null });

  assert.equal(near.length, 1, 'the on-terminator fixture must survive filtering');
  assert.ok(Math.abs(near[0].sunAltitudeDeg) < 0.01, `altitude ${near[0].sunAltitudeDeg} should be ~0`);
  assert.equal(far.length, 0, 'the under-the-sun fixture is far too bright to be a terminator camera');
});

test('rankCandidates buckets by phase and orders by score', () => {
  const ranked = rankCandidates([underTheSun({ webcamId: 'far' }), onTerminator({ webcamId: 'near' })], {
    date: AT,
    sunEq,
    subsolar,
    resolveEvents: () => null,
  });

  assert.equal(ranked.length, 1, 'only the on-terminator camera survives the altitude filter');
  assert.equal(ranked[0].webcamId, 'near');
  assert.equal(ranked[0].rank, 1);
  assert.ok(ranked[0].score > 0 && ranked[0].score <= 1);
  assert.ok(ranked[0].reason.length > 0);
  assert.equal(ranked[0].reasonSource, 'deterministic');
});

test('a camera closer to the terminator outscores one further from it', () => {
  // Both must survive the 15-degree filter, so these are about 3 and 12 degrees
  // off, measured along the equator.
  const close = candidate({
    webcamId: 'close',
    latitude: 0,
    longitude: normalize180(subsolar.subsolarLonDeg + 87),
  });
  const further = candidate({
    webcamId: 'further',
    latitude: 0,
    longitude: normalize180(subsolar.subsolarLonDeg + 78),
  });

  const ranked = rankCandidates([further, close], {
    date: AT,
    sunEq,
    subsolar,
    resolveEvents: () => null,
  });

  assert.equal(ranked.length, 2, 'both should survive the filter');
  assert.equal(ranked[0].webcamId, 'close', 'proximity is the heaviest weight');
  assert.ok(ranked[0].scoreParts.proximity > ranked[1].scoreParts.proximity);
});

test('rankCandidates is deterministic and total', () => {
  const build = () =>
    rankCandidates(
      [
        candidate({ webcamId: 'b', latitude: 30, longitude: -30 }),
        candidate({ webcamId: 'a', latitude: 31, longitude: -30 }),
        candidate({ webcamId: 'c', latitude: 29, longitude: -30 }),
      ],
      { date: AT, sunEq, subsolar, resolveEvents: () => null },
    );

  assert.deepEqual(build(), build(), 'two identical runs must produce identical output');
});

test('rankCandidates clamps and rounds minutesToSunset', () => {
  const ranked = rankCandidates([onTerminator()], {
    date: AT,
    sunEq,
    subsolar,
    // Deliberately absurd: the naive descent-rate ratio explodes near the
    // subsolar point, and this must never reach the client.
    resolveEvents: () => ({ kind: 'normal', minutesToSunset: -18342.7, sunsetDurationMin: 31.234 }),
  });

  assert.equal(ranked[0].minutesToSunset, -MAX_MINUTES_TO_SUNSET);
  assert.equal(ranked[0].sunsetDurationMin, 31.2);
});

test('a measured interval survives the clamp, so a long-past sunset is reported honestly', () => {
  // The clamp exists to catch a broken value, not to round a real one. At +-180
  // a camera eight hours past sunset was reported as "set 180 minutes ago" -
  // the same confident falsehood the unmeasured-duration bug produced. The
  // measured interval from `sunsetEvents` is bounded at about 12 hours, so it
  // must pass through untouched.
  const ranked = rankCandidates([onTerminator()], {
    date: AT,
    sunEq,
    subsolar,
    resolveEvents: () => ({ kind: 'normal', minutesToSunset: -530.9, sunsetDurationMin: 25.6 }),
  });

  assert.equal(ranked[0].minutesToSunset, -531, 'a real 8.8-hour-past sunset must not be flattened to -180');
  assert.ok(MAX_MINUTES_TO_SUNSET >= 720, 'the clamp must be slack enough never to bite a measured value');
});

test('a polar-day camera survives filtering and gets an honest reason', () => {
  // Set the polar camera on the terminator for the current date, at latitude 78.
  // At this declination the terminator reaches 80.9 degrees, so 78 is in band.
  const polar = candidate({
    latitude: 78,
    longitude: normalize180(subsolar.subsolarLonDeg + 30),
  });

  const ranked = rankCandidates([polar], {
    date: AT,
    sunEq,
    subsolar,
    resolveEvents: () => ({
      kind: 'midnightSun',
      minutesToSunset: null,
      sunsetDurationMin: null,
      nextSunsetIso: null,
    }),
  });

  assert.equal(ranked.length, 1, 'the polar fixture must survive the altitude filter');

  assert.equal(ranked[0].phase, 'polarDay');
  assert.match(deterministicReason(ranked[0]), /does not set/);
  assert.match(ranked[0].reason, /does not set/);
});

test('deterministicReason describes civil twilight as just after sunset', () => {
  const reason = deterministicReason({
    phase: 'civil_twilight',
    minutesToSunset: -22,
    sunsetDurationMin: 28,
    sunsetMeasured: true,
    distanceToTerminatorKm: 12,
  });
  assert.match(reason, /set 22 minutes ago/);
  assert.match(reason, /28 minutes/);
});

test('deterministicReason says twilight never ends only when that was measured', () => {
  const reason = deterministicReason({
    phase: 'golden_hour',
    minutesToSunset: 40,
    sunsetDurationMin: null,
    sunsetMeasured: true,
    distanceToTerminatorKm: 300,
  });
  assert.match(reason, /never fully sets/);
});

test('an unmeasured duration is reported as unmeasured, not as a false claim', () => {
  // The bug this guards: a null duration means either "twilight genuinely never
  // ends" or "Tier 2 never ran for this camera". Reading the first when the
  // second is true put "the sun never fully sets" on cameras in England in
  // October. The two must not share wording.
  const unmeasured = deterministicReason({
    phase: 'civil_twilight',
    minutesToSunset: -10,
    sunsetDurationMin: null,
    sunsetMeasured: false,
    distanceToTerminatorKm: 40,
  });

  assert.doesNotMatch(unmeasured, /never fully sets/);
  assert.match(unmeasured, /not been measured/);

  // And it defaults to "unmeasured" when the flag is absent entirely, so a
  // caller that forgets it fails safe.
  const missingFlag = deterministicReason({
    phase: 'civil_twilight',
    minutesToSunset: -10,
    sunsetDurationMin: null,
    distanceToTerminatorKm: 40,
  });
  assert.doesNotMatch(missingFlag, /never fully sets/);
});

test('selectPrimary prefers variety, then tops up when deduping leaves it short', () => {
  const sameCity = Array.from({ length: 5 }, (_, i) =>
    candidate({ webcamId: `lisbon-${i}`, city: 'Lisbon', score: 0.9 - i * 0.01 }),
  );
  const others = Array.from({ length: 4 }, (_, i) =>
    candidate({ webcamId: `other-${i}`, city: `City${i}`, score: 0.5 - i * 0.01 }),
  );

  const ranked = [...sameCity, ...others].map((c, i) => ({ ...c, rank: i + 1 }));

  const three = selectPrimary(ranked, 3);
  assert.equal(three.length, 3);
  assert.equal(new Set(three.map((c) => c.city)).size, 3, 'no city appears twice');

  // Asking for more than the number of distinct cities must still fill up
  // rather than silently returning fewer.
  const eight = selectPrimary(ranked, 8);
  assert.equal(eight.length, 8);
});
