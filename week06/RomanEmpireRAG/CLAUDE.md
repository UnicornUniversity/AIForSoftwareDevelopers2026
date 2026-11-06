# CLAUDE.md — week06/RomanEmpireRAG

Guidance for Claude Code when working in `week06/RomanEmpireRAG/`. The repository-root
`CLAUDE.md` still applies; this file narrows it to this project. `README.md` is the
human-facing overview.

## What this project is

Two course deliverables, one per spec, plus one shared ChromaDB store:

| spec | folder | deliverable |
|---|---|---|
| [`specs/chunks1.md`](specs/chunks1.md) | [`chunking/`](chunking/) | Chunk-size study over the six volumes in `data/`, an explicit size/overlap recommendation, and a standalone HTML report |
| [`specs/ui.md`](specs/ui.md) | [`rag-app/`](rag-app/) | Retrieval-augmented Q&A over Gibbon's *Decline and Fall*: ChromaDB vector retrieval plus DeepSeek answer synthesis, with a single-page UI (React + Vite frontend, Express backend) |

[`ingest.py`](ingest.py) and [`query.py`](query.py) are the Python side of retrieval: `ingest.py`
embeds the same chunks into ChromaDB, `query.py` prints ranked passages for checking an ingest. The
Express backend reads that store through `rag-app/backend/bridge/chroma_bridge.py`; it never
ingests.

The pieces connect through one generated artefact: `chunking/out/chunks.jsonl.gz`. `ingest.py`
regenerates the same chunks in-process from `chunking.py` and refuses to embed chunks that differ
from it. Regenerating the chunks changes what the app retrieves, so re-run the ingest and restart
the backend after changing chunking parameters.

`data/` holds the source corpus: six Project Gutenberg text files of *The History of the Decline and
Fall of the Roman Empire*. Treat them as immutable inputs.

[`semantic-chunking/`](semantic-chunking/) is an additional, exploratory study — not a spec
deliverable and not wired into the Chroma store. It answers *where* to cut (embedding-distance
boundaries) where `chunking/` answers *how large*; the two are deliberately separate and their
parameters must not be propagated across. `semantic-chunking/README.md` is the reference.

## Commands

### chunking — Python, standard library only

```bash
cd week06/RomanEmpireRAG/chunking
python chunking.py               # -> out/stats.json, out/volumes_view.json, out/chunks.jsonl.gz
python chunking.py --no-chunks   # skip the ~3 MB compressed chunk file
python chunking.py --explain     # print the segmentation decision for each volume
python make_html.py              # -> report.html (reads out/stats.json + out/volumes_view.json)
```

Run `chunking.py` first: `make_html.py` renders what it writes. `report.html` is generated (~9.5 MB,
the whole corpus is embedded for the full-text view). Never hand-edit it — change the generators
and rebuild. The report must stay standalone: no `<script>`, no network requests, opens by
double-click.

### ChromaDB ingestion — Python, needs `chromadb`

```bash
python -m pip install -r week06/RomanEmpireRAG/requirements.txt   # into the repo-root .venv
python week06/RomanEmpireRAG/ingest.py            # all six volumes -> week06/RomanEmpireRAG/chroma
python week06/RomanEmpireRAG/ingest.py --volumes 1  # one volume, same chunk ids as the full run
python week06/RomanEmpireRAG/ingest.py --append     # upsert into an existing collection
python week06/RomanEmpireRAG/ingest.py --stats      # chunks per volume, distinct chapters
python week06/RomanEmpireRAG/query.py "Why did the Western Empire fall?" -k 3
python week06/RomanEmpireRAG/query.py --volume 4 "Who was Belisarius?"
python week06/RomanEmpireRAG/query.py --chapter "Last Victory" "Belisarius" -k 2
python week06/RomanEmpireRAG/query.py --json "Who was Belisarius?"
```

