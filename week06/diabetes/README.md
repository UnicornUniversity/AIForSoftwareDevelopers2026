# Diabetes knowledge-base RAG

A retrieval-augmented Q&A layer over the twelve educational documents in
[`data/`](data/). It follows the decisions and module layout of
[`../RomanEmpireRAG`](../RomanEmpireRAG), scaled down to a small structured
corpus.

> **Educational reference only — not medical advice.** The corpus is an
> adaptation of public guidelines (WHO, ADA, NICE), not a clinical decision
> tool. The UI, the extractive answer and the model prompt all repeat this.

## What is here

```
data/                    12 Markdown documents (immutable input)
ingest.py                parse -> section chunks -> ChromaDB (week06/diabetes/chroma)
query.py                 CLI retrieval check
chroma/                  generated store (gitignored)
rag-app/backend/         Express 5 API, Chroma bridge, DeepSeek + extractive answers
rag-app/frontend/        React 19 + Vite single-page UI
```

The corpus is 12 documents, 4 useful sections each: **Overview**, **Key
information**, **Important distinctions / exceptions**, **Examples**. A
`## References` section exists in every file and is deliberately skipped:
bibliography adds no answer context and competes with real passages.

## Quick start

The Chroma store is a hard dependency of the backend; build it once.

```bash
# once, with an interpreter that has chromadb (the repository-root .venv does)
python -m pip install -r week06/diabetes/requirements.txt
python week06/diabetes/ingest.py            # 48 sections -> week06/diabetes/chroma

# backend: http://localhost:8789
cd week06/diabetes/rag-app/backend
npm ci
cp .env.example .env                        # optional; no key means extractive answers
npm start
npm test                                    # 42 tests, no network, no key, no store
npm run compare                             # section vs document retrieval, same questions

# frontend: http://localhost:5175 (proxies /api to 8789)
cd ../frontend
npm ci
npm run dev
npm test                                    # 6 tests for the pure highlight helpers
```

On a Windows checkout the repository venv is
`.venv/Scripts/python.exe`. The backend finds it automatically, along with a
venv under `week06/diabetes` or `week06`; override with `CHROMA_PYTHON`.

Check retrieval without the app:

```bash
python week06/diabetes/query.py "What HbA1c confirms diabetes?"
python week06/diabetes/query.py --doc 12 --section "Key information" -k 3 "metformin"
python week06/diabetes/query.py --json "How is prediabetes defined?"
```

## Chunking decisions

These are load-bearing; changing one changes what the app retrieves.

- **The unit is the `##` section, not a character window.** The Roman corpus is
  one continuous narrative, so a 1,500-character packing with overlap is right
  there. These documents are already structured: a fixed window would cut a
  bullet list in half and mix diagnosis, examples and references. 48 sections
  is the whole corpus.
- **`## References` is skipped** (see above).
- **Markdown is rendered to plain text for retrieval and display.** `**bold**`
  and `*italic*` markers are removed, wrapped prose lines are joined, and bullet
  items get a `•` marker. The wording is unchanged; only syntax is removed.
  Nothing in the UI renders Markdown or HTML.
- **The embedding carries a context prefix, the stored document does not.**
  A section body alone (`Warning signs ... Immediate management ...`) does not
  name its subject, and mean-pooled MiniLM drifts toward whichever bullet
  dominates. Each document is embedded as
  `Title — Section\nTopic: ...\n\n<body>`, while the stored document is the
  body alone, so the UI quotes the source verbatim. `ingest.py` computes the
  embeddings explicitly for this reason.
- **`doc_id`, `title` and `section` are required metadata.** They are what
  `query.py --doc` and the UI filter and label by; a chunk without them fails
  the ingest instead of producing an unfilterable vector.
- **Cosine space**, so the reported score is `1 - distance`.

## Retrieval modes

`RETRIEVAL_MODE` decides how many passages reach the model. Both modes run the
same two steps — rank, then load — at different granularities.

- **`section`** (default) — rank the top `TOP_K` sections and send exactly
  those. The unit that is ranked is the unit that is loaded.
- **`document`** — rank the top `TOP_K` sections, take the documents they
  belong to, and load every section of up to `DOC_TOP_K` of those documents. A
  precise section match selects a document; the model then sees the document's
  full structure. This is parent-document retrieval ("small-to-big"). It is
  still one retrieval round trip: `get_by_doc_ids` is a metadata lookup on the
  same collection, not a second search.

