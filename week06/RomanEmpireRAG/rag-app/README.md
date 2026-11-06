# Roman history RAG

A single-page application for asking questions about the Roman Empire, answered from
Edward Gibbon's *The History of the Decline and Fall of the Roman Empire* (six volumes,
5,772 passages). It implements [`../specs/ui.md`](../specs/ui.md):

1. a text box for a question and a **Search** button;
2. a read-only textarea for the answer;
3. a ranked list of the passages the answer was built from.

Retrieval is **ChromaDB** vector search over the chunks produced by
[`../chunking`](../chunking); answers are synthesised by **DeepSeek** when a key is
configured, and quoted from the retrieved text otherwise.

```
Browser (React + Vite, :5174) ──/api──> Express (:8788) ──JSON lines──> Python bridge
                                         ├─ ChromaDB vector search          └─ chroma/
                                         ├─ DeepSeek answer synthesis   (if a key is set)
                                         └─ extractive quoted answer    (otherwise)
```

## Quick start

The ChromaDB store is built **once, by a separate command** — the backend only reads it:

```bash
# from the repository root, with a Python that has chromadb
# (see week06/RomanEmpireRAG/requirements.txt)
.venv/Scripts/python.exe week06/RomanEmpireRAG/ingest.py   # or: python week06/RomanEmpireRAG/ingest.py
```

Then, two terminals, both from `week06/RomanEmpireRAG/rag-app`:

```bash
# 1 — backend, http://localhost:8788
cd backend
npm install
cp .env.example .env      # optional; add a DEEPSEEK_API_KEY for generated answers
npm start

# 2 — frontend, http://localhost:5174
cd frontend
npm install
npm run dev
```

Open <http://localhost:5174> and ask something. `?q=` opens the page directly on a
question, e.g. <http://localhost:5174/?q=Who+was+Belisarius%3F>.

With no `.env` at all the app still works: answers are **extractive**, quoted from the
passages ChromaDB returned. Set `ANSWER_MODE=extractive` to force that mode even when a
key is present.

The backend spawns `backend/bridge/chroma_bridge.py` with the first interpreter it finds
that has `chromadb` — `week06/.venv`, the repo-root `.venv`, then `PATH`. Override it
with `CHROMA_PYTHON`. If the store is missing the server exits with the path and the
command that builds it.

## What the page shows

- **Answer** — a read-only textarea. Generated answers cite the passages they used as
  `[1]`, `[2]`. Extractive answers say so in the first line, quote the passages, and
  keep the same citation numbers.
- **Related passages** — the top matches, with volume and chapter, cosine similarity,
  a relative score bar, and the query words highlighted. Longer passages expand in
  place.
- A status pill reports whether the model or extractive mode is in use; if the backend
  is down, the page says so and how to start it.

## How retrieval works

```
question -> Chroma bridge -> all-MiniLM-L6-v2 embedding -> cosine search -> top 6 chunks
```

- **The vectors are local.** `ingest.py` embedded every chunk with Chroma's
  default embedding function (all-MiniLM-L6-v2 through ONNX), so retrieval needs no API
  key and no network after the model is cached.
- **One embedding function.** A question must be embedded exactly like the passages.
  That function lives in Python, so the Node service keeps one bridge process alive and
  sends it `{id, question, k}` per line. The bridge talks to `chroma/` and returns
  ids, text, metadata and distances.
- **Cosine similarity.** The collection was created with `hnsw:space = cosine`, so the
  score shown in the UI is `1 - distance`, clamped at zero. Chroma's row order is the
  rank order; there is no second scoring pass.
- **Matching is semantic, not lexical.** A paraphrase can retrieve a passage that shares
  no words with the question; `matchedTerms` (used only for highlighting) may therefore
  be empty.
- The backend never ingests. Rebuilding the store is an explicit `ingest.py` run; restart
  the backend afterwards so the bridge reopens the new collection.

## The three answer paths

| `answerSource` | when | what the user sees |
|---|---|---|
| `deepseek` | a key is configured and the call succeeds | a 2–5 sentence answer grounded in the passages, with `[n]` citations |
| `extractive` | no key, `ANSWER_MODE=extractive`, or any model failure | a quote-based answer that starts by naming the reason |
| `none` | retrieval returned no passage (for example, an empty collection) | a prompt to name a person, place, office, battle or law |

The model is **never required**. A missing key, a timeout, a rate limit or an empty reply
degrades to the extractive answer; the server does not return 5xx because an upstream is
missing. The reason is carried in `llm.error` (a code) and `llm.note` (human text), and is
shown in the answer badge.

If the Chroma bridge itself fails (a dead interpreter, a store deleted underneath it),
`/api/ask` returns a scrubbed **503 `retrieval_unavailable`** referring to the request id;
that is a service fault, not a bad question.