Defaults come from the study: target/overlap are read from `chunking/out/stats.json` (`best`), and
fall back to 1,500/100 if it has not been generated. The full run is 5,772 chunks and takes about a
minute once Chroma's MiniLM model is cached (`~/.cache/chroma/onnx_models`, ~79 MB downloaded on
first use). The store lands in `week06/RomanEmpireRAG/chroma` (~126 MB on this checkout,
gitignored); `--db` changes it. A normal run replaces the collection, `--append` upserts
into it.

On this checkout the repo-root `.venv` already has `chromadb`; on Windows invoke it
directly: `.venv/Scripts/python.exe week06/RomanEmpireRAG/ingest.py`.

### rag-app backend — Node >= 20.12, ESM

```bash
cd week06/RomanEmpireRAG
.venv/Scripts/python.exe ingest.py   # once: build chroma/ (the backend only reads it)
cd rag-app/backend
npm ci
cp .env.example .env             # optional; with no .env the service answers extractively
npm start                        # http://localhost:8788 (via scripts/start.js)
npm run dev                      # same with node --watch
npm test                         # node --test "test/**/*.test.js"; 34 tests, no network
```

The one hard dependency is `week06/RomanEmpireRAG/chroma`: `npm start` exits with the path and the `ingest.py`
command if it is missing. The backend spawns `bridge/chroma_bridge.py` with the first interpreter
it finds (`week06/.venv`, then the repo-root `.venv`, then `PATH`; override with `CHROMA_PYTHON`).

`DEEPSEEK_API_KEY` is optional. A missing key, a timeout, a rate limit or an unusable model reply
all degrade to an extractive answer; the server must not return 5xx because an upstream is
missing. `.env` is loaded with `process.loadEnvFile()` guarded by `existsSync`, so no `.env` is
needed.

`scripts/start.js` launches the server with `--use-system-ca` when the interpreter supports it
(Node >= 24), because a TLS-scanning antivirus or corporate proxy can intercept `api.deepseek.com`.
Windows tools accept that chain from the OS store; Node reads its own CA list and fails with
`SELF_SIGNED_CERT_IN_CHAIN`, which surfaces as the extractive fallback and the note "the model
connection failed because HTTPS is being intercepted…". Setting `NODE_EXTRA_CA_CERTS` inside `.env`
does **not** work — config.js loads the file after Node has already built its CA list; the variable
must be in the environment before Node starts. `npm start` stays on Node >= 20.12: the launcher
simply omits the flag where it does not exist.

### rag-app frontend — React 19 + Vite

```bash
cd week06/RomanEmpireRAG/rag-app/frontend
npm ci
npm run dev                      # http://localhost:5174, proxies /api to 8788
npm test                         # node --test; 6 tests for src/lib/highlight.js
npm run build                    # -> dist/
```

The page implements `specs/ui.md`: a question input and Search button, a read-only textarea for
the answer, and a ranked list of retrieved passages. `?q=...` opens the page on a question. The
port is 5174 so this app can run beside sunset-chaser's frontend. The UI talks to the backend only
through `src/api.js`; nothing else calls `fetch`.

## Architecture: chunking

```
data/*.txt -> read_volume -> split_blocks -> classify -> split_sentences
                                                          |
                                    flatten -> pack (sweep) -> chunk_metrics -> score
                                                                                |
                                              stats.json + volumes_view.json + chunks.jsonl.gz
                                                                                |
                                                                    make_html.py -> report.html
```

`chunking.py` is the single source of truth for every number the report shows. `make_html.py` is a
renderer only — if a statistic is missing or wrong, fix `chunking.py` and regenerate, never patch
the HTML.

Non-obvious decisions, all load-bearing:

- **Body location is structural.** Volumes label their contents inconsistently (`CONTENTS`, an
  unlabelled TOC, …). The body starts at the first heading followed within two blocks by a
  paragraph over 1,000 characters. Do not switch to a marker-based detection.
