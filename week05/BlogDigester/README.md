# BlogDigester

A local "assignment desk" for blog reading. You save article URLs in a web form; on every run the
app re-fetches all of them, archives the readable text as Markdown, asks DeepSeek to rank them
against a theme and summarise the winners, and sets a self-contained front page in the style of a
1920s American newspaper.

## Requirements

- Node.js >= 20.12 (ESM, `fetch`, `node --test`).
- A DeepSeek API key, optional. Without one the edition still renders: ranking falls back to
  recency/topic overlap and summaries fall back to the article text, and the page says so.

## Setup

```bash
npm ci
cp .env.example .env      # optional; fill DEEPSEEK_API_KEY for model-written stories
npm start                 # http://localhost:3000
npm run dev               # same, with --watch
npm test                  # offline suite: no network, no key
```

Then, in the browser:

1. Add one URL per article page on the desk (feeds and homepages are not expanded).
2. Edit `settings.json` to set the theme, `topN`, and fetch/LLM tuning. It is re-read on every run,
   so no restart is needed.
3. Press **Compose the edition**. The run happens in the background; the run page refreshes itself.
4. Read `output/index.html` — served at `/output/index.html` while the server runs, and openable
   straight from disk because the page has no external assets.

Saved URLs live in `data/store.json`; the Markdown archive is `data/articles/<id>.md`. Both survive
restarts and are gitignored.

## Settings

`settings.json` is committed and validated on load. A malformed value warns and falls back; the app
never refuses to start because of settings.

| Key | Meaning | Default |
| --- | --- | --- |
| `topN` | Stories on the front page (1–50) | `8` |
| `theme` | Prompt for relevance ranking and summaries | AI / software engineering |
| `fetch.concurrency` | Pages fetched at once (1–16) | `4` |
| `fetch.perHostDelayMs` | Minimum gap between requests to one host | `1000` |
| `fetch.respectRobotsTxt` | Honour `robots.txt` | `true` |
| `fetch.timeoutMs` / `maxBytes` / `maxRedirects` | Per-request limits | 15 s / 5 MB / 5 |
| `llm.rankingCandidates` | Articles offered to the ranker (3–100) | `40` |
| `llm.summaryConcurrency` | Concurrent summary requests (1–8) | `3` |
| `llm.timeoutMs` / `maxTokens` / `temperature` | Model request limits | 45 s / 8000 / 0.4 |
| `output.dir` / `output.file` | Where the edition is written (relative only) | `output` / `index.html` |

Secrets stay in `.env`; `output.dir` is rejected if it is absolute or contains `..`.

## Endpoints

| Method | Path | Result |
| --- | --- | --- |
| GET | `/` | The assignment desk (add, list, remove, compose) |
| GET | `/health` | Status, saved-article count, whether a key is present, run state |
| GET | `/api/urls` | `{ articles }` |
| POST | `/api/urls` | `201 { article }`, `400` invalid, `409` duplicate |
| DELETE | `/api/urls/:id` | `204`, `404` unknown |
| POST | `/api/digest` | `202 { runId }`, `400` empty collection, `409` already running |
| GET | `/api/digest/status` | Latest run: `state`, `progress`, `result`, `error` |
| POST | `/run` | The form version: `303` to the run page |
| GET | `/runs/:runId` | Human-readable run report (auto-refreshes while running) |
| GET | `/output/index.html` | The generated edition |

```bash
curl -X POST http://localhost:3000/api/urls \
  -H 'content-type: application/json' \
  -d '{"url":"https://example.com/post"}'

curl -X POST http://localhost:3000/api/digest
# {"runId":"20261030120000-1","state":"running","statusUrl":"/api/digest/status"}
```

## How a run works

```
store.list() -> fetch + robots + extract  ->  data/articles/<id>.md  ->  store.update()
             -> rank (DeepSeek, metadata)  ->  summarize top N (DeepSeek)  ->  render  ->  output/index.html
```

- **Fetch** (`src/fetch-html.js`) is SSRF-guarded: http(s) only, no credentials, every DNS answer
  checked against loopback/private/link-local/CGNAT/metadata ranges, every redirect hop re-validated,
  a streaming byte cap, and retries only for 429/5xx/network faults. `src/robots.js` fails open when
  `robots.txt` is missing or unreachable, and a per-host gate enforces the delay.
- **Extract** (`src/extract.js`) uses Readability with an `<article>/<main>` fallback, then Turndown.
  Images become their alt text and non-http links are unwrapped, so the archive and the front page
  never load remote assets.
- **Model** (`src/llm.js`) never throws. Missing key, timeout, rate limit, garbage JSON or invented
  ids all end in a deterministic ranking/summary. Model strings are sanitised and capped; ids are
  checked against the offered set. Default model is `deepseek-flash`.
- **Render** (`src/render.js`) escapes every value and allows only http(s) `href`s. The page has one
  inline stylesheet, no scripts, no fonts and no images, so it opens from disk.
- **Runs** (`src/run-manager.js`) are process-local and one at a time. A second start is a `409`;
  the last 20 runs are kept so polling still works after a run finishes.

Per-article failures are expected (paywalls, bot walls, JavaScript-only sites). They are recorded on
the article (`status: failed`, `error: <code>`) and listed as notes on the front page; they never
abort the edition. A run fails only when nothing readable remains.

## Tests

```bash
npm test              # 80 offline tests, <1 s, no network and no keys
npm run test:online   # opt-in: real network + real DeepSeek key from .env
```

The offline suite injects every network dependency (fake fetcher, fake OpenAI client, temp
directories) and covers the SSRF guard, robots parsing, extraction, ranking/summary validation,
escaping in the renderer, the orchestrator and the HTTP API.

`npm run test:online` sets `RUN_ONLINE=1` through `scripts/run-online-tests.mjs` (no shell-specific
syntax). It exercises DeepSeek ranking, a live Wikipedia scrape, and a full run to `output/index.html`
in a temp directory. Set `ONLINE_URLS=https://site/a,https://site/b` to change the scrape targets. If
`DEEPSEEK_API_KEY` is missing, the two model-dependent cases skip with a message and the live scrape
still runs. Model calls are retried once and their latency is printed: the local DeepSeek path is
sometimes slow (13–46 s) or flaky, and the suite is designed to distinguish that from a code fault.

## Limitations

- Single process: run state and the "one run at a time" lock are in memory, and the store assumes
  one writer. Do not run two instances against the same `data/`.
- DNS-rebinding between the address check and the connection remains a theoretical SSRF gap. This is
  a local course project; put it behind an allowlisted proxy before exposing it.
- No scheduling, authentication, feeds, or rich-text editing. URLs are added one at a time, and each
  URL must be a single article page.
- `robots.txt` is honoured, and the default user agent identifies the project. Please keep the
  per-host delay when scraping small sites.
