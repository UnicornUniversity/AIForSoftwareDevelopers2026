# YoutubeDigester

Give it the first video of a YouTube course (or a playlist). It finds the rest of
the course, downloads every transcript into a local depot, proposes a course-wide
list of topics, lets you tick the ones you want, and builds one PDF companion —
by default explained the way you would explain it to a curious 10-year-old.

Everything stays on your machine: transcripts in `data/`, PDFs in `output/`, and
the only outbound calls are the YouTube Data API, YouTube's public captions, and
DeepSeek (all optional).

## Quick start

```bash
npm install
cp settings.example.json settings.json   # then fill in the two keys
npm start                                # http://localhost:3001
npm test                                 # offline: no network, no keys, no Chromium
```

Port 3001 keeps it beside its sibling `../BlogDigester` (port 3000). Override
with `PORT` in `.env` or the environment.

Keys can live in `settings.json` (gitignored, takes precedence) or in `.env` /
the environment as `YOUTUBE_API_KEY` and `DEEPSEEK_API_KEY`. `settings.example.json`
is the committed template with blank keys; `settings.json` never leaves the
machine and is never rendered by the app — the settings page only shows whether
each key is set.

Both keys are optional:

| Missing | What still works |
| --- | --- |
| `youtube.apiKey` | A playlist URL (`&list=…` or `/playlist?list=…`) is still followed; with only a bare video URL the course degrades to that one video, with a visible warning. |
| `deepseek.apiKey` | Topics are grouped locally by contiguous videos; chapters are assembled from the transcripts instead of written by the model. The PDF still builds and says both things. |

The server never returns a 5xx because an upstream is missing.

## The flow

1. **Add a course** — paste a first-lecture URL (`watch?v=…`, optionally with
   `&list=…`) or a playlist URL. The first lecture stays the anchor; the playlist
   hint is used when present.
2. **Discovery** — playlist first; otherwise the channel's playlists matching the
   derived course title; otherwise the channel's videos filtered by course tokens,
   duration and Shorts. The cap is `youtube.maxVideos` (default 30); the seed video
   is always kept.
3. **Transcripts** — fetched with `youtube-transcript`, in the configured
   languages, saved as Markdown under `data/videos/<videoId>.md`. A video without
   usable captions is marked and skipped, not fatal.
4. **Topics** — DeepSeek proposes a course-wide topic list with summaries; you
   tick what you want on the course's **Review topics** page.
5. **PDF** — one chapter per selected topic, in proposal order, with a cover,
   contents, key ideas and a sources list.

## Endpoints

Pages (server-rendered, no client JavaScript; run pages refresh with `<meta>`).

| Method | Path | Result |
| --- | --- | --- |
| GET | `/` | Home: add form, courses, key banner |
| POST | `/courses` | Validate seed; 303 to the course (`notice=started\|duplicate`); 400 when invalid |
| GET | `/courses/:id` | Course status and progress |
| GET | `/courses/:id/topics` | Topic checkboxes; 409 until a proposal exists |
| POST | `/courses/:id/topics` | Save the selection and start a PDF job; 303 to the run |
| POST | `/courses/:id/reingest` | Retry discovery/transcripts (`force=1` re-fetches transcripts) |
| POST | `/courses/:id/delete` | 303 home |
| GET | `/courses/:id/runs/:jobId` | Run report |
| GET | `/courses/:id/runs/:jobId/download` | PDF attachment; 409 not ready, 410 file gone |
| GET | `/settings` | Effective settings with keys redacted |

JSON API (same behaviour, JSON bodies). `POST /api/digest` is a deprecated alias
of `POST /api/courses`.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | Status, model, key booleans, counts; never 5xx |
| GET | `/api/courses` | `{ courses }` |
| POST | `/api/courses` | `{ url }` → 201 new / 200 duplicate |
| GET | `/api/courses/:id` | `{ course, videos, proposal, selection, jobs }` |
| GET | `/api/courses/:id/topics` | `{ proposal }`; 409 not ready |
| POST | `/api/courses/:id/selection` | `{ topicIds }` → 202 `{ selection, job }` |
| POST | `/api/courses/:id/reingest` | `{ force? }` → 202 `{ job }` |
| GET | `/api/courses/:id/jobs` | `{ jobs }` |
| GET | `/api/jobs/:id` | Pollable job |
| GET | `/api/courses/:id/pdf` | Latest completed PDF metadata |
| DELETE | `/api/courses/:id` | 204; 409 while a job runs |

```bash
curl -s -X POST http://localhost:3001/api/courses \
  -H 'content-type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL…"}'
```

Course ids look like `c_0123456789ab`; job ids are UUIDs. Invalid ids are 404.
4xx messages are written for humans; 5xx bodies are scrubbed and carry the
request id instead of upstream detail.

## Settings