- **Classification never uses indentation.** Paragraph indentation differs per volume (six spaces,
  flush, five spaces for synopses); use opening words and block length instead.
- **Abbreviation-aware sentence splitting.** `St.`, `M.`, `A.D.`, `i.e.` and a long Latin/English
  list must not end a sentence.
- **Packing prefers whole paragraphs and closes at a sentence.** Overlap is carried in whole
  sentences from the previous chunk, never across a chapter heading.
- **The sweep is a grid, not a search.** 10 targets × 5 overlaps; configurations where overlap
  exceeds 20% of the target are dropped before scoring. The 512-token embedding-window constraint
  (`target + ~110-char heading prefix <= 2,048 chars`) is hard, applied before ranking.
- **Score weights:** 35% size stability (share within ±20% of target), 25% single-paragraph chunks,
  20% restored context (chunks opening on a pronoun whose antecedent is carried in), 20% inverse
  overlap cost. The weights are a judgement; the metrics are measured.
- **The recommendation is a plateau, not a point.** 1,500 chars (~375 tokens) with 100 chars of
  requested overlap wins; everything from 1,200 to 1,800 chars is within 1% of the best score, so
  an operational constraint may legitimately pick another point. Reporting a single winner without
  the plateau overstates precision.
- **Token counts are estimates** (chars/4, cross-checked with words/0.75). No tokenizer is
  vendored; do not present these as exact.

Invariants enforced at runtime (the run fails rather than emitting a plausible report):

- emitted chunks cover **100%** of the corpus body;
- every chunk is a contiguous sentence range (a word-split chunk cannot be laid out and is
  rejected);
- every sentence belongs to exactly one owning chunk in `volumes_view.json` (overlapping copies are
  shown once, tagged as overlap);
- the volume view drops and repeats no sentence.

`chunks.jsonl.gz` format — one JSON object per line:
`id` (`v1-00000`), `volume`, `chapter`, `chars`, `words`, `tokens`, `paragraph_from`,
`paragraph_to`, `overlap_chars`, `text`. 5,772 chunks at the recommended parameters.

## Architecture: ChromaDB ingestion

```
data/*.txt -> ingest.load_volume -> flatten -> pack  (all imported from chunking/chunking.py)
                                                       |
                                        Chroma PersistentClient (cosine, collection "gibbon")
                                                       |
                          week06/RomanEmpireRAG/chroma/  <- query.py                  (CLI check)
                                                       <- rag-app bridge/chroma_bridge.py
                                                             <- Express /api/ask   (the UI)
```

- **Segmentation is not duplicated.** `ingest.py` imports `load_volume`, `flatten` and `pack` from
  `chunking/chunking.py`. The resulting 5,772 chunks are byte-identical to
  `chunking/out/chunks.jsonl.gz`; every run checks ids, volumes and text against that file and
  refuses to ingest if they differ (re-run `chunking.py` instead). Never re-implement splitting in
  `ingest.py`.
- **A `--volumes` subset still segments the whole corpus**, then filters before embedding, so ids
  stay identical to the full run (`v{volume}-{global_index:05d}`).
- **Embeddings are local.** Chroma's `DefaultEmbeddingFunction` runs all-MiniLM-L6-v2 through ONNX;
  no API key, no network after the one-time model download. It is deterministic for a given model,
  so `query.py` embeds questions the same way.
- **`volume` and `chapter` are required metadata, not optional decoration.** `extract_metadata`
  rejects a chunk whose volume is not a positive integer or whose chapter is blank, so a
  segmentation bug fails the ingest instead of producing unfilterable vectors. Every stored chunk
  has both; a full run currently covers 6 volumes and 300 distinct (volume, chapter) pairs. The
  remaining fields (`chars`, `words`, `tokens`, `paragraph_from`, `paragraph_to`, `overlap_chars`,
  `split`) describe how the chunk was cut.
