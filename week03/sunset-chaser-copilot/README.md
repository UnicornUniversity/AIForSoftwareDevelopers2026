# Sunset Chaser

An app that shows live webcam pictures from around the world, choosing the cameras that are
standing near the **solar terminator** — the day/night boundary. It answers the brief in
[`spec.md`](spec.md): find where the terminator is, find webcams near it, and always fall back to
big cities that are currently in daylight.

**The idea.** At any instant the most dramatic light on Earth lies along a great circle about
20,000 km long, and most of that circle is over open ocean. The app computes the terminator from an
ephemeris, samples it where webcams actually exist, ranks what it finds by how close the camera is
to the line and how long the twilight lasts at that latitude, asks DeepSeek to curate and narrate
the result, and draws the whole thing on a world map.

## Deliverables

| file | what it is |
|---|---|
| [`backend/`](backend/) | Node.js API — astronomy, the Windy webcam sweep, scoring, the DeepSeek curation |
| [`frontend/`](frontend/) | React + Vite client — terminator map, ranked camera gallery, camera detail page |
| [`backend/test/`](backend/test/) | 102 tests, `node --test`, no network and no API keys needed |
| [`frontend/test/`](frontend/test/) | 3 committed checks, 75 assertions, against a hand-written fixture |

## Source

| file | role |
|---|---|
| `backend/src/services/solar.js` | the only astronomy in the project — subsolar point, terminator arcs, per-camera sun position |
| `backend/src/services/sampler.js` | places the Windy probes along the arc by weighted equal-arc sampling |
| `backend/src/services/windy.js` | Windy Webcams v3 client: `nearby`, retries, adaptive paging, normalisation, dedupe |
| `backend/src/services/scoring.js` | phase buckets, hard filters, the weighted score, the deterministic reason text |
| `backend/src/services/fallback.js` | the spec's step 3 — daylight big cities, spread across skylines |
| `backend/src/services/llm.js` | DeepSeek curation, and everything that makes untrusted model output safe to show |
| `backend/src/services/chase.js` | the orchestrator, and the cache keys that decide what each request costs |
| `backend/src/routes/` | `express.Router()` per resource, mounted at `/api/v1` |
| `frontend/src/components/TerminatorMap.jsx` | the Leaflet map: arcs drawn in three world copies, markers coloured by phase |
| `frontend/src/hooks/useChase.js` | fetch, 300 s poll, pause when the tab is hidden, `stale` vs `error` |
| `frontend/test/run-check.mjs` | bundles a check with the Vite that is already installed, then runs it in Node |

## Reproducing

```bash
cd backend  && npm ci && cp .env.example .env   # then fill in the two keys
cd ../frontend && npm ci

cd backend  && npm run dev        # http://localhost:8787
cd frontend && npm run dev        # http://localhost:5173
```

Both keys are optional. Without `WINDY_API_KEY` there are no cameras but the terminator map still
renders; without `DEEPSEEK_API_KEY` the ranking and the wording are produced deterministically from
the same numbers. The server never returns a 5xx because an upstream is missing.

```bash
cd backend  && npm test    # 102 tests, ~300 ms, no network
cd frontend && npm test    # 3 checks: the map, the page, the components
```

The frontend checks are `.jsx` and import application source, so they need a JSX transform; rather
than add a second test runner, `test/run-check.mjs` builds each one with the Vite already in
`devDependencies` and runs the bundle in Node. `npm run test:map` and `npm run test:chase` need no
backend at all. `npm run test:api` prefers a **live** payload from a running backend and falls back
to `test/fixtures/payload.js`, printing which one it used — a fixture run proves less, because the
fixture is written by the same hand as the components.

## Notes

### The astronomy is a library, not arithmetic

`solar.js` wraps [`astronomy-engine`](https://github.com/cosinekitty/astronomy) (MIT, zero
dependencies, VSOP87 + NOVAS C 3.1, ±1 arcminute). A hand-rolled version was prototyped first and
contained a real 4× unit error in the equation of time — dividing degrees where minutes were meant —
which put the subsolar longitude 2.7° out, about eleven minutes of time. The library computes
Greenwich apparent sidereal time directly, so the subsolar point is `λ = α − GAST` and the entire
equation-of-time code path, which is where that bug lived, does not exist. The six
declination/equation-of-time anchors in `test/solar.test.js` pin the integration, including both
annual equation-of-time extremes.

The terminator itself is then exact closed-form geometry rather than a numerical search: it *is* the
great circle 90° from the subsolar point, so each arc is a half circle of 20,015 km
(`test/solar.test.js` asserts the length to ±50 km, which catches any longitude-unit slip at once).
Because it is a great circle, a camera's perpendicular distance to it is exactly `R · |altitude|`.

### Geometric sun on the map, refracted sunset on the card

One inconsistency is deliberate. The arc is drawn at geometric altitude 0 — the standard definition
of the terminator — while the sunset time shown per camera is the **apparent** one, corrected for
refraction and the solar disc radius, which lifts the sun about 0.83° at the horizon, roughly five
minutes. So a camera exactly on the drawn line has, strictly, already set. This is what terminator
visualisations normally do, and it keeps the map and the ranking on one model.

That 0.83° also caused a real bug worth recording. `SearchRiseSet` returns the *apparent* sunset, so
geometric altitude goes negative about five minutes *before* the event. The original code tested
`altitude > 0` to decide whether a camera had already set, which put a camera three minutes before
its sunset down the "already set" branch and reported `−1437` minutes. The fix asks which sunset is
nearer instead of testing a sign.

### The Windy call budget

