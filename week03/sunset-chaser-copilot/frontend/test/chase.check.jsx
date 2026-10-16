/**
 * Page-level integration check.
 *
 * `render.check.jsx` and `map.check.jsx` each construct their component's props
 * by hand, which is what makes them fast and deterministic - and also what makes
 * them blind to the one class of bug that lives *between* a page and its
 * children: a prop passed under the wrong name. That is not hypothetical here;
 * this check exists because `ChasePage` passed `detail` to a `CameraGallery`
 * that reads `emptyDetail`, so both galleries silently dropped their
 * explanation, and every hand-built prop check still passed.
 *
 * So this one renders the real page against a stubbed `fetch` and asserts on
 * what a reader would see, including the two states a screenshot would not show:
 * a refresh failing after a good load, and a first load failing with nothing to
 * keep.
 *
 * Run with:  npm run test:chase
 */
import { StrictMode, act, createElement as h } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import { ChasePage } from '../src/pages/ChasePage.jsx';
import { CameraCard } from '../src/components/CameraCard.jsx';
import { FIXTURE_PAYLOAD } from './fixtures/payload.js';

const failures = [];
const check = (label, condition, detail = '') => {
  if (!condition) failures.push(label);
  console.log(`${condition ? '  ok  ' : ' FAIL '} ${label}${detail ? ` (${detail})` : ''}`);
};

// --- The stub ----------------------------------------------------------------
// The app's `api.js` calls the global `fetch` at call time, so replacing it here
// is enough to drive every state below without a backend.
const realFetch = globalThis.fetch;
let handler = async () => {
  throw new TypeError('fetch failed');
};
let lastSignal = null;

globalThis.fetch = (url, init = {}) => {
  lastSignal = init?.signal ?? null;
  return handler(url, init);
};

const jsonResponder = (body) => async () => ({ ok: true, status: 200, json: async () => body });
const networkFailure = async () => {
  throw new TypeError('fetch failed');
};

/** Render the real page and return its container. */
async function mount() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(h(StrictMode, null, h(MemoryRouter, null, h(ChasePage))));
  });
  return { container, root };
}

async function unmount({ container, root }) {
  await act(async () => {
    root.unmount();
  });
  container.remove();
}

const text = (container) => container.textContent ?? '';
const cards = (container) => container.querySelectorAll('article.card').length;

// --- A good load -------------------------------------------------------------
handler = jsonResponder(FIXTURE_PAYLOAD);
const good = await mount();

check('a good load draws one card per camera', cards(good.container) === 4, `saw ${cards(good.container)}, expected 4`);
check('the terminator map is mounted', good.container.querySelector('.leaflet-container') !== null);
check('the status bar is present', text(good.container).includes('Sun overhead at'));
check('the briefing is present', text(good.container).includes('runs from the Canadian Maritimes'));
check('the diagnostics block is present', text(good.container).includes('Windy calls'));
check('no error page after a good load', !text(good.container).includes('Could not load the sunset chase'));

// --- A refresh that fails, with a payload already on screen ------------------
// The degradation path: the cameras on screen are still real, so they stay, and
// the page says how old they are rather than replacing them with an error.
handler = networkFailure;
const refreshButton = [...good.container.querySelectorAll('button')].find((b) =>
  b.textContent.includes('Refresh now'),
);
check('the refresh control is a real button', Boolean(refreshButton));

if (refreshButton) {
  await act(async () => {
    refreshButton.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  });

  check('a failed refresh keeps the cameras on screen', cards(good.container) === 4, `saw ${cards(good.container)}`);
  check('a failed refresh is labelled as stale', text(good.container).includes('Showing the last good result'));
  check('a failed refresh is not an error page', !text(good.container).includes('Could not load the sunset chase'));
}

await unmount(good);

// --- A first load that fails, with nothing to keep ---------------------------
handler = networkFailure;
const failed = await mount();

check('a failed first load shows the error page', text(failed.container).includes('Could not load the sunset chase'));
check('the error page explains how to start the backend', text(failed.container).includes('npm run dev'));
check('the error page offers a retry', [...failed.container.querySelectorAll('button')].some((b) => b.textContent.includes('Try again')));
check('a failed first load draws no cards', cards(failed.container) === 0);

await unmount(failed);

// --- Empty galleries still explain themselves --------------------------------
// The wiring this check was written for. With no cameras anywhere and no API
// key, both galleries must say *why*, because that is the first-run state.
handler = jsonResponder({
  ...FIXTURE_PAYLOAD,
  primary: [],
  fallback: [],
  meta: {
    ...FIXTURE_PAYLOAD.meta,
    degraded: true,
    windy: { ...FIXTURE_PAYLOAD.meta.windy, authOk: false },
  },
});
const empty = await mount();

