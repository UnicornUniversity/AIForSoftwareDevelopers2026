# Semantic chunking of Gibbon's *Decline and Fall*

A study of where to cut the six Project Gutenberg volumes of *The History of the Decline and Fall
of the Roman Empire* so that each chunk is both small enough for a 512-token retrieval window and
semantically coherent. The deliverable is a runnable pipeline, a measured comparison against
size-only baselines, and [`report.html`](report.html), a standalone report with the full corpus
coloured by chunk.

This folder is a separate answer from the stdlib-only size study in [`../chunking/`](../chunking/).
That study asks *how large* a chunk should be; this one asks *where* the cut belongs. The two are
not meant to converge, and changes here are deliberately not propagated there.

## Recommendation

| Parameter | Value | Why |
|---|---|---|
| Target | **1,500 chars** (~375 tokens) | Centre of the size plateau; matches the sibling study's operational target. |
| Hard bounds | **500–1,900 content chars** | A chunk below 500 is only a chapter tail; overlap is trimmed whenever content plus overlap would push the chunk past 1,938 chars, leaving room for the ~110-char breadcrumb inside 2,048. |
| Overlap | **one whole sentence** (≈137 chars, 10.9% measured) | Repairs a chunk opening on a pronoun; never splits a sentence. |
| Percentile floor | **none, q = 0** | The size constraints already choose a boundary. A floor removes good candidates and forces bad ones. |
| Probe buffer | **0** | Sentence-to-sentence distance; a wider window was not better on this corpus. |
| Boundaries | **chapter walls are absolute** | Merging across a heading is wrong regardless of vector similarity. |

Measured on all six volumes (57,364 sentences, 7,879,852 chars, 300 chapters):

| Result | Value |
|---|---|
| Chunks | **6,313** |
| Mean / median chars | 1,393.9 / 1,471 |
| In 500–2,000 chars | 99.8% |
| Over the 2,048-char embedding window | 0.0% |
| Boundary contrast z | **+0.923** |
| Cuts that are a local similarity dip | **98.4%** |
| Paragraph alignment | 8.6% |
| Overlap | 10.9% |
| Composite score | **0.714** |

The baselines are clearly worse: fixed-size sentence packing scores 0.535 and paragraph packing
0.551. Their cuts have *negative* contrast — they land slightly below the average semantic change —
and their local-dip accuracy is 46.8% and 44.2%, a coin flip. The full comparison is in
[`report.html`](report.html) and in `out/stats.json` under `baselines`.

## The mechanism

```
data/*.txt
  -> structure pass        body, headings, paragraphs, sentence stream
  -> sentence embeddings   spaCy en_core_web_lg, SIF-weighted, centred, L2-normalised
  -> context probes        mean vector in a window around each sentence
  -> boundary distances    cosine distance between consecutive probes
  -> constrained packing   strongest legal candidate in each [min, max] window
  -> whole-sentence overlap
  -> chunks.jsonl.gz + stats.json + volumes_view.json
  -> make_html.py -> report.html
```

### 1. Structure is a prior, not a guess

The parser strips the Gutenberg licence, finds the body by the first heading followed within two
blocks by a paragraph longer than 1,000 characters, and separates headings and their one-block
synopses from prose. Sentence splitting is abbreviation-aware (`St.`, `A.D.`, `i.e.`, initials,
and a long Latin/English list must not end a sentence). The result is a stream of sentence objects
with stable volume, chapter, paragraph, and paragraph-start flags.

This pass is deliberately not semantic. It defines the units the embedder is allowed to see, and it
is the only place chapter walls are created.

### 2. Embedding, with the arithmetic that makes cosine meaningful

The default backend is spaCy's `en_core_web_lg` static 300-d vectors:

- each word is weighted by smooth inverse frequency, `a / (a + p(word))` with `a = 1e-3`;
- sentence vectors are the weighted mean of their word vectors;
- the whole matrix is **mean-centred**;
- the first principal component is projected out (the SIF post-processing);
- every row is L2-normalised.

Centring is load-bearing. Uncentred static vectors sit in a narrow cone: every pair of sentences
looks about 0.93 similar, distances are compressed, and boundary contrast is flat. Centring made
the measured contrast rise from 0.372 to 0.509 on volume 1 and produced distances that can be read
as "different" versus "similar". The cache key carries a `-c1` suffix so an old, uncentred cache
cannot be reused silently.

### 3. Compare context, then cut

For sentence *i*, the probe is the L2-normalised mean of the sentence vectors in a window of
`buffer` sentences on either side. The boundary distance between sentences *i-1* and *i* is the
cosine distance between their probes:

```
probe(i) = normalize( mean( v[i-b] … v[i+b] ) )
d(i)     = 1 − cos( probe(i−1), probe(i) )
```

With `b = 0` the probe is the sentence itself. A positive buffer smooths over one unusual sentence;
on this corpus it did not improve the score, so the recommendation is 0.

### 4. Choose under hard constraints

For each chapter independently:

```
floor(c)      = percentile( { d(i) : i in chapter c }, q )
candidate(i)  = d(i) ≥ floor(c)

low  = first position with ≥ 500 chars from the current start
high = last position with ≤ 1,900 chars from the current start

choose = argmax over i in [low, high] of
           d(i)
         + 0.03 · [sentence i starts a paragraph]
         − 0.03 · |chars(start..i) − 1500| / 1500
```

If no candidate exists in the window, the packer falls back to the legal paragraph start nearest
the target size, or the legal position nearest the target. A single sentence longer than 1,900
chars is allowed to oversize; the hard cap yields to the fact that sentences cannot be split.

The paragraph bonus breaks ties; it does not overrule the vectors. The size penalty is small for the
same reason. Both are visible constants in `segmenter.py`, not hidden heuristics.

### 5. Overlap in whole sentences

The previous chunk's final sentence is carried into the next chunk, capped by `overlap_chars`
(0 means no cap). Overlap never crosses a chapter heading and never splits a sentence. The total
chunk text, including overlap and a ~110-char chapter breadcrumb, must stay at or below 2,048 chars
— the chars/4 estimate of a 512-token embedding window. `validate_chunks` fails the run otherwise.

### Why q = 0, not q = 95

