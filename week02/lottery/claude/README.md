# Eurojackpot analysis

An analysis of the 821 Eurojackpot draws in `eurojackpot.csv` (10 Oct 2014 – 12 May 2026),
answering the tasks in [`../spec.md`](../spec.md).

**Headline finding:** the draws are consistent with a fair uniform random process, and no model
built on this history predicts them. The one large apparent anomaly in the data — Set #2 numbers
11 and 12 looking drastically cold, significant at p < 10⁻¹² — is an artefact of a rule change on
25 March 2022 and vanishes once the two eras are separated.

Read [`lottery_analysis.md`](lottery_analysis.md) for the full write-up.

## Deliverables

| file | what it is |
|---|---|
| [`lottery_analysis.md`](lottery_analysis.md) | the written analysis |
| [`lottery_analysis.ipynb`](lottery_analysis.ipynb) | the same analysis as an executed notebook |
| [`heatmap.html`](heatmap.html) | two D3 heatmaps — Set #1 as a 5×10 grid, Set #2 as 2×6 |
| [`barchart.html`](barchart.html) | two D3 bar charts plus the plaque of most-frequent numbers |

Open the two HTML files in a browser — they are self-contained apart from the vendored
`d3.min.js`, so they work offline and by double-click.

## Source

| file | role |
|---|---|
| `eurojackpot.csv` | the input data — the folder is self-contained; nothing is fetched |
| `analysis.py` | every statistic; standard library only; the single source of truth |
| `make_html.py` | builds the two HTML pages from `stats.json` |
| `build_notebook.py` | builds the notebook with `nbformat` |
| `stats.json` | generated — every figure the write-up, pages and notebook quote |
| `d3.min.js` | vendored D3 v7.9.0, so the pages work without a CDN |

## Reproducing

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

python analysis.py          # -> stats.json      (runs without the venv; self-checks everything)
python make_html.py         # -> heatmap.html, barchart.html
python build_notebook.py    # -> lottery_analysis.ipynb (unexecuted)
python -m nbconvert --to notebook --execute --inplace lottery_analysis.ipynb
```

`analysis.py` takes a couple of seconds and asserts every invariant the write-up depends on: draw
counts, value totals, the five chi-square statistics, the pooled-set trap, the hot-list
instability, adjacency, overlap and the jackpot odds. It exits non-zero if any of them move, so a
change to the data cannot silently invalidate the prose. `stats.json` is byte-identical across
runs (all randomness is seeded).

## Notes on the data

The CSV is semicolon-delimited with a Czech header and differs from the brief's description in
three ways worth knowing before writing any code against it:

- it has **10** populated columns, not 9 — there is an undocumented `tyden` (ISO week) column;
- `rok` is the **ISO week-year**, so it disagrees with the calendar year for 4 draws;
- rows are stored **newest-first**, and Set #1 is **not** sorted.

`analysis.py` handles all three and documents them where they bite. There is no BOM in the file
(the first bytes are `datum;`), contrary to what a Czech-locale export might suggest.
