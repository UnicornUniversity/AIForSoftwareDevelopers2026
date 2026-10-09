# Eurojackpot: what 821 draws actually tell us

**Question.** `eurojackpot.csv` holds every Eurojackpot draw between 10 Oct 2014 and 12 May 2026.
Is there any pattern in it — hot numbers, cold numbers, correlations, anything a predictive model
could exploit?

**Answer: no.** The draws are statistically indistinguishable from a fair uniform random process.
The one large apparent anomaly in the data is not a property of the balls at all — it is an
artefact of a rule change that the file records but the task description does not mention.

| | |
|---|---|
| Draws analysed | **821** (10 Oct 2014 → 12 May 2026) |
| Set #1 | 5 numbers from 1–50 — 4,105 values |
| Set #2 | 2 numbers from 1–12 — 1,642 values |
| Era-correct uniformity tests passed | **4 of 4** |
| Probability the pooled view is uniform | **< 1 × 10⁻¹²** (it rejects — and it is wrong to pool) |
| Predictive model vs random | 0.5025 vs 0.4881 matched numbers per line, **p = 0.171** |
| Odds of one line matching all seven | **1 in 139,838,160** |

---

## 1. The data, and three things the brief gets wrong

The CSV is semicolon-delimited with a Czech header. Profiling it before analysis turned up four
details that materially affect the result:

1. **There are 10 populated columns, not 9.** The brief describes date, year, five Set #1 numbers
   and two Set #2 numbers. The file also carries an undocumented **`tyden`** (ISO week number)
   between the year and the numbers, plus a trailing `;` that yields an empty 11th field. The week
   column is what makes the twice-weekly cadence change visible in section 2.
2. **`rok` is the ISO week-year, not the calendar year.** Four rows disagree with their own date —
   e.g. `30. 12. 2025` is tagged `2026`, because that date falls in ISO week 1 of 2026. Any
   year-grouping must use the parsed date, not that column, or four draws silently move year.
3. **The rows are stored newest-first.** They are sorted ascending on load. Skipping this inverts
   every recency and gap calculation downstream — the numbers still look plausible, they are just
   backwards, which is the worst kind of bug.
4. **The file has no BOM** (the first bytes are `datum;`), contrary to what one might assume of a
   Czech-locale export. It is read as `utf-8-sig` regardless, which is a no-op here and strips a
   BOM should one ever be added.

One further property matters for section 6: **Set #1 is not stored sorted.** Only 5 of 821 rows
happen to be ascending where chance predicts about 7, so the `1. cislo` … `5. cislo` columns
preserve the order the balls came out. That makes a positional analysis meaningful — and means any
downstream code that assumes sorted columns is simply wrong.

---

## 2. The decisive finding: a rule change in March 2022

On **25 March 2022** Eurojackpot changed two things at once, and both are visible in the file:

| | Era A | Era B |
|---|---|---|
| Draws | **389** (10 Oct 2014 → 18 Mar 2022) | **432** (25 Mar 2022 → 12 May 2026) |
| Cadence | weekly — 389 gaps of exactly 7 days | twice weekly, Tue + Fri — gaps of 3 and 4 days |
| Set #2 universe | **1–10** | **1–12** |

Draws per year tell the story immediately: 52–53 every year through 2021, then **92 in 2022** and
**104 a year** from 2023. And the largest Set #2 value drawn steps from 10 to 12 exactly at the
boundary.

This is not a footnote. It means the history is **two different games stacked end to end**, and
anything computed across the boundary is comparing them as though they were one.

---

## 3. Frequency analysis and the hot/cold lists

Under current rules each Set #1 number is expected to appear `432 × 5/50 = **43.2**` times and each
Set #2 number `432 × 2/12 = **72.0**` times.

**Era B (current rules), Set #1** — observed range 27–58 against an expectation of 43.2 with a
standard deviation of 6.2:

| | numbers (times drawn) |
|---|---|
| Hottest 5 | **11** (58), **17** (54), **20** (52), **30** (52), **13** (51) |
| Coldest 5 | 42 (35), 19 (34), 5 (33), 33 (33), **25** (27) |

