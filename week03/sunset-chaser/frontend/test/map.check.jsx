/**
 * Map behaviour check.
 *
 * Mounts the real `TerminatorMap` inside `StrictMode` and inspects the DOM
 * Leaflet produced. This covers the one set of claims a production build and a
 * server render cannot: whether the imperatively-mounted Leaflet map survives
 * React StrictMode's deliberate double-invocation of effects, whether it cleans
 * up so the container can be reused, and whether each family of layers produces
 * the shapes it should.
 *
 * Runs against `test/fixtures/payload.js`, so it needs no backend and no API key.
 *
 * Run with:  npm run test:map
 */
import { StrictMode, act, createElement as h } from 'react';
import { createRoot } from 'react-dom/client';

import { TerminatorMap } from '../src/components/TerminatorMap.jsx';
import { worldCopies, worldCopyLatLngs } from '../src/lib/geo.js';
import { FIXTURE_PAYLOAD } from './fixtures/payload.js';

const failures = [];
const check = (label, condition, detail = '') => {
  if (!condition) failures.push(label);
  console.log(`${condition ? '  ok  ' : ' FAIL '} ${label}${detail ? ` (${detail})` : ''}`);
};

const payload = FIXTURE_PAYLOAD;
const cameras = [...payload.primary, ...payload.fallback];
const samplePoints = payload.terminator.samplePoints;
const sunsetArcs = payload.terminator.sunset.arcs.length;
const sunriseArcs = payload.terminator.sunrise.arcs.length;

const container = document.createElement('div');
document.body.appendChild(container);
let root = createRoot(container);

/** Mount one configuration, count SVG shapes, unmount, return the count. */
async function mountAndCount(props) {
  await act(async () => {
    root.render(h(StrictMode, null, h(TerminatorMap, props)));
  });
  const count = container.querySelectorAll('path').length;
  await act(async () => {
    root.unmount();
  });
  // React refuses to reuse an unmounted root, so each mount gets a fresh one.
  root = createRoot(container);
  return count;
}

// --- StrictMode --------------------------------------------------------------
// The empty map is the control. An empty Leaflet map draws a few paths of its
// own, so every expectation below is a difference against this baseline rather
// than an absolute count.
let baseline = null;
let threw = null;
try {
  baseline = await mountAndCount({ payload: null, cameras: [], samplePoints: [] });
} catch (err) {
  threw = err;
}
check('mounting under StrictMode throws nothing', threw === null, threw?.message ?? '');

// --- One shape per layer -----------------------------------------------------
const arcsOnly = await mountAndCount({ payload, cameras: [], samplePoints: [] });
check(
  'each terminator arc is drawn in three world copies',
  arcsOnly - baseline === (sunsetArcs + sunriseArcs) * 3,
  `saw ${arcsOnly - baseline}, expected ${(sunsetArcs + sunriseArcs) * 3} ((sunset ${sunsetArcs} + sunrise ${sunriseArcs}) x 3)`,
);

const pointsOnly = await mountAndCount({ payload: null, cameras: [], samplePoints });
check(
  'one shape per sample point',
  pointsOnly - baseline === samplePoints.length,
  `saw ${pointsOnly - baseline}, expected ${samplePoints.length}`,
);

const camerasOnly = await mountAndCount({ payload: null, cameras, samplePoints: [] });
check(
  'one shape per camera',
  camerasOnly - baseline === cameras.length,
  `saw ${camerasOnly - baseline}, expected ${cameras.length} (${payload.primary.length} primary + ${payload.fallback.length} fallback)`,
);

// --- The mounted map --------------------------------------------------------
const mounted = document.createElement('div');
document.body.appendChild(mounted);
const probe = createRoot(mounted);
await act(async () => {
  probe.render(h(StrictMode, null, h(TerminatorMap, { payload, cameras, samplePoints })));
});

check('Leaflet created a map container', mounted.querySelector('.leaflet-container') !== null);
check('the tile layer is attached', mounted.querySelector('.leaflet-tile-pane') !== null);
check('the attribution control is present', mounted.querySelector('.leaflet-control-attribution') !== null);
check('no Leaflet popup is open by default', mounted.querySelector('.leaflet-popup') === null);

await act(async () => {
  probe.unmount();
});
mounted.remove();

check('unmount leaves the container empty', mounted.querySelector('.leaflet-container') === null);
check('unmount leaves no stray children', mounted.childElementCount === 0);

// --- Remount on the same node ------------------------------------------------
// The exact sequence StrictMode performs in development. Had the cleanup not
// fully removed the map, this mount would throw "Map container is already
// initialized" - the specific failure this check exists to catch.
const reused = document.createElement('div');
document.body.appendChild(reused);
const secondRoot = createRoot(reused);
let secondThrew = null;
try {
  await act(async () => {
    secondRoot.render(h(StrictMode, null, h(TerminatorMap, { payload, cameras, samplePoints })));
  });
} catch (err) {
  secondThrew = err;
}
check('mounting a second time on a reused node works', secondThrew === null, secondThrew?.message ?? '');

await act(async () => {
  secondRoot.unmount();
});
check('the second unmount also cleans up', reused.querySelector('.leaflet-container') === null);
reused.remove();
container.remove();

// --- Antimeridian arithmetic -------------------------------------------------
// Checked directly rather than through the rendered paths. Leaflet emits `d` in
// projected pixel space and clips to the viewport, so at any fixed view the two
// off-screen world copies collapse to identical or empty paths - asserting on
// that would assert on the viewport, not on the behaviour.
const copies = worldCopies(170);
check(
  'worldCopies shifts a longitude by a full turn either way',
  copies.length === 3 && copies[0] === -190 && copies[1] === 170 && copies[2] === 530,
  JSON.stringify(copies),
);
check(
  'worldCopyLatLngs emits [lat, lon] pairs per copy',
  JSON.stringify(worldCopyLatLngs(51.5, 170)) === JSON.stringify([[51.5, -190], [51.5, 170], [51.5, 530]]),
  JSON.stringify(worldCopyLatLngs(51.5, 170)),
);
check('the date line is shifted, not duplicated', new Set(worldCopies(180)).size === 3, JSON.stringify(worldCopies(180)));

console.log(
  `\n${failures.length === 0 ? 'ALL MAP CHECKS PASSED' : `${failures.length} FAILED:\n - ${failures.join('\n - ')}`}`,
);
process.exit(failures.length === 0 ? 0 : 1);
