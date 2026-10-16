/**
 * Component rendering check.
 *
 * Renders the presentational components against a payload and asserts the values
 * actually reach the markup. This is what catches a field-name mismatch between
 * the API and the components - which a build cannot see, because JavaScript has
 * no type checking at that boundary, and which a fixture alone cannot catch,
 * because a fixture is written by the same person who wrote the components.
 *
 * So it prefers a LIVE payload from a running backend and falls back to the
 * fixture only to keep the check runnable without one. Which source was used is
 * printed, because a fixture run proves less.
 *
 * Run with:  npm run test:api   (start the backend first for the stronger form)
 */
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

import { Briefing } from '../src/components/Briefing.jsx';
import { CameraCard } from '../src/components/CameraCard.jsx';
import { CameraGallery } from '../src/components/CameraGallery.jsx';
import { ErrorState } from '../src/components/EmptyState.jsx';
import { StatusBar } from '../src/components/StatusBar.jsx';
import { FIXTURE_PAYLOAD } from './fixtures/payload.js';

const failures = [];
const check = (label, condition) => {
  if (!condition) failures.push(label);
  console.log(`${condition ? '  ok  ' : ' FAIL '} ${label}`);
};

const withRouter = (element) => h(MemoryRouter, null, element);
const base = process.env.CHECK_API ?? 'http://127.0.0.1:8787/api/v1';

let payload = FIXTURE_PAYLOAD;
let source = 'fixture';
try {
  const response = await fetch(`${base}/sunset-chase`, { signal: AbortSignal.timeout(60000) });
  if (response.ok) {
    payload = await response.json();
    source = 'live API';
  } else {
    console.log(`backend answered ${response.status}; using the fixture instead\n`);
  }
} catch {
  console.log('no backend reachable; using the fixture instead\n');
}

console.log(
  `source: ${source} - ${payload.primary.length} primary, ${payload.fallback.length} fallback\n`,
);

// --- StatusBar ---------------------------------------------------------------
const status = renderToStaticMarkup(
  h(StatusBar, { payload, stale: false, onRefresh: () => {}, refreshing: false }),
);
check('status shows the subsolar latitude', status.includes(Math.abs(payload.sun.subsolarLatDeg).toFixed(1)));
check('status shows the terminator span', status.includes(payload.sun.sunsetTerminatorSpanDeg.toFixed(1)));
check('status shows the equation of time', status.includes(payload.sun.equationOfTimeMin.toFixed(1)));
check('status renders the refresh control', status.includes('Refresh now'));

const staleStatus = renderToStaticMarkup(
  h(StatusBar, { payload, stale: true, onRefresh: () => {}, refreshing: false }),
);
check('a stale payload is labelled, not silently shown', staleStatus.includes('last good result'));

// --- Briefing ---------------------------------------------------------------
const briefing = renderToStaticMarkup(h(Briefing, { briefing: payload.briefing }));
check('briefing renders its text', briefing.includes(payload.briefing.text.slice(0, 40)));
check(
  'briefing labels its source',
  briefing.includes(payload.briefing.source === 'deepseek' ? 'DeepSeek' : 'Computed locally'),
);

// A briefing claiming to be modelled must actually be labelled as modelled.
const modelled = renderToStaticMarkup(
  h(Briefing, { briefing: { text: 'Modelled text.', source: 'deepseek', model: 'deepseek-flash' } }),
);
check('a modelled briefing is attributed', modelled.includes('DeepSeek') && modelled.includes('deepseek-flash'));

// --- CameraCard -------------------------------------------------------------
const card = payload.primary[0];
if (!card) {
  console.log('\nNo primary cameras in this payload; skipping card checks.');
} else {
  const markup = renderToStaticMarkup(withRouter(h(CameraCard, { camera: card })));
  check('card shows the city', !card.city || markup.includes(card.city));
  check('card uses the image url', markup.includes(new URL(card.imagePreviewUrl).origin));
  check('card links back to Windy', markup.includes(card.windyPageUrl));
  check('card links to the detail route', markup.includes(`/camera/${encodeURIComponent(card.webcamId)}`));
  check('card renders the reason text', markup.includes(card.reason.slice(0, 40)));
  check('card reports the distance', !card.distanceToTerminatorKm || markup.includes('km'));
  check('card attributes the narration', markup.includes(card.reasonSource === 'deepseek' ? 'DeepSeek' : `Rank ${card.rank}`));
  check('the image is lazy-loaded', markup.includes('loading="lazy"'));
}

// --- Cases the live payload may not happen to contain ------------------------
// Deliberately synthetic. Waiting for a live payload to happen to include a
// camera that set four minutes ago, or one with an unmeasured twilight, would
// mean these states go unchecked on the runs where they are absent - which is
// exactly when a regression would slip through.