**Era B, Set #2** — observed range 62–85 against an expectation of 72.0, standard deviation 7.7:

| | numbers (times drawn) |
|---|---|
| Hottest 2 | **5** (85), **3** (83) |
| Coldest 2 | 8 (64), 11 (62) |

**Full history, Set #1** (for contrast): 20 (102), 35 (95), 11 (94), 16 (94), 34 (94).

### The hot list does not survive a change of window

This is the simplest evidence that "hot" is not a property of the machine. Recomputing on Era B
alone keeps only **two of the five** numbers:

| | top 5 Set #1 |
|---|---|
| Full history | 20 (102), 35 (95), 11 (94), 16 (94), 34 (94) |
| Era B only | 11 (58), 17 (54), 20 (52), 30 (52), 13 (51) |
| **Overlap** | **11 and 20 — two of five** |

A genuine physical bias would persist across both windows. A ranking of coin-flip outcomes
reshuffles when you change the sample, which is exactly what happens here. Even within Era B the
spread is unremarkable: number 11 at 58 is about 2.4 standard deviations above expectation, and
with 50 numbers on screen you *expect* to see a couple that far out.

---

## 4. The trap: pooling two different Set #2 universes

This is the most instructive thing in the dataset. Count Set #2 over the whole file, ignoring the
rule change:

| Set #2 number | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Naive, all 821 draws | 146 | 135 | 161 | 145 | 164 | 151 | 148 | 149 | 159 | 145 | **62** | **77** |

Numbers 11 and 12 look catastrophically cold — 62 and 77 against 135–164 for everything else. A
chi-square test on that table gives **χ² = 85.42, df = 11, p < 1 × 10⁻¹²**. That is a
highly significant, publishable-looking result. A careless analysis would announce that 11 and 12
are "due", and build a model around it.

It is entirely fictitious. **Numbers 11 and 12 did not exist before 25 March 2022.** They had 432
draws in which to appear instead of 821, so of course they have roughly half the count. Restricted
to the era in which the 1–12 game was actually played, every number lands between 62 and 85 against
an expectation of 72.0, and the test passes comfortably (χ² = 7.94, df = 11, p = 0.718).

The lesson generalises well beyond lotteries: a real statistical effect, significant at
p < 10⁻¹², was produced with no mechanism behind it at all — just by aggregating two populations
that should never have been pooled.

---

## 5. Testing uniformity properly

Chi-square goodness-of-fit, each set scored only against the universe actually in play, with
zero-count categories retained so the degrees of freedom are correct:

| Test | n | universe | expected | χ² | df | p | verdict |
|---|---|---|---|---|---|---|---|
| Set #1, full history | 4,105 | 1–50 | 82.10 | 40.74 | 49 | 0.793 | consistent with uniform |
| Set #1, Era A | 1,945 | 1–50 | 38.90 | 29.47 | 49 | 0.988 | consistent with uniform |
| Set #1, Era B | 2,160 | 1–50 | 43.20 | 47.08 | 49 | 0.551 | consistent with uniform |
| Set #2, Era A | 778 | 1–10 | 77.80 | 4.72 | 9 | 0.858 | consistent with uniform |
| Set #2, Era B | 864 | 1–12 | 72.00 | 7.94 | 11 | 0.718 | consistent with uniform |
| *Set #2, pooled* | 1,642 | 1–12 | 136.83 | **85.42** | 11 | **< 1e-12** | *rejects — mis-specified* |

Every era-correct test passes, several of them with p-values suspiciously close to 1, which is what
a fair process looks like. The only rejection is the deliberately mis-specified pooled row.

The p-values are computed from a regularised incomplete gamma function implemented in `analysis.py`
rather than pulled from a library, and unit-checked against standard tables
(`χ²(3.841, df=1) = 0.0500`, `χ²(66.339, df=49) = 0.0500`, and four more) before anything was built
on top of them.

---

## 6. Structure of a draw

**Position carries no information.** Chi-square on each of the five Set #1 columns, over all 821
draws:

