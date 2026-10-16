import test from 'node:test';
import assert from 'node:assert/strict';

import { haversineKm } from '../src/lib/geo.js';
import { subsolarPoint } from '../src/services/solar.js';
import { MAX_ABS_LAT, densityWeight, sampleTerminator, terminatorBand } from '../src/services/sampler.js';

const at = (iso) => new Date(iso);

const MID_OCTOBER = at('2026-10-16T17:00:00Z');
const JUNE_SOLSTICE = at('2026-06-21T12:00:00Z');
const DECEMBER_SOLSTICE = at('2026-12-21T12:00:00Z');

test('densityWeight prefers the mid-latitude band and hard-cuts the poles', () => {
  assert.equal(densityWeight(45), 1.0);
  assert.equal(densityWeight(-45), 1.0);
  assert.equal(densityWeight(0), 0.6);
  assert.equal(densityWeight(70), 0.45);
  assert.equal(densityWeight(72), 0.45);
  assert.equal(densityWeight(72.001), 0, 'poleward of the cut is worth no call at all');
  assert.equal(densityWeight(-89), 0);
});

test('samples are exactly as many as asked for', () => {
  const sun = subsolarPoint(MID_OCTOBER);
  for (const k of [8, 12, 20, 30]) {
    assert.equal(sampleTerminator(sun, k).length, k);
  }
});

test('no sample is ever poleward of the cut, at any declination', () => {
  for (const date of [MID_OCTOBER, JUNE_SOLSTICE, DECEMBER_SOLSTICE]) {
    const samples = sampleTerminator(subsolarPoint(date), 20);
    assert.ok(samples.length > 0);
    for (const point of samples) {
      assert.ok(
        Math.abs(point.lat) <= MAX_ABS_LAT,
        `${date.toISOString()}: sample at latitude ${point.lat}`,
      );
    }
  }
});

test('samples land on the terminator, not merely near it', () => {
  // Every sample must satisfy the terminator equation cos H = -tan(phi) tan(dec).
  const sun = subsolarPoint(MID_OCTOBER);
  const samples = sampleTerminator(sun, 20);
  for (const { lat, lon } of samples) {
    const h = (lon - sun.subsolarLonDeg) * (Math.PI / 180);
    const residual =
      Math.cos(h) +
      Math.tan(lat * (Math.PI / 180)) * Math.tan(sun.declinationDeg * (Math.PI / 180));
    assert.ok(Math.abs(residual) < 1e-3, `off the arc by residual ${residual}`);
  }
});

test('mid-October places samples across the useful band with a ~650 km median gap', () => {
  const sun = subsolarPoint(MID_OCTOBER);
  const samples = sampleTerminator(sun, 20);

  const lats = samples.map((p) => p.lat).sort((a, b) => a - b);
  // The plan predicted this band before the code existed. The extremes are the
  // weighted quantile's half-step inset from the +-72 cut.
  assert.ok(Math.abs(lats[0] + 66) < 1.5, `southernmost ${lats[0].toFixed(1)}, expected ~-66`);
  assert.ok(Math.abs(lats[lats.length - 1] - 66) < 1.5, `northernmost ${lats.at(-1).toFixed(1)}`);

  const gaps = [];
  for (let i = 1; i < samples.length; i += 1) {
    gaps.push(
      haversineKm(samples[i - 1].lat, samples[i - 1].lon, samples[i].lat, samples[i].lon),
    );
  }
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  assert.ok(median > 500 && median < 800, `median gap ${median.toFixed(0)} km, expected ~650`);
});

test('samples are ordered along the arc and none is duplicated', () => {
  const sun = subsolarPoint(MID_OCTOBER);
  const samples = sampleTerminator(sun, 20);
  const seen = new Set();
  for (const { lat, lon } of samples) {
    const key = `${lat},${lon}`;
    assert.ok(!seen.has(key), `duplicate sample at ${key}`);
    seen.add(key);
  }
});

test('a terminator that never leaves the polar cap yields no samples', () => {
  // Near a solstice the terminator still crosses the equator, so the cut never
  // removes everything - but a band pinned near the pole must return nothing
  // rather than an empty-but-present array of NaNs.
  const fake = { declinationDeg: 0.5, subsolarLonDeg: 0 };
  assert.equal(sampleTerminator(fake, 10, { maxAbsLat: 0.1 }).length, 0);
});

test('the equinox terminator still samples cleanly', () => {
  // At the equinox the arc degenerates to a pair of meridians and the latitude
  // parametrisation divides by sin(dec) ~ 0. It must not produce NaN.
  const sun = subsolarPoint(at('2026-03-20T12:00:00Z'));
  assert.ok(Math.abs(sun.declinationDeg) < 0.1, 'this date should be near the equinox');
  const samples = sampleTerminator(sun, 12);
  assert.equal(samples.length, 12);
  for (const { lat, lon } of samples) {
    assert.ok(Number.isFinite(lat) && Number.isFinite(lon), `got ${lat},${lon}`);
    assert.ok(Math.abs(lat) <= MAX_ABS_LAT);
  }
});

test('terminatorBand intersects the reachable span with the camera cut', () => {
  const sun = subsolarPoint(MID_OCTOBER);
  const band = terminatorBand(sun);
  assert.equal(band.hi, MAX_ABS_LAT, 'mid-October reaches past the cut');
  assert.equal(band.lo, -MAX_ABS_LAT);
  assert.ok(Math.abs(band.span - 80.93) < 0.2);

  // Near a solstice the terminator stops short of the cut, so the span binds.
  const june = terminatorBand(subsolarPoint(JUNE_SOLSTICE));
  assert.ok(Math.abs(june.hi - 66.56) < 0.2, `june hi ${june.hi}`);
});
