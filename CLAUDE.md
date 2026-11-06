# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Coursework for *AI For Software Developers* (autumn 2026). One folder per week, one self-contained
assignment per subfolder. There is **no root-level build, test, or package manifest** — every
project is run from its own directory, and `README.md` at the root is just the course title.

Beyond code, weeks contain non-code deliverables (PDFs, Markdown knowledge bases, prompt/agent
transcripts) that are committed as-is. Do not "clean up" or reformat them.

## Naming convention: one folder per AI tool

Several assignments are solved more than once for comparison, in sibling folders named after the
tool: `week02/lottery/{claude,copilot}/`, `week02/hello-world-{copilot,claude-ollama,aider-ollama}/`,
`week03/{sunset-chaser,sunset-chaser-copilot}/`. When changing one solution, do **not** propagate the
change to its siblings — the divergence is the deliverable.

Each assignment folder also carries the original `spec.md` it was built against. Treat `spec.md` as
the requirement and the tool-named folder as one answer to it.

## Commands

Run these from the listed directory; `npm test` at the repo root does nothing.

### week03/sunset-chaser — the main application

```bash
# backend (http://localhost:8787)
cd week03/sunset-chaser/backend && npm ci && cp .env.example .env
npm run dev
npm test              # 102 tests, ~300ms, no network, no API keys needed

# frontend (http://localhost:5173)
cd week03/sunset-chaser/frontend && npm ci
npm run dev
npm test              # test:map && test:chase && test:api
npm run test:map      # single check; also test:chase, test:api
```

A single backend test file: `node --test test/scoring.test.js` (add `--test-name-pattern=<regex>`
to narrow to one case).

The frontend checks are `.jsx` and import application source, so `test/run-check.mjs` bundles each
one with the Vite already in `devDependencies` and runs the bundle in Node — there is deliberately
no second test runner. `test:api` prefers a **live** backend payload and falls back to
`test/fixtures/payload.js`, printing which it used; a fixture run proves less because the fixture
was written by the same hand as the components, so start the backend when a result matters.

### week03/openapi-node-integration

```bash
npm install && cp .env.example .env   # needs a real DEEPSEEK_API_KEY
npm start        # node --env-file=.env src/index.js
npm run dev      # same with --watch
npm test         # node --test
npm run tools    # tool-calling demo against the stub weather service
```

### week02/lottery/claude — Python analysis

```bash
python analysis.py        # -> stats.json; stdlib only, asserts every invariant in the write-up
python make_html.py       # -> heatmap.html, barchart.html
python build_notebook.py  # -> lottery_analysis.ipynb (then nbconvert --execute)
```

The repo-root `.venv` holds the notebook dependencies (`requirements.txt`). `analysis.py` and
`make_html.py` need none of them. `analysis.py` exits non-zero if any asserted invariant moves, so
a change to the CSV cannot silently invalidate the prose.

### week06/RomanEmpireRAG/chunking — chunk-size study (Python)

```bash
cd week06/RomanEmpireRAG/chunking
python chunking.py    # -> out/stats.json, out/volumes_view.json, out/chunks.jsonl.gz
python make_html.py   # -> report.html (result table plus the whole corpus, chunk-coloured)
```

Both are standard-library only. `chunking.py` asserts that the emitted chunks cover 100% of the
corpus and that every volume view neither drops nor repeats a sentence; a segmentation regression
fails the run instead of producing a plausible report. `report.html` is generated, not hand-edited
— change the generators and rebuild.

### week06/RomanEmpireRAG ChromaDB (optional, Python)

```bash
python -m pip install -r week06/RomanEmpireRAG/requirements.txt   # chromadb into the repo-root .venv
python week06/RomanEmpireRAG/ingest.py    # six volumes -> week06/RomanEmpireRAG/chroma (5,772 chunks, ~1 min)
python week06/RomanEmpireRAG/query.py "Why did the Western Empire fall?" -k 3
```

`ingest.py` imports the segmenter from `week06/RomanEmpireRAG/chunking/chunking.py`; the chunks
are identical to `out/chunks.jsonl.gz`. Embeddings are Chroma's local all-MiniLM model (no key).
The store is gitignored, and it is what the Node app retrieves from.
`week06/RomanEmpireRAG/CLAUDE.md` has the details.

### week06/RomanEmpireRAG/rag-app — Roman history RAG (Node + React)

```bash
# once: build the Chroma store the backend reads (it never ingests)
.venv/Scripts/python.exe week06/RomanEmpireRAG/ingest.py

# backend (http://localhost:8788)
cd week06/RomanEmpireRAG/rag-app/backend && npm ci && cp .env.example .env   # key optional
npm start        # node src/index.js
npm test         # 34 tests, no network, key, Python or store

# frontend (http://localhost:5174)
cd week06/RomanEmpireRAG/rag-app/frontend && npm ci
npm run dev
npm test         # 6 tests for the pure highlight helpers
```