| Position | χ² | df | p |
|---|---|---|---|
| 1st ball | 43.01 | 49 | 0.714 |
| 2nd ball | 48.85 | 49 | 0.479 |
| 3rd ball | 40.69 | 49 | 0.795 |
| 4th ball | 37.65 | 49 | 0.881 |
| 5th ball | 42.64 | 49 | 0.727 |

The order the balls emerge is as uninformative as the numbers themselves — one potential modelling
dimension closed off.

**Composition.** In Era B, Set #1 is 1,103 odd / 1,057 even (51.1% odd; expected 50%). The decade
buckets 1–10 through 41–50 come out 426 / 475 / 428 / 422 / 409, against 432 each. Nothing stands
out.

**Adjacency.** 280 of 821 draws (34.10%) contain two consecutive numbers. The exact rate, enumerated
over all 2,118,760 possible 5-number combinations rather than simulated, is 35.30%. Slightly fewer
than expected — comfortably inside noise, and the opposite of the "clustering" a pattern-seeker
would hope for.

---

## 7. Gaps, droughts, and the gambler's fallacy

If draws are independent, the gap between successive appearances of a Set #1 number is geometric
with mean `1/p = 10` draws. Observed mean gap in Era B: **10.00**. Textbook.

The longest current drought is **number 24, unseen for 40 draws** (since 23 Dec 2025). This feels
dramatic until you do the arithmetic:

- P(a given number skips ≥ 40 draws) = 0.9⁴⁰ = **0.0148**
- Gaps observed in this window: 2,160
- Expected number of gaps that long: 0.0148 × 2,160 = **31.9**

Roughly thirty-two gaps of that length are *expected* to occur. Seeing one is not a signal; seeing
none would have been the surprise. This is the clearest possible illustration of why "overdue" is
not information.

**Correlations between draws.** Consecutive draws share a mean of **0.4927** Set #1 numbers where
0.50 is expected — no carry-over from one draw to the next. On co-occurrence within a draw, 1,224
of the 1,225 possible Set #1 pairs were observed at least once against an expected 6.70 each, with
the most common pair (34, 49) appearing 16 times. Testing 1,225 pairs simultaneously at α = 0.05
expects around 61 spurious "significant" pairs by chance alone, so a top-pair list is decorative —
it is rank-order noise, and the multiplicity is the point.

---

## 8. The predictive model — and its honest verdict

The brief asks for a model that suggests winning numbers. One was built, and then tested properly.

**Design.** Three weak and partly contradictory signals are blended into a score per number:

| component | hypothesis it encodes | weight |
|---|---|---|
| `frequency` | "hot numbers keep coming" | 0.4 |
| `recency` | "these haven't appeared lately" | 0.3 |
| `gap_ratio` | current drought ÷ that number's own mean gap | 0.3 |

The first two are the folk theories real players use, and they contradict each other — which is
itself good reason to expect neither to work. Weights are a documented judgement call rather than
fitted values; section 8.2 shows the conclusion does not depend on them. Lines are drawn by
weighted sampling without replacement from the scores, seeded so the output is reproducible.
**All features are computed on Era B only**, because the cadence and the Set #2 universe both change
at the boundary and mixing eras would feed the model incomparable history.

### 8.1 Walk-forward backtest

For each of the last 120 Era B draws, the model is fitted on *strictly earlier draws only*, then 60
candidate lines are generated and matched against the actual result. The same number of uniformly
random lines is scored on the same draws as a control. A random 5-from-50 line matches
`5 × 5/50 = 0.5` numbers on average — that is the bar.

| | mean matched per line | 95% CI | lines scored |
|---|---|---|---|
| Model (frequency + recency + gap) | **0.5025** | 0.488 – 0.517 | 7,200 |
| Random lines | **0.4881** | 0.474 – 0.503 | 7,200 |
| Analytic expectation | **0.5000** | — | — |

Difference **+0.0144**, z = 1.37, **p = 0.171**. The model lands within one fifth of a percentage
point of chance and is not significantly different from it at any conventional threshold.

### 8.2 Does it depend on the weights? No.

Sweeping 26 weight configurations and checking whether the winner reproduces on a second window:

| | best config | score | spread across 26 configs |
|---|---|---|---|
| Window A (most recent 60 draws) | f1.0 / r0.5 / g0.5 | 0.5240 | 0.0387 |
| Window B (the 60 before that) | f0.0 / r1.0 / g1.0 | 0.5233 | 0.0300 |

The two windows pick **completely different winners**. Window B's best configuration ranks **21st
of 26** on window A, and window A's best drops from 0.5240 to 0.5080 on window B. Picking the
best-looking corner of a noisy grid is guaranteed to produce an apparent edge; that it evaporates
when the window moves is the signature of fitting noise. Note also that window B prefers
`f0.0 / r1.0 / g1.0` — pure "due number" logic — while window A wants the opposite mix. The two
strategies players actually use cannot both be right, and the data cannot tell them apart.

### 8.3 Suggested lines

Five lines are generated and stored in `stats.json` (reproducible from seed 7). They are reported
because the brief asks for them, and they are exactly as good as any other five lines — that is,
identical in expectation to picking at random. **They are for entertainment, not forecasting.**

---

## 9. Conclusion

- Every era-correct frequency distribution is consistent with uniformity. The single test that
  rejects uniformity is an artefact of pooling two number universes, and it disappears the moment
  the 2022 rule change is respected.
- The "hot five" loses three of its five members when the measurement window changes. Real bias
  persists; coin-flip rankings do not.
- The longest current drought is the length you should *expect* to see roughly 32 times over in a
  window this size.
- Consecutive draws share 0.4927 numbers where 0.50 is expected — draws are independent.
- The model matched 0.5025 numbers per line against 0.4881 for random lines and an analytic
  expectation of 0.50 (p = 0.171), and its best weight configuration failed to reproduce across
  windows.

Playing one line every draw for the whole 12-year history in this file leaves an expected jackpot
count of `821 / 139,838,160 ≈ 0.000006`.

---

## 10. Limitations

The tests establish that the data is *consistent with* fairness; they do not prove the machine is
fair. A bias smaller than the sampling noise of 821 draws — or one confined to a subset of the
history — would not be detected here. Partial years (2014 with 12 draws, 2026 with 39) and the
transition year 2022 are not comparable year-on-year, which is why the per-year view is used only
to locate the rule change, never to make a claim. No external data was used: everything here comes
from `eurojackpot.csv` alone.

---

## 11. Where everything lives

| file | contents |
|---|---|
| [`analysis.py`](analysis.py) | all statistics — standard library only, no dependencies |
| [`stats.json`](stats.json) | every computed figure, consumed by the pages and the write-up |
| [`lottery_analysis.ipynb`](lottery_analysis.ipynb) | the analysis as an executed notebook, charts included |
| [`heatmap.html`](heatmap.html) | two D3 frequency heatmaps, with an era toggle |
| [`barchart.html`](barchart.html) | two D3 bar charts, expected-frequency reference, and the plaque |
| [`make_html.py`](make_html.py) / [`build_notebook.py`](build_notebook.py) | generators for the pages and the notebook |

The two HTML pages are self-contained apart from a vendored `d3.min.js`, so they work offline and
when opened by double-click. Both carry a **draw-history toggle**: switching between "current
rules" and "full history" makes the section 4 artefact visible in the Set #2 panel — numbers 11 and
12 visibly turn from the coldest cells on the board into ordinary ones.

On `barchart.html`, the plaque required by the brief sits below the two charts, and every bar is
plotted against the frequency a fair draw would produce. Almost the entire chart sits inside the
shaded 95% range, which is the conclusion of this analysis in one glance.

## 12. Reproducing

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

python analysis.py          # -> stats.json      (stdlib only; self-checks all invariants)
python make_html.py         # -> heatmap.html, barchart.html
python build_notebook.py    # -> lottery_analysis.ipynb (unexecuted)
python -m nbconvert --to notebook --execute --inplace lottery_analysis.ipynb
```

`analysis.py` asserts every figure quoted above — draw counts, value totals, the five chi-square
statistics, the pooled trap counts, the hot-list instability, adjacency, overlap and the odds — and
fails loudly if any of them move. If you change the analysis, it will tell you which of these
numbers the write-up depends on.
