# CLAUDE.md — week06/diabetes

Guidance for Claude Code when working in this folder. The repository-root
`CLAUDE.md` still applies. This project is a scaled-down port of
[`../RomanEmpireRAG`](../RomanEmpireRAG); its `CLAUDE.md` is the reference for
the shared RAG architecture.

## What this is

A retrieval-augmented Q&A layer over the twelve Markdown documents in `data/`.
Three pieces, one generated artefact (`chroma/`):

| piece | path | role |
|---|---|---|
| ingestion | `ingest.py` | parse `data/*.md` into section chunks, embed, write ChromaDB |
| retrieval check | `query.py` | CLI over the same collection |
| app | `rag-app/backend`, `rag-app/frontend` | Express API + React UI |

The corpus is educational material adapted from WHO/ADA/NICE guidance. **Never
present its output as medical advice**; every answer surface carries the
disclaimer, and the model prompt forbids diagnosis and patient-specific advice.

## Commands

```bash
# store (once; repository-root .venv already has chromadb)
python week06/diabetes/ingest.py
python week06/diabetes/ingest.py --stats
python week06/diabetes/ingest.py --append
python week06/diabetes/query.py "What HbA1c confirms diabetes?" -k 3

# backend: http://localhost:8789
cd week06/diabetes/rag-app/backend
npm ci && cp .env.example .env    # .env optional
npm start                         # node scripts/start.js
npm test                          # 42 tests
npm run compare                   # section vs document retrieval, same questions

# frontend: http://localhost:5175, proxies /api to 8789
cd ../frontend
npm ci
npm run dev
npm test                          # 6 tests
npm run build                     # -> dist/
```

On Windows use `.venv/Scripts/python.exe`. `config.js` finds the repository
venv automatically; `CHROMA_PYTHON` overrides it.

## Architecture

```
data/*.md -> ingest.parse_document -> plain_text -> chunks
                                                    |
                              embedding_text -> Chroma (cosine, "diabetes")
                                                    |
                          query.py  <-  bridge/chroma_bridge.py  <- chroma.js
                                                    |
                                    retrieval.js (section | document)
                                                    |
                              app.js /api/ask -> answerer -> llm | extractive
```

Module map of the backend (all files under `rag-app/backend/src/`):

- `config.js` — env parsing; `int()`/`str()` warn and fall back, so the service
  boots with no `.env`. Port 8789, collection `diabetes`, `TOP_K=5`.
- `chroma.js` — one long-lived Python child, one JSON request per line, pending
  requests matched by id and bounded by `CHROMA_TIMEOUT_MS`. Maps Chroma rows to
  `{chunk:{id,docId,docNumber,title,section,sectionIndex,topic,source,text},
  score, rank, matchedTerms}` with `score = 1 - distance` clamped at zero.
  `getByDocIds` is the document-lookup half of document mode; its rows have no
  distance, so they score 0 until `retrieval.js` substitutes the document's.
- `retrieval.js` — the policy layer (`createRetrieval().retrieve`). `section`
  passes the ranked sections through; `document` expands up to `DOC_TOP_K`
  matched documents. A failed expansion falls back to the seeds, so expansion
  can never turn a good answer into a 5xx.
- `bridge/chroma_bridge.py` — reader only; emits `ready` with corpus counts,
  then answers `search` (default) and `get_by_doc_ids` requests. Stdout is
  protocol only.
- `services/llm.js` — DeepSeek via the OpenAI SDK. Never throws; every failure
  is a code, with the socket `cause` preserved for TLS diagnosis. The system
  prompt restricts answers to the passages, requires `[n]` citations, and
  forbids diagnosis/prescribing/patient-specific advice.
- `services/extractive.js` — the no-model answer; quotes retrieved sentences and
  states why there is no synthesised answer, plus the disclaimer.
- `services/answerer.js` — mode selection and fallback.
- `app.js` — `createApp({retriever, answerer, config, logger})`; request ids,
  scrubbed 5xx, Express 5 named catch-all `/{*splat}`.
- `index.js` — starts the bridge first (the one hard dependency), listens on
  8789, tears the bridge down on exit.

## Decisions that must not be quietly changed

- **Chunk by `##` section.** 48 chunks from 12 documents; `## References` is
  skipped. A fixed-size window would cut these short structured documents apart.
- **Embed with context, store without it.** `embedding_text()` prepends
  `Title — Section` and `Topic:` for the vector; `documents=` stores the body
  only. The embeddings are passed explicitly to `upsert`; re-embedding without
  the prefix silently degrades retrieval.
- **Plain text, not Markdown.** `plain_text()` strips emphasis markers and
  joins wrapped lines; `**` must never reach the UI or the vector.
- **Required metadata.** `doc_id`, `title`, `section` fail the ingest when
  absent. `query.py --doc` uses `doc_id`/`doc_number` natively; `--section` is a
  case-insensitive substring applied after retrieval (Chroma has no `$contains`
  on string metadata here), which is why it fetches all candidates.
- **The backend reads the store; it never ingests.** Rebuilding the collection
  while the backend runs invalidates the bridge; restart it after an ingest.
- **Keys are optional and upstream failures are not 5xx.** A missing key, slow
  proxy or TLS interception degrades to the extractive answer.
- **Retrieval granularity is a mode, not a rewrite.** `RETRIEVAL_MODE=section`
  (default) loads exactly the ranked sections; `document` loads every section
  of up to `DOC_TOP_K` matched documents. Expanded passages carry the matched
  document's best seed score and `expanded: true` — they were not ranked
  themselves, so do not present that score as a section similarity. Expansion
  failure must keep the seed results and report `expanded: false`.
- **Model output is untrusted.** Sanitised server-side, rendered as a textarea
  value / text nodes; no `dangerouslySetInnerHTML` anywhere.

## Tests

`node --test` only (no Jest/Vitest). Backend tests use `test/fixtures.js` and a
`FakeBridge` that speaks the real line protocol, so they need neither Python nor
the store. Frontend tests cover `src/lib/highlight.js` directly.

Generated paths (`chroma/`, `node_modules/`, `dist/`) are gitignored and are
rebuilt, never edited. `data/` is immutable input.