`settings.json` is validated at startup (and reloaded before every job, so edits
apply without a restart). A missing, malformed, or unknown value warns and falls
back — it never throws. The full schema with every default is in
`settings.example.json`; the parts you are most likely to touch:

| Block | Field | Meaning |
| --- | --- | --- |
| `youtube` | `apiKey` | Data API v3 key (or `YOUTUBE_API_KEY`) |
| | `maxVideos` | Course size cap, 1–200 |
| | `minDurationSeconds` | Drop shorter videos from channel search |
| | `includeShorts` | Whether Shorts may be part of a course |
| `deepseek` | `apiKey`, `baseURL`, `model`, `temperature` | OpenAI-compatible client |
| `transcript` | `languages`, `maxChars`, `concurrency`, `requestDelayMs` | Caption fetching |
| `llm` | `topicsMin`/`topicsMax`, `chapterMaxChars`, `chapterConcurrency` | Bounded prompting and output |
| `pdf` | `pageSize`, `includeCover`, `includeToc`, `pageNumbers` | Book structure |
| `pdf.style` | `tonePrompt`, `readingLevel`, fonts, colours, margins | The 10-year-old voice and the look |
| `output` | `dir`, `pdfName` | Where PDFs go (relative to the app, cannot escape it) |
| `jobs` | `concurrency`, `stateWriteIntervalMs`, `maxWarnings` | Background work |

The default `pdf.style.tonePrompt` is the whole point of the default voice:

> Explain the material for a curious 10-year-old. Use simple words, short
> paragraphs, and everyday analogies (toys, games, cooking, school). Introduce one
> idea at a time and define any hard word the first time it appears. Stay accurate:
> do not invent facts, numbers or names. End each chapter with three short takeaways.

Colours must be `#rrggbb`; margins 5–50 mm; font sizes 8–24 pt; `pageSize` is
`A4` or `Letter`. Unsafe values fall back rather than reaching the stylesheet.

## YouTube quota

The Data API costs units. The defaults are chosen for a free-tier 10,000-unit day:

| Call | Units |
| --- | --- |
| Video metadata (`videos`, ≤50 ids per call) | 1 per call |
| Playlist info (`playlists`) | 1 |
| Playlist items (`playlistItems`, ≤50 per page) | 1 per page |
| Channel video search (`search`) | 100 per page |
| Channel playlist search (`search`) | 100 per page |

A course with a `list=` hint costs a handful of units. Search-based discovery
costs at least 100 per course and is the first thing to avoid: prefer playlist
URLs, lower `youtube.searchPages`, and reuse a course (duplicate seeds are not
re-ingested). Responses are cached per client with a TTL, and failures are not.

## Disk layout

```
data/
  depot.json                 course, video, topic and job index
  videos/<videoId>.md        transcript with YAML frontmatter
  runs/<jobId>/
    state.json               job snapshot (survives restarts)
    chapters.json            written after every chapter
    digest.html              the exact HTML handed to Chromium
output/<courseId>/<jobId>.pdf
```

Writes are atomic (sibling `.tmp` then rename) and serialised per path. If the
server stops mid-job, the next start marks that job `interrupted` and the course
`failed`; re-ingest reuses the transcripts that already succeeded.

## Design notes

- The pipeline is `discover → ingest → llm → generate → render-book → pdf`, with
  `jobs.js` orchestrating and `depot.js` as the only persistence layer.
- Model output is untrusted: JSON only, every string sanitised and capped, every
  returned video id checked against the set that was offered, and every string is
  HTML-escaped before it reaches the PDF.
- `youtube.js` puts the key on the outgoing URL only — never in logs, cache keys
  or error messages.
- Puppeteer launches lazily and is reused; `PUPPETEER_EXECUTABLE_PATH` points at
  a local Chrome if the bundled browser cannot start. Tests inject a fake
  launcher, so `npm test` neither downloads nor launches Chromium.

## Tests

`npm test` runs `node --test` over `test/` (147 tests, well under a second). Every
file uses fakes for the network, the model, and the browser:

```
store  settings  depot  youtube  discover  transcript  llm
jobs   ingest    generate  render-book  pdf  app
```

Run one file with `node --test test/app.test.js`, or one case with
`--test-name-pattern=<regex>`.

## Limitations

- `youtube-transcript` is unofficial and can break or be rate-limited; each video
  fails on its own and the course stays usable.
- Channel search is a heuristic: a course without a playlist may miss videos or
  pick up neighbours. Playlist URLs are always the reliable path.
- The table of contents lists chapters without page numbers — Chromium has no
  `target-counter`; the footer shows "page X of Y".
- Topic discovery is capped by `llm.clusterMaxTotalChars`, so very long courses
  are summarised from the beginning of each transcript.
- One PDF per selection run; the latest completed PDF is what the course page
  links to.