The standard recipe (Kamradt, LlamaIndex's default) sets a high percentile floor so only strong
semantic breaks become cuts. That recipe assumes chunk size is free. Here it is not: the 1,900-char
ceiling forces a cut every few paragraphs whether or not a strong break exists. When the floor
rejects every position in the legal window, the packer cuts somewhere the model did not endorse.

Measured at min 500 / max 1,900 / buffer 0:

| Floor | Chunks | Contrast z | Cuts below own floor | Composite |
|---|---:|---:|---:|---:|
| none (q=0) | 6,313 | +0.923 | **0.0%** | **0.6088** |
| q60 | 6,237 | +0.871 | 11.3% | 0.6047 |
| q70 | 6,183 | +0.811 | 20.8% | 0.6009 |
| q80 | 6,089 | +0.704 | 35.8% | 0.5950 |
| q90 | 5,969 | +0.510 | 57.9% | 0.5834 |
| q95 | 5,879 | +0.346 | **71.9%** | 0.5755 |

At q = 95 nearly three quarters of the cuts are below the floor the configuration itself declared.
The floor is not selecting boundaries; it is removing candidates and leaving the size constraint to
place the cut. Lowering the floor lets the same packer choose the strongest available boundary in
each window. This is the central empirical finding of the study.

The q = 0 row is 0% *by construction*: its threshold is the minimum of the chapter's distances, so
nothing can fall below it. The informative rows are q60–q95, where every added floor point raises
the share of cuts the floor itself rejects.

The recommendation is a plateau, not a point: 13 configurations are within 0.02 of the best
composite, spanning floors 0/60/70/80, buffers 0/1, minimums 500/700, and maximums 1,700/1,900.
An operational constraint may legitimately pick another point.

## Backends

| Backend | Dependency | Key | Notes |
|---|---|---|---|
| `spacy` (default) | `spacy`, `numpy`, `en_core_web_lg` | none | 300-d static vectors, SIF, ~66 MB dense cache for the full corpus |
| `tfidf` | none (standard library) | none | Sparse unigram + bigram TF-IDF; lexical proxy, fully offline |
| `st` | `sentence-transformers` | none | Contextual transformer embeddings; model downloads on first use |

`--backend auto` picks spaCy when importable and falls back to TF-IDF otherwise. DeepSeek is
**not** an embedding backend: its public API exposes chat completions, not an embeddings endpoint.

## DeepSeek (optional)

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY`. The key is optional; with no `.env` the
pipeline runs fully offline. DeepSeek is used only where a language model beats a vector:

| Stage | Flag | Output |
|---|---|---|
| Boundary adjudication | `--deepseek-verify N` | `out/deepseek_verify.json` — agreement rate and judged samples |
| Chunk labels | `--deepseek-label` | `out/chunk_labels.jsonl` — 3–8 word topic + one-sentence summary |
| Retrieval questions | `--deepseek-questions N` | `out/questions.jsonl` — one answerable question per sampled chunk |

```bash
python semantic_chunking.py --deepseek-verify 24 --deepseek-label --deepseek-questions 24
```

All stages are sampled (`DEEPSEEK_MAX_ITEMS`, default 40) and opt-in, so a full run stays
affordable. A missing key, timeout, or malformed reply is recorded in `stats.json` and never
aborts chunking. Model output is untrusted: returned chunk ids are checked against the offered
set, labels and reasons are control-character stripped and length-capped, and the report renders
them as text nodes, never HTML.

Boundary verdicts are **advisory**. The pipeline records agreement and does not re-segment on
them: doing so would make the chunk set depend on an optional, non-deterministic model call.

## LlamaIndex (optional alternative)

`llamaindex_pipeline.py` runs the reference implementation of the same splitter family —
`SemanticSplitterNodeParser` — over one `Document` per chapter, and writes a comparable chunk file.

```bash
python -m pip install "llama-index-core>=0.12" "llama-index-embeddings-huggingface>=0.4"
python llamaindex_pipeline.py --backend huggingface     # local BAAI/bge-small-en-v1.5
```

Outputs: `out/llamaindex_chunks.jsonl.gz` and `out/llamaindex_stats.json`. The report picks them up
automatically on the next `make_html.py` run. LlamaIndex exposes no per-boundary distances, so the
report leaves contrast and separation blank for its row rather than estimating them. Its parser is
also not size-constrained the way this pipeline is; it is a reference point, not a drop-in
replacement.

## Running it

From this directory:

```bash
# one-time, optional: the spaCy backend
python -m pip install -r requirements-optional.txt
python -m spacy download en_core_web_lg

# full corpus, default sweep, report
python semantic_chunking.py
python make_html.py

# one fixed configuration, no sweep
python semantic_chunking.py --no-sweep --percentile 0 --buffer 0 \
    --min-chars 500 --max-chars 1900

# no optional dependencies at all
python semantic_chunking.py --backend tfidf

# development: one volume, separate output directory
python semantic_chunking.py --limit 1 --out out-dev
```

The first spaCy run embeds all 57,364 sentences and writes `out/cache/*.npy` (~66 MB). Repeat runs
load that cache; a full 108-configuration sweep then finishes in seconds. `--refresh-cache`
recomputes embeddings. The cache is gitignored because it is regenerable.

`python corpus.py` prints the parsed corpus summary without embedding anything.

## Outputs

### `out/stats.json`

| Key | Contents |
|---|---|
| `backend` | Backend name, model, dimensions, weighting |
| `corpus` | Volume/chapter/paragraph/sentence counts, size percentiles, per-volume counts |
| `method`, `constraints` | The effective parameters and the 512-token window arithmetic |
| `sweep` | All 108 configurations with cheap metrics |
| `best` | Winning configuration and exact metrics |
| `plateau` | Configurations within 0.02 of the best |
| `baselines` | Fixed-size and paragraph packing, measured identically |
| `per_volume` | Chunk count, size, contrast, separation, alignment per volume |
| `chunk_histogram` | Size distribution |
| `samples`, `boundary_samples` | Three sample chunks and the eight strongest boundaries |
| `deepseek` | Status of the optional stages |

### `out/chunks.jsonl.gz`

One JSON object per line. The fields used by `rag-app` are present with the same names and meanings:
`id`, `volume`, `chapter`, `chars`, `words`, `tokens`, `paragraph_from`, `paragraph_to`,
`overlap_chars`, `text`. Semantic extras: `chapter_id`, `chapter_heading`, `content_chars`,
`sentence_count`, `boundary_distance`, `threshold`, `backend`.

This corpus is not wired into the RAG app. The app retrieves from the ChromaDB store built by
`../ingest.py`, which imports the sibling size study's segmenter; the backend has no
`CHUNKS_PATH` switch. To compare the corpora in retrieval, build a separate Chroma collection
from this `chunks.jsonl.gz` and point `CHROMA_DB` / `CHROMA_COLLECTION` at it. The two corpora
have different ids and chunk boundaries, so do not mix them in one index.

### `out/volumes_view.json`

Every sentence exactly once, tagged with its owning chunk, chunk index, overlap flag, and
paragraph-start flag. The report's full-text view is rendered from this file. A sentence that is
carried into the next chunk's text appears once here, flagged `overlap`.

### `report.html`

Standalone, no JavaScript, no network. It embeds the whole corpus, so it is ~11 MB; Volume 1 is
open and the other volumes are collapsed. Regenerate it after any change to `stats.json` or
`volumes_view.json`.

## Metrics

| Metric | Definition | Why it is measured this way |
|---|---|---|
| `in_band_pct` | Share of chunks with 500–2,000 chars | The size constraint is a hard part of the problem. |
| `over_window_pct` | Share above 2,048 chars | Must be 0; the retrieval window is a hard failure, not a preference. |
| `contrast_z` | `(mean distance at cuts − mean distance over all adjacent pairs) / stdev` | Positive means cuts land at above-average semantic change. Measured on the same vector field for every strategy. |
| `separation_drop` | Mean cosine of adjacent pairs inside a chunk minus mean cosine across a cut | A local comparison. Random within-chunk pairs would always favour large chunks. |
| `separation_accuracy_pct` | Share of cuts whose cross-boundary pair is less similar than the adjacent pairs just inside each side | A boundary is a *local dip*, not just a low similarity. Sampled 800 chunks / 24,130 pairs. |
| `paragraph_alignment_pct` | Share of cuts at a paragraph start | Structural agreement, not a quality score. Semantic cuts can legitimately be mid-paragraph. |
| `overlap_pct` | Overlap chars / content chars | Context has a cost; it is scored inversely. |
| `reference_with_overlap_pct` | Of chunks opening on a reference-bearing word (pronoun, "this", "thus", …), share that received overlap | Measures whether overlap actually repairs dangling references. |
| `composite` | 30% in-band + 25% contrast (capped at z=2) + 20% separation accuracy + 15% paragraph alignment + 10% inverse overlap | A stated judgement. The measured components are in the same table so the weights can be argued with. |

Two tempting metrics were tested and rejected:

- **Leave-one-out nearest-chunk retrieval** ranked semantic chunking *below* the baselines
  (32.9% vs 36.1%). The own-chunk centroid is noisy and neighbouring chunks share topic, so the
  metric measured neighbour similarity rather than boundary quality. It was removed.
- **Random within-chunk vs adjacent cross-boundary cosine** is unfair by construction: adjacent
  pairs are always more similar than random pairs, wherever they sit. It was replaced by the local
  dip test above.

## Invariants

The run fails rather than emitting a plausible report if:

- a chapter produces no chunks, or a chunk is empty;
- chunks do not start at sentence 0, end at the last sentence, or leave a gap/overlap in coverage;
- overlap crosses into a chunk's content;
- a chunk, including overlap, exceeds the 2,048-char embedding window;
- the volume view drops or repeats a sentence (checked while building it).

`validate_chunks` is called per volume inside `semantic_chunking.py`; there is no separate test
runner, matching the repository's stdlib-first convention.

## Files

| File | Role |
|---|---|
| `corpus.py` | Gutenberg parsing: body, headings, paragraphs, abbreviation-aware sentences |
| `embedders.py` | TF-IDF, spaCy/SIF, sentence-transformers; vector helpers; dense cache |
| `segmenter.py` | Probe distances, semantic/fixed/paragraph ranges, chunk construction, metrics |
| `semantic_chunking.py` | CLI, sweep, baselines, output writers |
| `deepseek.py` | Optional boundary adjudication, labels, question generation (stdlib urllib) |
| `llamaindex_pipeline.py` | Optional reference implementation via LlamaIndex |
| `make_html.py` | Standalone report renderer |
| `envfile.py` | Minimal stdlib `.env` reader |
| `.env.example` | Committed template; placeholders only, no secrets |
| `requirements-optional.txt` | spaCy, numpy, sentence-transformers, LlamaIndex |
| `report.html` | Generated report (~11 MB) |

## Limitations

- **Static vectors, not contextual.** spaCy's vectors average word meanings; they do not
  disambiguate by sentence. `--backend st` is the first thing to try for production.
- **Intrinsic metrics only.** They measure boundary quality, not retrieval answer quality. A real
  evaluation needs labelled questions; the DeepSeek pass generates candidates, not gold labels.
- **Footnotes stay in.** Editorial notes are interleaved with prose and are treated as sentences.
  Removing them is a separate cleaning decision that would change the corpus.
- **Paragraph alignment is deliberately low** (8.6% vs 64% for paragraph packing). A reader who
  needs paragraph-pure chunks should use the paragraph baseline and accept the size spread.
- **Chapter walls are a prior.** The study does not test whether a detector would find them alone.
- **Token counts are estimates** at 4 chars/token. No tokenizer is vendored; 2,048 chars is a
  conservative proxy for 512 tokens.