| setting | default | meaning |
|---|---|---|
| `RETRIEVAL_MODE` | `section` | `section` or `document` |
| `TOP_K` | `5` | sections ranked per question |
| `DOC_TOP_K` | `3` | documents expanded in document mode |

Expanded sections carry the matched document's best section score and
`expanded: true`; they are ordered by document match rank, then
`section_index`. A failed expansion degrades to the seed sections rather than
failing the request.

Measured on this corpus with `npm run compare` (four questions, `TOP_K=5`,
`DOC_TOP_K=3`):

| mode | documents | sections | passage chars | ~prompt tokens | retrieval |
|---|---|---|---|---|---|
| section | 12 | 20 | 17,959 | 5,632 | 441 ms |
| document | 10 | 40 | 35,202 | 10,188 | 443 ms |

Document mode roughly doubles the context — 1.96× passage text, 1.81× prompt
tokens — for about the same retrieval time. Whether that trade is worth it
depends on the corpus: these sections are already self-contained, which is why
`section` is the default here. The Roman corpus is the case where the parent
matters, and it uses character windows instead.

```bash
cd week06/diabetes/rag-app/backend
npm run compare                            # both modes, four fixed questions
npm run compare -- "How is DKA managed?"   # your own question(s)
npm run compare -- --k 5 --docs 3 --show-chunks
npm run compare -- --answer                # also generate answers (slow; needs a key)
node scripts/compare-retrieval.js --json   # clean JSON (npm prints a banner)
```

`--answer` calls the model twice per question. On this machine a DeepSeek call
has been measured at 13–46 s and may fail; it falls back to the extractive
answer. The default comparison measures retrieval and prompt size only.

## HTTP contract

- `GET /api/health` →
  `{ok, service, disclaimer, corpus:{chunks,documents,sections,characters},
  retrieval:{backend:"chromadb",collection,metric,mode,documentTopK},
  answer:{mode,hasLlmKey,model}, uptimeSeconds}`
- `POST /api/ask` body `{"question": "..."}` →
  `{requestId, question, answer, answerSource:"deepseek"|"extractive"|"none",
  disclaimer, llm:{model,error,cause,note,finishReason,latencyMs}|null,
  retrieval:{mode:"section"|"document",documents,expanded,latencyMs,candidates,
  returned,matchedTerms},
  chunks:[{rank,id,docId,docNumber,title,section,topic,source,score,chars,
  matchedTerms,expanded,text}], timing:{totalMs}}`

`retrieval.documents` is the number of distinct documents represented in
`chunks`; `retrieval.expanded` is true only when document expansion actually
ran (a failed lookup falls back to the seed sections and reports false).
- 400 `question_required` / `question_too_long`; 404 `not_found`; a dead bridge
  is a scrubbed 503 `retrieval_unavailable`; other 5xx bodies reference the
  request id. Questions are capped at 500 characters, the JSON body at 16 KB.

## Answer modes

`DEEPSEEK_API_KEY` is optional. With a key and `ANSWER_MODE=auto`, DeepSeek
writes the answer from the retrieved sections; a missing key, timeout, rate
limit, TLS interception or unusable reply falls back to an extractive answer
that quotes the passages and states why no model answer exists. Model output is
sanitised and rendered as text only. The server never returns 5xx because an
upstream is missing.

`npm start` uses `scripts/start.js`, which adds `--use-system-ca` on Node >= 24
so a TLS-inspecting antivirus or proxy does not force the extractive fallback.

## Tests

- `rag-app/backend/test/*.test.js` — 42 tests on a fixture corpus, a fake
  line-protocol bridge and a scripted OpenAI client. No network, key, Python or
  ChromaDB needed. `retrieval.test.js` covers both retrieval modes and the
  expansion-failure fallback.
- `rag-app/frontend/test/highlight.test.js` — 6 tests on the pure highlight
  helpers via `node --test`.

`ingest.py` fails rather than emitting a plausible store if a document has no
title or topic, a section is empty, or two sections would produce the same
chunk id. The run prints the per-document section count so a parsing regression
is visible.