/** A complete camera, so each check below overrides only what it is about. */
const makeCamera = (overrides = {}) => ({
  webcamId: 'test-1',
  title: 'Test Camera',
  city: 'Testville',
  country: 'Testland',
  latitude: 51.5,
  longitude: -0.12,
  sunAltitudeDeg: 1.2,
  hourAngleDeg: 60,
  isDescending: true,
  phase: 'golden_hour',
  minutesToSunset: 30,
  sunsetDurationMin: 30,
  distanceToTerminatorKm: 120,
  score: 0.5,
  rank: 1,
  source: 'terminator',
  imagePreviewUrl: 'https://img.test/a.jpg',
  imageExpiresAt: '2026-10-16T17:10:00.000Z',
  windyPageUrl: 'https://www.windy.com/webcams/test-1',
  lastUpdatedOn: '2026-10-16T16:55:00.000Z',
  reason: 'A reason.',
  reasonSource: 'deterministic',
  ...overrides,
});

const renderCard = (overrides) =>
  renderToStaticMarkup(withRouter(h(CameraCard, { camera: makeCamera(overrides) })));

// The sign is the whole point of `minutesToSunset`, so both sides are pinned to
// their exact wording rather than to a loose pattern.
check('a camera before its sunset counts down', renderCard({ minutesToSunset: 2 }).includes('sets in 2 min'));
check('a camera past its sunset counts up', renderCard({ minutesToSunset: -4 }).includes('set 4 min ago'));
check(
  'a long countdown is hours, not minutes',
  renderCard({ minutesToSunset: 95 }).includes('sets in 1 h 35 min'),
);
check(
  'an unmeasured twilight reads as unmeasured, not as zero',
  renderCard({ sunsetDurationMin: null }).includes('not measured'),
);
check(
  'a missing countdown renders no chip at all',
  !renderCard({ minutesToSunset: null }).includes('sets in'),
);
check(
  'a fallback camera is labelled as one',
  renderCard({ source: 'fallback' }).includes('Big-city fallback'),
);
check(
  'a modelled reason is attributed',
  renderCard({ reasonSource: 'deepseek' }).includes('narrated by DeepSeek'),
);

// --- Hostile input ----------------------------------------------------------
// Camera titles are untrusted text from Windy, and the reason string can
// originate from DeepSeek, which has read those titles.
const hostile = {
  ...(card ?? {
    webcamId: 'x',
    latitude: 0,
    longitude: 0,
    imagePreviewUrl: 'https://img.test/a.jpg',
  }),
  title: '<img src=x onerror="globalThis.pwned=true">',
  city: '<script>globalThis.pwned=true</script>',
  reason: '<b>not bold</b>',
  windyPageUrl: 'https://www.windy.com/webcams/1',
};
const hostileMarkup = renderToStaticMarkup(withRouter(h(CameraCard, { camera: hostile })));
check('a hostile title is escaped', hostileMarkup.includes('&lt;script&gt;') && !hostileMarkup.includes('<script>'));
check('a hostile reason is escaped', hostileMarkup.includes('&lt;b&gt;') && !hostileMarkup.includes('<b>not bold</b>'));
// The escaped text still contains the literal word "onerror", which is harmless.
// What must not appear is a real element, so the assertion is on the unescaped
// form: `<img src=x` can only exist as a tag, never as text.
check('a hostile title produces no live element', !hostileMarkup.includes('<img src=x') && hostileMarkup.includes('&lt;img src=x'));

// --- Gallery ----------------------------------------------------------------
const gallery = renderToStaticMarkup(
  withRouter(
    h(CameraGallery, { title: 'On the terminator', description: 'Ranked.', cameras: payload.primary.slice(0, 3) }),
  ),
);
check(
  'gallery renders one card per camera',
  (gallery.match(/class="card"/g) ?? []).length === Math.min(3, payload.primary.length),
);

const emptyGallery = renderToStaticMarkup(
  h(CameraGallery, {
    title: 'On the terminator',
    cameras: [],
    emptyTitle: 'No cameras on the line right now',
    emptyDetail: 'Most of the terminator is over ocean.',
    hints: ['No Windy API key is configured.'],
  }),
);
check('an empty gallery explains itself', emptyGallery.includes('No cameras on the line right now'));
check('an empty gallery forwards its hints', emptyGallery.includes('No Windy API key is configured.'));

// --- ErrorState -------------------------------------------------------------
const networkError = renderToStaticMarkup(
  h(ErrorState, { error: { code: 'network', message: 'Could not reach the API.' } }),
);
check('the network error state names the backend command', networkError.includes('npm run dev'));
check('the network error state names the port', networkError.includes('8787'));

const timeoutError = renderToStaticMarkup(
  h(ErrorState, { error: { code: 'timeout', message: 'Too slow.' } }),
);
check('the timeout error state explains the cold start', timeoutError.includes('a minute'));

console.log(
  `\n${failures.length === 0 ? 'ALL RENDER CHECKS PASSED' : `${failures.length} FAILED:\n - ${failures.join('\n - ')}`}`,
);
process.exit(failures.length === 0 ? 0 : 1);
