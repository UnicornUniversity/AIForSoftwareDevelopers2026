# Chunking Gibbon's *Decline and Fall*

How to cut the six volumes in [`../data`](../data) into retrieval units, following
[`../specs/chunks1.md`](../specs/chunks1.md).

**Recommendation: chunks targeting 1,500 characters (~375 tokens) with 100 characters
(~25 requested, ~55 realised) of overlap, on paragraph and sentence boundaries.**

The optimum is flat: everything between 1,200 and 1,800 characters scores within 1% of the
winner, so an operational constraint may legitimately pick another point in that range.

## Deliverables

| file | what it is |
|---|---|
| [`report.html`](report.html) | the standalone report: corpus table, sweep heatmap, full result table, sample chunks, method, and every volume in full with chunk and overlap backgrounds. No network, no scripts — open it by double-click |
| [`chunking.py`](chunking.py) | segmentation, chunking, the parameter sweep and every statistic; standard library only |
| [`make_html.py`](make_html.py) | renders `out/stats.json` into the report |
| [`out/stats.json`](out/stats.json) | generated — every number the report shows |
| [`out/chunks.jsonl.gz`](out/chunks.jsonl.gz) | generated — the 5,772 chunks at the recommended parameters, one JSON object per line |
| [`out/volumes_view.json`](out/volumes_view.json) | generated — every sentence of all six volumes tagged with its chunk and overlap status; drives the full-text section of the report |

## Reproducing

```bash
cd week06/chunking
python chunking.py      # -> out/stats.json, out/chunks.jsonl.gz
python make_html.py     # -> report.html
```

Run both in that order: `chunking.py` writes the stats the report is built from. The split takes
a few seconds and needs nothing beyond the standard library.

Useful flags: `--explain` prints what the segmenter decided for each volume and the first
paragraph it kept; `--no-chunks` skips the 3 MB chunk file.

## Reading the full-text view

Section 8 of the report prints all six volumes in reading order, with every sentence
carrying the background of the chunk that owns it. The two blue tints alternate from chunk
to chunk, so a change of tint is a boundary; a blue rule marks the first sentence of each
chunk. The amber band is the overlap — sentences that close one chunk and open the next.
They are shown once, tinted as overlap rather than as either neighbour, so the page does
not repeat the 14% of the corpus that overlap copies. Chunks never cross a chapter
heading, so every section starts a fresh chunk with no carry-over. Each volume has its
own jump strip, and a volume selector sits above the text.

## How the parameters were chosen

1. **Paragraphs.** Blank lines delimit paragraphs; the first block after a chapter heading is
   its synopsis and is attached to the heading instead of being chunked. Median paragraph:
   423 characters, P90: 3,576 — heavily skewed, so neither the mean nor the median is a good
   target on its own.
2. **Sentences.** Paragraphs are split into sentences (abbreviation-aware: `St.`, `M.`,
   `A.D.`, `i.e.` do not end a sentence). The median sentence is 123 characters, which makes
   sentence-level boundaries a fine-grained, cheap fallback.
3. **Sweep.** Ten targets x five overlaps, 39 configurations after the overlap cap.
   Packing prefers whole paragraphs and closes at a sentence. Overlap is carried in whole
   sentences from the previous chunk, never across a chapter break.
4. **Score.** 35% size stability (share within ±20% of target), 25% single-paragraph chunks,
   20% restored context (chunks opening on a pronoun whose antecedent is carried in), 20%
   inverse overlap cost. The weights are a judgement; the metrics are measured.
5. **Constraints.** The target plus the ~110-character heading prefix must fit a 512-token
   embedding window (2,048 characters at the chars/4 estimate), and overlap may not exceed
   20% of the target.

Token counts are estimates (chars/4, cross-checked against words/0.75) because no tokenizer is
vendored.

## Data quirks handled

- Volumes 1 and 3 label their contents `CONTENTS`; volume 2 has a table of contents with no
  label at all. The body is located by structure — the first heading followed within two
  blocks by a paragraph over 1,000 characters — not by a marker.
- Paragraph indentation differs per volume (six spaces, flush, five spaces for synopses), so
  classification uses the opening words and block length, never indentation.
- The edition interleaves Gibbon's and Milman's footnotes with the prose. They are left in
  the chunks; a production pipeline would strip or tag them.