- **The space is cosine**, which makes the reported score `1 - distance` meaningful.
- **Filters use the stored metadata.** `query.py --volume` becomes a native Chroma `where` clause.
  Chroma rejects `$contains` on string metadata here, so `--chapter` is a case-insensitive substring
  applied after retrieval; that path asks for every candidate (not just top-k) so filtering never
  silently drops a better match. `ingest.py --stats` prints the per-volume counts and distinct
  chapter count, which is the quickest check that metadata landed.
- **Re-runs are idempotent.** A normal run deletes and recreates the collection; `--append` keeps it
  and `upsert`s, so interrupted ingests can be resumed.
- **The Node backend reads the store, it does not ingest.** `bridge/chroma_bridge.py` is a
  line-oriented process: one `{id, question, k}` per line in, one `{id, ok, results}` out, plus a
  single `ready` line with the collection's counts. It exists because the query must be embedded
  with the same Python `DefaultEmbeddingFunction` as the passages; re-implementing MiniLM in
  JavaScript would risk a silent vector space mismatch. The adapter keeps the app's contract:
  `search(question, {k}) -> {chunk, score, rank, matchedTerms}`, with `score = 1 - distance`
  (cosine, clamped at zero). Rebuilding the collection while the backend runs invalidates the
  bridge's handle; restart the backend after an ingest.

## Architecture: rag-app

```
POST /api/ask -> app.js -> chroma.js search -> services/answerer.js
                              | (JSON lines)        |-> services/llm.js (DeepSeek)
                              v                     \-> services/extractive.js (fallback)
                    bridge/chroma_bridge.py -> week06/RomanEmpireRAG/chroma
```

- `src/index.js` — startup. Starts the Chroma bridge (the one hard dependency: fail with the store
  path and the `ingest.py` command rather than boot a service that answers nothing), listens on
  8788, closes the bridge on SIGINT/SIGTERM and on `exit` (so `node --watch` does not orphan it).
- `src/config.js` — all env parsing; `int()`/`str()` warn and fall back rather than throw, matching
  sunset-chaser's "boots with no `.env`" property. Never expose a key value; `/api/health` reports
  only `hasLlmKey`. `CHROMA_DB`, `CHROMA_COLLECTION`, `CHROMA_PYTHON`, `CHROMA_BRIDGE` and
  `CHROMA_TIMEOUT_MS` select the store and interpreter; venv detection tries `week06/.venv` before
  the repo root.
- `src/chroma.js` — the adapter. One long-lived child process, one JSON request per line, pending
  requests matched by id and bounded by `CHROMA_TIMEOUT_MS`; a bridge that dies or overruns is
  dropped so the next request starts a fresh one. `toResults` maps Chroma rows to the app contract
  (`{chunk, score, rank, matchedTerms}`) with `score = 1 - distance` clamped at zero;
  `matchedTerms` is for highlighting only and may be empty for a paraphrase.
- `bridge/chroma_bridge.py` — reader only: checks that `chroma.sqlite3` exists, opens the
  collection with `DefaultEmbeddingFunction`, emits one `ready` line with the corpus counts, then
  answers queries. Stdout is protocol only; Chroma/ONNX logging goes to stderr.
- `src/lib/text.js` — tokenizer, stopword list, conservative plural stemmer and abbreviation-aware
  sentence splitter. Retrieval is semantic, but `matchedTerms` and extractive quotes still use it.
- `src/services/llm.js` — DeepSeek via the OpenAI-compatible SDK. Never throws: every failure
  becomes an error code, and the socket code (`err.cause.code`) is carried alongside it so a TLS
  trust problem is not flattened into "request failed". Passages are labelled as data in the prompt
  and the system message instructs the model to ignore instruction-like text inside them. Output
  passes through `lib/sanitize.js` (control characters stripped, length capped).
- `src/services/extractive.js` — the no-model answer. It quotes retrieved sentences and says in the
  first line why there is no synthesised answer; it must never pretend to be generated prose.
