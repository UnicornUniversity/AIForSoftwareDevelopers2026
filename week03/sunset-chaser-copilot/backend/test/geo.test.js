import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EARTH_RADIUS_KM,
  dedupePath,
  haversineKm,
  longitudeDelta,
  normalize180,
  pathLengthKm,
  splitAtAntimeridian,
} from '../src/lib/geo.js';

test('normalize180 wraps into [-180, 180)', () => {
  const near = (actual, expected) =>
    assert.ok(Math.abs(actual - expected) < 1e-9, `expected ~${expected}, got ${actual}`);

  near(normalize180(0), 0);
  near(normalize180(179.9), 179.9);
  near(normalize180(180), -180);
  near(normalize180(-180), -180);
  near(normalize180(181), -179);
  near(normalize180(-181), 179);
  near(normalize180(540), -180);
  near(normalize180(-540), -180);
  near(normalize180(360 + 45), 45);
});

test('longitudeDelta takes the short way round the antimeridian', () => {
  // 179 to -179 is 2 degrees east, not 358 degrees west.
  assert.equal(longitudeDelta(-179, 179), 2);
  assert.equal(longitudeDelta(179, -179), -2);
  assert.equal(longitudeDelta(10, 20), -10);
  assert.equal(longitudeDelta(20, 10), 10);
});

test('haversineKm matches a known great-circle distance', () => {
  // London -> Paris is ~344 km.
  const d = haversineKm(51.5074, -0.1278, 48.8566, 2.3522);
  assert.ok(Math.abs(d - 344) < 6, `expected ~344 km, got ${d.toFixed(1)}`);
});

test('haversineKm crosses the antimeridian correctly', () => {
  // Two points 1 degree apart in longitude at the equator, either side of 180.
  const d = haversineKm(0, 179.5, 0, -179.5);
  const expected = ((1 / 180) * Math.PI * EARTH_RADIUS_KM);
  assert.ok(Math.abs(d - expected) < 1, `expected ~${expected.toFixed(1)} km, got ${d.toFixed(1)}`);
  // And it must NOT be the long way round the globe.
  assert.ok(d < 200, `crossed the long way: ${d.toFixed(1)} km`);
});

test('splitAtAntimeridian breaks a path at every +-180 jump', () => {
  const points = [
    [170, 10],
    [175, 11],
    [-178, 12],
    [-170, 13],
    [-160, 14],
  ];
  const paths = splitAtAntimeridian(points);
  assert.equal(paths.length, 2);
  assert.deepEqual(paths[0], [[170, 10], [175, 11]]);
  assert.deepEqual(paths[1], [[-178, 12], [-170, 13], [-160, 14]]);
});

test('splitAtAntimeridian leaves an unwrapped path alone', () => {
  const points = [[0, 0], [10, 10], [20, 20]];
  assert.equal(splitAtAntimeridian(points).length, 1);
});

test('splitAtAntimeridian handles empty and single-point paths', () => {
  assert.deepEqual(splitAtAntimeridian([]), []);
  assert.equal(splitAtAntimeridian([[5, 5]]).length, 1);
});

test('pathLengthKm sums segments but skips antimeridian jumps', () => {
  // A path that jumps the dateline must not measure the long way round.
  const crossing = [[179, 0], [-179, 0]];
  const len = pathLengthKm(crossing);
  assert.equal(len, 0, 'a bare antimeridian jump contributes no length');

  // Two degrees along the equator.
  const along = [[0, 0], [1, 0], [2, 0]];
  const expected = ((2 / 180) * Math.PI * EARTH_RADIUS_KM);
  assert.ok(Math.abs(pathLengthKm(along) - expected) < 2, `got ${pathLengthKm(along).toFixed(1)}`);
});

test('dedupePath removes consecutive duplicates only', () => {
  const points = [[0, 0], [0, 0], [1, 1], [1, 1], [1, 1], [2, 0]];
  assert.deepEqual(dedupePath(points), [[0, 0], [1, 1], [2, 0]]);
});