The answer prompt restricts the model to the supplied passages and says they are data,
not instructions. Replies pass through `sanitizeAnswer` (control characters stripped,
length capped) and are displayed as text in a textarea, so model or corpus text can never
become markup.

## API

```bash
curl http://localhost:8788/api/health

curl -s http://localhost:8788/api/ask \
  -H 'content-type: application/json' \
  -d '{"question":"Why did the Western Roman Empire fall?"}'
```

- `GET /api/health` →
  `{ok, service, corpus:{chunks,volumes,chapters,characters},
  retrieval:{backend:"chromadb",collection,metric}, answer:{mode,hasLlmKey,model},
  uptimeSeconds}` — never includes a key value.
- `POST /api/ask` body `{"question":"..."}` →
  `{requestId, question, answer, answerSource, llm, retrieval, chunks, timing}`.
  Every response carries `x-request-id`; 400 bodies are `question_required` or
  `question_too_long`, unknown routes are a JSON 404, and 5xx bodies are scrubbed and
  reference the request id.

Questions are capped at 500 characters and the JSON body at 16 KB.

## Configuration

All values are optional except the store itself; see
[`backend/.env.example`](backend/.env.example). The ones worth knowing:

| variable | default | effect |
|---|---|---|
| `DEEPSEEK_API_KEY` | empty | absent → extractive answers |
| `DEEPSEEK_MODEL` | `deepseek-flash` | model id passed to DeepSeek |
| `ANSWER_MODE` | `auto` | `extractive` never calls the model |
| `LLM_TIMEOUT_MS` | `40000` | one answer attempt; a timeout falls back, it is not an error |
| `LLM_MAX_RETRIES` | `1` | SDK retries for connection errors, 429 and 5xx |
| `CHROMA_DB` | `../../chroma` | store built by `ingest.py` |
| `CHROMA_COLLECTION` | `gibbon` | collection name |
| `CHROMA_PYTHON` | detected venv | interpreter with `chromadb` |
| `CHROMA_TIMEOUT_MS` | `30000` | bridge start-up and one query |
| `TOP_K` | `6` | passages retrieved per question |

The link to DeepSeek has been measured at 13–46 seconds on this machine, so the frontend
waits 120 s — above `LLM_TIMEOUT_MS × (1 + LLM_MAX_RETRIES)` — and shows a "may take up
to 40 seconds" hint while waiting rather than looking frozen.

## Tests

```bash
cd backend && npm test     # 34 tests, no network, no API key, no ChromaDB
cd frontend && npm test    # 6 tests for the highlight helpers
```

Backend tests use a six-chunk fixture, a fake line-protocol child process and a scripted
OpenAI client, so the HTTP shape, the Chroma framing/mapping and every model path
(success, 401, timeout, empty reply) run without Python, a store or a key.

## Corpus provenance

The passages are `../chunking`'s output at roughly 1,500 characters per chunk with
100 characters of requested overlap. `../ingest.py` segments the same corpus with the
same code and refuses to embed chunks that differ from `chunking/out/chunks.jsonl.gz`.
Regenerating the chunks changes what the app retrieves: re-run the ingest and restart the
backend.

## Known limits

- **Pure vector retrieval.** A question that names a rare proper noun may be outranked by
  a semantically similar passage; the retrieved list is evidence, not a citation index.
  There is no lexical/BM25 hybrid.
- Answers are not verified against the passages beyond the prompt; the passages beside
  the answer are the evidence, and the UI says so.
- Overlap means adjacent chunks can both surface in one result list.
- The bridge holds the store open. Rebuilding the collection while the backend runs
  invalidates its handle; restart the backend after an ingest.
- No authentication, rate limiting or persistence: this is a coursework UI.

## Files

```
backend/
  bridge/chroma_bridge.py   Python side of the JSON-line protocol (reads Chroma only)
  src/index.js              startup: open the bridge, listen, graceful shutdown
  src/app.js                Express routes and error handling
  src/config.js             env parsing; boots with no .env
  src/chroma.js             bridge client + Chroma rows -> retrieval results
  src/lib/text.js           tokenizer and sentence splitter (matched terms, quotes)
  src/lib/sanitize.js       model-output bounding
  src/services/llm.js       DeepSeek call; never throws
  src/services/extractive.js quote-based fallback answer
  src/services/answerer.js  mode selection and fallback orchestration
  test/                     node --test suites and the shared fixture
frontend/
  src/App.jsx               page state, search, results layout
  src/api.js                fetch wrapper with a 120 s budget
  src/components/           status pill, answer panel, passage list
  src/lib/highlight.js      query-term highlighting (no HTML)
  src/styles.css            light/dark theme, responsive layout
  test/                     node --test for the pure helpers
```