- `src/services/answerer.js` — mode selection: `ANSWER_MODE=extractive` or no key → extractive;
  otherwise try DeepSeek and fall back on any failure, carrying the attempt latency.
- `src/app.js` — `createApp({retriever, answerer, config, logger})` takes dependencies explicitly
  so tests can run the real Express stack with a fixture retriever and scripted answerer. Adds
  `x-request-id` and logs on `finish`; a retrieval failure is a scrubbed 503
  `retrieval_unavailable`, other 5xx bodies are scrubbed and reference the id. Express 5 requires a
  named catch-all: `/{*splat}`.

Frontend: `src/App.jsx` owns the question, result and loading state, the 120 s request budget and
one in-flight request at a time (a new search aborts the previous one). It renders
`components/AnswerPanel.jsx` (read-only textarea plus a source badge) and
`components/ChunkList.jsx` (ranked passages, score bars, query-term highlights, per-passage
expansion). `src/lib/highlight.js` returns text segments rendered as text nodes; there is no
`dangerouslySetInnerHTML` anywhere. `src/api.js` is the only module that calls `fetch`.

### Tests

- `backend/test/*.test.js` — 34 tests on a six-chunk fixture, a fake line-protocol child process
  and a scripted OpenAI client. No network, no key, no Python and no ChromaDB needed.
- `frontend/test/highlight.test.js` — 6 tests on the pure highlight helpers via `node --test`.

### HTTP contract

- `GET /api/health` → `{ok, service, corpus:{chunks,volumes,chapters,characters},
  retrieval:{backend:"chromadb",collection,metric}, answer:{mode,hasLlmKey,model}, uptimeSeconds}`
- `POST /api/ask` body `{"question": "..."}` → `{requestId, question, answer, answerSource:
  "deepseek"|"extractive"|"none", llm:{model,error,cause,note,finishReason,latencyMs}|null,
  retrieval:{latencyMs,candidates,returned,matchedTerms}, chunks:[{rank,id,volume,chapter,score,
  chars,matchedTerms,text}], timing:{totalMs}}`
  — `llm.note` is the human sentence for `llm.error` (e.g. "no DEEPSEEK_API_KEY is configured"),
  produced server-side so the UI does not keep a second copy of the code table.
- 400 `question_required` / `question_too_long`; 404 `not_found`; 5xx `internal_error` with the
  request id. Questions are capped at `MAX_QUESTION_CHARS` (default 500); the JSON body is capped at
  16 KB.

## Shared conventions

- **Python**: standard library only in `chunking/`. Do not add NumPy/pandas/a tokenizer to make a
  number nicer. `ingest.py`, `query.py` and `rag-app/backend/bridge/chroma_bridge.py` are the only
  files that may import `chromadb`; keep the chunking study runnable with a bare interpreter.
- **Node**: ESM (`"type": "module"`), Node >= 20.12, `node --test` for tests (no Jest/Vitest).
- **Env files**: `.env` is gitignored; `.env.example` is the committed template. In `rag-app` every
  value is optional and documented in that file.
- `.env.example` notes the DeepSeek link has been measured between 13 and 46 seconds on this
  machine. `LLM_TIMEOUT_MS` (40 s) and `LLM_MAX_RETRIES` (1) are sized for that; keep the
  frontend's wait above `LLM_TIMEOUT_MS * (1 + retries)`.
- HTTPS to DeepSeek may pass through a TLS-inspecting proxy. Node cannot trust it from the OS store
  before Node 24, so use `npm start` (which adds `--use-system-ca` where available) rather than
  calling `node src/index.js` directly, or set `NODE_EXTRA_CA_CERTS` in the shell before launch.
- Generated files (`chunking/out/*`, `chunking/report.html`, `chroma/`) are rebuilt, not
  edited. Data files are committed as-is; do not reformat them.