Implements `week06/RomanEmpireRAG/specs/ui.md`: question input, read-only answer textarea, ranked
retrieved passages. The backend reads `week06/RomanEmpireRAG/chroma` (the one hard dependency)
through a small Python JSON bridge, and answers through DeepSeek when `DEEPSEEK_API_KEY` is set,
otherwise by quoting the retrieved passages. An upstream failure never becomes a 5xx; a dead
retrieval bridge is a scrubbed 503. `week06/RomanEmpireRAG/CLAUDE.md` has the module map and the
HTTP contract.

### week06/diabetes — diabetes knowledge-base RAG (Node + React)

Same architecture as `week06/RomanEmpireRAG/rag-app`, but the corpus is 12 short structured
Markdown documents, so the retrieval unit is the `##` section (48 chunks), not a character window.
`RETRIEVAL_MODE=section` (default) sends the top-ranked sections; `document` loads every section
of up to `DOC_TOP_K` matched documents (parent-document retrieval). `npm run compare` measures both
on the same questions.

```bash
# once: build the Chroma store the backend reads
python -m pip install -r week06/diabetes/requirements.txt   # chromadb into the repo-root .venv
python week06/diabetes/ingest.py                            # -> week06/diabetes/chroma
python week06/diabetes/query.py "What HbA1c confirms diabetes?" -k 3

# backend (http://localhost:8789)
cd week06/diabetes/rag-app/backend && npm ci && cp .env.example .env   # key optional
npm start        # node scripts/start.js
npm test         # 42 tests, no network, key, Python or store

# frontend (http://localhost:5175)
cd ../frontend && npm ci
npm run dev
npm test         # 6 tests for the pure highlight helpers
```

Sections are embedded with a `Title — Section` / `Topic:` prefix but stored as the plain body, so
retrieval is anchored without changing what the UI quotes. `## References` is skipped. Every
answer surface carries "Educational reference only — not medical advice", and the model prompt
forbids diagnosis and patient-specific advice. `week06/diabetes/README.md` and `CLAUDE.md` have
the details.

## Shared conventions

- **Node >= 20.12**, ESM everywhere (`"type": "module"`). Tests use the built-in `node --test`; no
  Jest/Mocha/Vitest.
- **Env files**: `.env` is gitignored, `.env.example` is the committed template with placeholder
  keys. `openapi-node-integration` loads it via `node --env-file=.env`; `sunset-chaser` uses
  `process.loadEnvFile()` guarded by `existsSync` (see below) instead of `dotenv`.
- **Express 5**, so `path-to-regexp` v8 rejects a bare `*` — catch-all routes must be named
  (`app.use('/{*splat}', ...)`).
- Keys are **optional** in `sunset-chaser`: a missing `WINDY_API_KEY` or `DEEPSEEK_API_KEY` degrades
  to a smaller but valid response rather than an error. The server never returns 5xx because an
  upstream is missing. Preserve that property in new code.

## Architecture: sunset-chaser

The only multi-file application here. Data flows one direction:

```
routes/*  ->  services/chase.js (orchestrator)  ->  solar  ->  sampler  ->  windy  ->  scoring  ->  llm
                                                            \-> fallback (spec step 3)
```

- `services/solar.js` — **the only astronomy in the project**. Wraps `astronomy-engine`; the
  subsolar point is `λ = α − GAST`, and the terminator is exact closed-form geometry (the great
  circle 90° from the subsolar point), not a numerical search. Do not reimplement this arithmetic;
  a hand-rolled version had a 4× unit error in the equation of time. `test/solar.test.js` pins it
  with declination/equation-of-time anchors.
- `services/sampler.js` — places the 20 Windy probes by weighted equal-arc sampling. 20, not the 41
  needed for full coverage: this is a deliberate yield optimisation (missing cameras is acceptable,
  returning bad ones is not). Poleward of 72° is a hard cut.
- `services/scoring.js` — phase buckets, hard filters, weighted score, deterministic reason text.
- `services/fallback.js` — spec step 3, daylight big cities.
- `services/llm.js` — DeepSeek curation. **Model output is untrusted**: every returned `webcamId` is
  checked against the set that was offered, reasons are stripped of control characters and capped,
  and the frontend renders them as text nodes, never HTML.
- `services/chase.js` — orchestrator and the cache keys. Three caches keyed on a coarse **grid of the
  subsolar point**, not on time. The curation cache is keyed on the sweep that produced the
  candidate pool, not on offered candidate ids (ids shift between ranking passes, so that key never
  hits).
- `config.js` reads and validates all env vars with `int()`/`str()` helpers that warn and fall back
  rather than throw — the server is designed to boot with no `.env` at all.
- `app.js` carries a per-request id (`x-request-id`) on every response and logs on `finish`; 5xx
  bodies are scrubbed and reference that id instead of leaking upstream detail.

Antimeridian handling appears in three separate places and all three matter: the backend splits arcs
at ±180, the frontend draws each arc in three world copies, and all longitude math goes through
`longitudeDelta`/`normalize180` — never a raw subtraction.

Frontend: React 19 + React Router 7 + Leaflet, Vite dev server on 5173 proxying `/api` to 8787 (so
there is no CORS preflight locally). Polls every 300 s, paused when the tab is hidden.
