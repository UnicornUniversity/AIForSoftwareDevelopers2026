# Roman Empire RAG

A retrieval-augmented Q&A application over Edward Gibbon's *The History of the Decline
and Fall of the Roman Empire* (six volumes, 5,772 passages), plus the two studies that
produced its corpus.

| folder | what it is | spec |
|---|---|---|
| [`chunking/`](chunking/) | Size study: how large a chunk should be. Produces the chunk set the app retrieves | [`specs/chunks1.md`](specs/chunks1.md) |
| `ingest.py`, `query.py`, [`rag-app/`](rag-app/) | ChromaDB ingestion and the Express + React app that answers questions over it | [`specs/ui.md`](specs/ui.md) |
| [`semantic-chunking/`](semantic-chunking/) | Additional study: *where* to cut, by embedding-distance boundaries. Not wired into the app | — |

```
Browser (React + Vite, :5174) ──/api──> Express (:8788) ──JSON lines──> Python bridge
                                          ├─ ChromaDB vector search          └─ chroma/
                                          ├─ DeepSeek answer synthesis   (if a key is set)
                                          └─ extractive quoted answer    (otherwise)
```

The answer is synthesised by DeepSeek when `DEEPSEEK_API_KEY` is configured; with no key,
or on any model failure, the service quotes the retrieved passages instead. Retrieval
itself is local (Chroma's all-MiniLM-L6-v2 embeddings) and needs no key or network.

## Quick start

The Chroma store is built once by a separate command — the backend only reads it.

```bash
# from the repository root, with a Python that has chromadb (the repo-root .venv does)
python -m pip install -r week06/RomanEmpireRAG/requirements.txt
python week06/RomanEmpireRAG/ingest.py        # 5,772 chunks -> week06/RomanEmpireRAG/chroma

# backend: http://localhost:8788
cd week06/RomanEmpireRAG/rag-app/backend
npm ci
cp .env.example .env                          # optional; no key means extractive answers
npm start

# frontend: http://localhost:5174 (proxies /api to 8788)
cd ../frontend
npm ci
npm run dev
```

Open <http://localhost:5174>. `?q=...` opens the page on a question, e.g.
<http://localhost:5174/?q=Who+was+Belisarius%3F>.

On Windows use `.venv/Scripts/python.exe` for the Python steps. If the interpreter with
`chromadb` is not the repo-root `.venv`, set `CHROMA_PYTHON` to it — the backend spawns
the store bridge with that interpreter.

Check retrieval without the app:

```bash
python week06/RomanEmpireRAG/query.py "Why did the Western Empire fall?" -k 3
python week06/RomanEmpireRAG/query.py --volume 4 "Who was Belisarius?"
python week06/RomanEmpireRAG/query.py --json "Who was Belisarius?"
```

## The chunking study

[`chunking/README.md`](chunking/README.md) is the full write-up. The recommendation is
1,500-character targets (~375 tokens) with 100 characters of requested overlap, on
paragraph and sentence boundaries; everything from 1,200 to 1,800 characters scores within
1% of the best, so the recommendation is a plateau rather than a single point.

```bash
cd week06/RomanEmpireRAG/chunking
python chunking.py        # -> out/stats.json, out/volumes_view.json, out/chunks.jsonl.gz
python make_html.py       # -> report.html
```

Both are standard-library only. `report.html` is generated — change the generators and
rebuild it, never hand-edit the HTML.

## How the pieces connect

`ingest.py` imports the segmentation from `chunking/chunking.py` and refuses to embed
chunks that differ from `chunking/out/chunks.jsonl.gz`, so the vectors cover exactly the
chunks the study analysed. Regenerating the chunks changes what the app retrieves: re-run
the ingest and restart the backend afterwards.

`semantic-chunking/` is deliberately separate. It answers a different question, uses
different ids and boundaries, and is not read by the app or by `ingest.py`.

## Tests

```bash
cd week06/RomanEmpireRAG/rag-app/backend && npm test    # 34 tests
cd week06/RomanEmpireRAG/rag-app/frontend && npm test   # 6 tests
```

Backend tests use a fixture corpus, a fake line-protocol bridge and a scripted OpenAI
client: no network, API key, Python or ChromaDB needed. Frontend tests cover the pure
highlight helpers.

## Configuration

Everything is optional except the store; `rag-app/backend/.env.example` documents every
value. The ones worth knowing:

| variable | default | effect |
|---|---|---|
| `DEEPSEEK_API_KEY` | empty | absent → extractive answers |
| `ANSWER_MODE` | `auto` | `extractive` never calls the model |
| `CHROMA_DB` | `../../chroma` (from the backend) | the store built by `ingest.py` |
| `CHROMA_COLLECTION` | `gibbon` | collection name |
| `CHROMA_PYTHON` | detected venv | interpreter with `chromadb` |
| `TOP_K` | `6` | passages retrieved per question |

`npm start` uses `scripts/start.js`, which adds `--use-system-ca` on Node >= 24 so a
TLS-inspecting antivirus or corporate proxy does not force the extractive fallback.

## Generated artefacts

`chunking/out/*`, `chunking/report.html` and `chroma/` are rebuilt, not edited. `data/`
holds the six Project Gutenberg volumes and is immutable input. The store and
`node_modules/` are gitignored.

## More detail

- [`CLAUDE.md`](CLAUDE.md) — architecture, module map, decisions and invariants.
- [`chunking/README.md`](chunking/README.md) — how chunk sizes were chosen and measured.
- [`rag-app/README.md`](rag-app/README.md) — the app's behaviour, API and answer modes.
- [`semantic-chunking/README.md`](semantic-chunking/README.md) — the boundary study.
- [`specs/`](specs/) — the two assignment specifications.