check('an empty primary gallery still draws the map', empty.container.querySelector('.leaflet-container') !== null);
check('an empty primary gallery names the state', text(empty.container).includes('No cameras on the line right now'));
check('an empty primary gallery explains the ocean', text(empty.container).includes('crossing open ocean'));
check('an empty primary gallery explains the missing key', text(empty.container).includes('No Windy API key is configured'));
check('an empty fallback gallery explains itself', text(empty.container).includes('no big city was in daylight'));

await unmount(empty);

// --- The diagnostics tell the truth about a reused curation ------------------
// A cached curation reports the model's own latency, which would otherwise read
// as a 29-second call inside a 30-millisecond response.
handler = jsonResponder({
  ...FIXTURE_PAYLOAD,
  meta: {
    ...FIXTURE_PAYLOAD.meta,
    llm: { ...FIXTURE_PAYLOAD.meta.llm, used: true, source: 'deepseek', model: 'deepseek-flash', latencyMs: 29179, cached: true, error: null },
  },
});
const reused = await mount();

check('a reused curation is marked as cached in the diagnostics', text(reused.container).includes('deepseek-flash in 29179 ms (cached)'));

await unmount(reused);

// --- A dead image swaps in a freshly minted token ----------------------------
// Windy's preview tokens last about ten minutes, so an image that fails is
// usually an expired URL rather than an offline camera. This is the path that
// tells the two apart, and the retry cap that stops it looping forever.
const live = FIXTURE_PAYLOAD.primary[0];
const FRESH_URL = 'https://img.test/freshly-minted.jpg';
let webcamFetches = 0;

const cardHost = document.createElement('div');
document.body.appendChild(cardHost);
const cardRoot = createRoot(cardHost);

handler = async (url) => {
  if (String(url).includes('/webcams/')) {
    webcamFetches += 1;
    return { ok: true, status: 200, json: async () => ({ ...live, imagePreviewUrl: FRESH_URL }) };
  }
  return { ok: true, status: 200, json: async () => FIXTURE_PAYLOAD };
};

await act(async () => {
  cardRoot.render(h(MemoryRouter, null, h(CameraCard, { camera: live })));
});

const firstImage = cardHost.querySelector('img');
check('the card renders the payload image', firstImage?.getAttribute('src') === live.imagePreviewUrl);

await act(async () => {
  firstImage.dispatchEvent(new window.Event('error'));
});

check(
  'a failed image is replaced with a freshly minted url',
  cardHost.querySelector('img')?.getAttribute('src') === FRESH_URL,
  cardHost.querySelector('img')?.getAttribute('src') ?? 'no image element',
);
check('the refresh asked the backend for that one camera', webcamFetches === 1, `fetched ${webcamFetches} times`);

// Now a camera that is genuinely offline: the backend answers, the URL does not
// change, so there is nothing left to try and the card must say so rather than
// hammering the endpoint.
handler = async (url) => {
  if (String(url).includes('/webcams/')) {
    webcamFetches += 1;
    return { ok: true, status: 200, json: async () => ({ ...live, imagePreviewUrl: FRESH_URL }) };
  }
  return { ok: true, status: 200, json: async () => FIXTURE_PAYLOAD };
};

for (let attempt = 0; attempt < 4; attempt += 1) {
  const image = cardHost.querySelector('img');
  if (!image) break;
  await act(async () => {
    image.dispatchEvent(new window.Event('error'));
  });
}

check('an unchanged url is treated as an offline camera', text(cardHost).includes('Camera offline'));
check('retries are capped, not endless', webcamFetches <= 2, `fetched ${webcamFetches} times`);
check('no image element is left behind once the card gives up', cardHost.querySelector('img') === null);

await act(async () => {
  cardRoot.unmount();
});
cardHost.remove();

// --- Unmount aborts the request in flight ------------------------------------
// A never-settling fetch keeps the request open, so the only way the page can
// stop caring about it is the abort. Without this, a poll that lands after the
// user has navigated away sets state on a dead tree.
handler = () => new Promise(() => {});
const pending = await mount();

check('the request carries an abort signal', pending.container ? lastSignal instanceof AbortSignal : false);
const inFlight = lastSignal;
await unmount(pending);
check('unmounting aborts the request in flight', inFlight?.aborted === true);

globalThis.fetch = realFetch;

console.log(
  `\n${failures.length === 0 ? 'ALL CHASE CHECKS PASSED' : `${failures.length} FAILED:\n - ${failures.join('\n - ')}`}`,
);
process.exit(failures.length === 0 ? 0 : 1);