The sunset arc is always a half great circle, so tangent coverage of the whole 20,015 km at the
250 km maximum `nearby` radius would need 41 calls. The app deliberately spends 20, placed by
weighted equal-arc sampling: segments between 25° and 62° latitude get full weight (long twilights,
dense webcams), the tropics 0.60, 62–72° gets 0.45, and everything poleward of 72° is a hard cut —
about 22% of the arc's length lies over the Southern Ocean and Arctic pack ice and yields essentially
no webcams. This is a yield optimisation, not a coverage problem: missing cameras is acceptable,
returning bad ones is not.

A sample point that comes back with exactly `limit=50` results is saturated, so up to three
follow-up pages are requested at `offset=50` for the highest-yield points. **`offset` is only ever
0 or 50**, so the free tier's `offset ≤ 1000` limit is never approached.

Measured on 16 Oct 2026, a live sweep was **26 calls: 20 terminator probes, 2 adaptive pages, 4
fallback cities**, none failed. **14 of the 20 sample points returned nothing at all** — that is the
normal case, because most of the terminator is over water — and 6 carried every camera the payload
showed (284 candidates before ranking, 12 primary, 4 fallback).

### What a request costs

Three caches, all keyed on a coarse grid of the subsolar point rather than on time, because a time
bucket would change every bucket no matter how little the sun moved:

- **the Windy sweep** (`chase:<lonGrid>:<dec>:<samples>:<radius>`), TTL 300 s, with single-flight, so
  ten simultaneous page loads make one sweep rather than ten;
- **the DeepSeek curation**, TTL 300 s, which is the one that decides whether a warm request is fast;
- the position grid itself, 1° of subsolar longitude, which is stable for about four minutes.

The curation cache is the interesting one. `deepseek-flash` is a reasoning model, and a successful
curation call was measured at **13.4 s, 20.1 s, 29.2 s, 30.7 s and 46.1 s** on this link. Before it
was cached, every request paid that again for the same cameras under the same sun. Now:

| request | measured |
|---|---|
| cold, model unreachable (deterministic) | **0.9 s** |
| cold, model answers | **29.6 s** (of which 29.2 s is the model) |
| warm, sweep and curation cached | **27–33 ms** |

Keying that cache on the *offered* candidate ids looked more precise and was worse: the second
ranking pass re-measures the head of the list on every request, so a few seconds later the twelfth
candidate is a different camera, the key misses, and the cache never hits. It is keyed on the sweep
that produced the candidate pool instead. Two consequences are worth stating plainly:

- The frontend polls every 300 s, which is exactly the TTL, so **each poll is a cache miss and does
  pay a fresh sweep and a fresh model call**. The cache protects the Windy quota against concurrency
  and makes manual refresh instant; it does not make the poll cheap, and it should not, because
  fresh is the point of the app.
- `meta.llm.latencyMs` is the model's own latency even when the answer came from the cache, so
  `meta.llm.cached` says whether *this* request paid it. The diagnostics panel shows `(cached)`.

The frontend's request budget (60 s) is deliberately larger than the backend's model budget (45 s).
A budget below it would abort requests the server was about to answer, turning a slow success into a
timeout page. A model call that overruns its 45 s budget is not an error either: the response falls
back to the deterministic briefing, which is written from the same geometry and says something true
and specific, and `meta.llm.error` reports why.

### The model's output is untrusted, and so is its input

Camera titles are written by whoever registered the webcam, and they reach the model as data inside
a delimited JSON block that is explicitly labelled as data. The real defence is on the way back:
every `webcamId` the model returns is checked against the set that was offered, so no prompt
injection can introduce a camera Windy did not return — at worst it can reorder or reword real ones.
Reasons are stripped of control characters and capped at 240 characters, and the frontend renders
them as text nodes, never as HTML. The same is true of the briefing.

### The antimeridian, and the other two places it bites

The sunset arc spans 180° of longitude, so it always wraps. It bites in three separate ways, and all
three are handled: the backend **splits the arc at every ±180 jump** while building it (a live
payload is 2 sunset arcs and 1 sunrise arc, 1801 points each); the frontend draws each arc in **three
world copies** so panning past the date line does not end the line; and longitude arithmetic uses
`longitudeDelta`/`normalize180` everywhere, never a raw subtraction, with `haversineKm` taking four
scalars so degree and radian units cannot be mixed silently.

### Known limitations

- **Coverage is partial by design** — 20 probes, not the 41 that would touch the whole arc. Cameras
  between probes are simply not seen.
- `distanceToTerminatorKm` is the distance to the terminator *great circle*. It equals the distance
  to the **sunset** arc only when the hour angle is positive; a camera in the southern-hemisphere
  morning can be near the great circle yet far from the sunset arc.
- Windy's preview image tokens expire after about ten minutes. The 300 s poll is deliberately under
  that, each camera carries `imageExpiresAt`, and an image that fails anyway is re-minted through
  `GET /api/v1/webcams/:id` — capped at two retries per card, so a genuinely dead camera does not
  loop. `npm run test:chase` drives that path with a stubbed backend: a failed image is replaced by
  the fresh URL, and a camera whose URL does not change is reported as offline after two attempts
  rather than retried forever.
- **Visual browser rendering was not verified.** There is no browser in the environment this was
  built in. The map is checked at the DOM level — the real `TerminatorMap` mounted under
  `StrictMode` in jsdom, with per-layer shape counts against an empty-map baseline, plus
  mount/unmount/remount — and the page and components are checked by rendering them, but nobody has
  looked at the drawn terminator, so "no streak at the dateline" is verified as arithmetic
  (`worldCopies`) rather than as pixels.
