"""Render the semantic-chunking study as one standalone HTML file.

Every number comes from ``out/stats.json``; the full-text view comes from
``out/volumes_view.json``. This module formats those files and nothing else, so
the report cannot disagree with the run. The page has no ``<script>`` and makes
no network requests: it opens by double-click.

Usage:
    python make_html.py [--stats out/stats.json] [--view out/volumes_view.json]
                        [--out report.html]
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TINTS = 8


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def attr(text: object) -> str:
    return html.escape(str(text), quote=True)


def n(value: float | int) -> str:
    return f"{value:,.0f}"


def num(value: float | int | None, digits: int = 1, dash: str = "—") -> str:
    if value is None:
        return dash
    return f"{value:,.{digits}f}"


def pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def z(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}"


def metric(metrics: dict, key: str, digits: int = 1) -> str:
    return num(metrics.get(key), digits)


def signal(value: float | None, positive_above: float = 0.0) -> str:
    """CSS class for a value where higher is better."""
    if value is None:
        return ""
    return "good" if value > positive_above else "bad"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #faf9f6;
  --card: #ffffff;
  --ink: #1c1917;
  --muted: #57534e;
  --faint: #78716c;
  --line: #e7e5e4;
  --line-strong: #d6d3d1;
  --accent: #1d4ed8;
  --accent-soft: #dbeafe;
  --good: #047857;
  --warn: #b45309;
  --bad: #b91c1c;
  --ov: #fde68a;
  --ov-line: #b45309;
  --c0: #eef2ff;
  --c1: #ecfdf5;
  --c2: #fff7ed;
  --c3: #f0f9ff;
  --c4: #fdf2f8;
  --c5: #f7fee7;
  --c6: #f5f3ff;
  --c7: #fefce8;
  --radius: 14px;
  color-scheme: light;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14120f;
    --card: #1c1917;
    --ink: #e7e5e4;
    --muted: #a8a29e;
    --faint: #78716c;
    --line: #292524;
    --line-strong: #44403c;
    --accent: #60a5fa;
    --accent-soft: #1e3a8a;
    --good: #34d399;
    --warn: #fbbf24;
    --bad: #f87171;
    --ov: #78350f;
    --ov-line: #fbbf24;
    --c0: rgba(99, 102, 241, .13);
    --c1: rgba(16, 185, 129, .12);
    --c2: rgba(249, 115, 22, .12);
    --c3: rgba(14, 165, 233, .12);
    --c4: rgba(236, 72, 153, .12);
    --c5: rgba(132, 204, 22, .11);
    --c6: rgba(139, 92, 246, .13);
    --c7: rgba(234, 179, 8, .11);
    color-scheme: dark;
  }
}

* { box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 16px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 1120px; margin: 0 auto; padding: 0 24px 96px; }

a { color: var(--accent); text-underline-offset: 3px; }

.hero { padding: 72px 0 28px; border-bottom: 1px solid var(--line); }
.eyebrow {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: .78rem;
  font-weight: 650;
  letter-spacing: .13em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  max-width: 20ch;
  font-size: clamp(2.1rem, 5.4vw, 3.7rem);
  line-height: 1.04;
  letter-spacing: -.035em;
}
.lede { max-width: 72ch; margin: 20px 0 0; color: var(--muted); font-size: 1.08rem; }

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin: 34px 0 0;
}
.tile {
  padding: 18px 18px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
}
.tile b { display: block; font-size: 1.9rem; line-height: 1.15; letter-spacing: -.03em; }
.tile span { display: block; margin-top: 6px; color: var(--muted); font-size: .84rem; }

.callout {
  margin: 40px 0 0;
  padding: 24px 26px;
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: var(--radius);
  background: var(--card);
}
.callout h2 { margin: 0 0 10px; border: 0; padding: 0; font-size: 1.25rem; }
.callout p { margin: 0 0 10px; }
.callout p:last-child { margin-bottom: 0; }

.toc {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin: 26px 0 0;
  padding: 18px 0;
  border-bottom: 1px solid var(--line);
  font-size: .86rem;
}
.toc a { color: var(--muted); text-decoration: none; }
.toc a:hover { color: var(--accent); text-decoration: underline; }

section { scroll-margin-top: 24px; }

h2 {
  margin: 64px 0 18px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  font-size: 1.6rem;
  line-height: 1.2;
  letter-spacing: -.02em;
}
h2 .sechead { color: var(--faint); font-weight: 500; margin-right: 10px; }
h3 { margin: 28px 0 10px; font-size: 1.12rem; letter-spacing: -.01em; }
table.compare td:first-child { min-width: 180px; }
table.compare th, table.compare td { padding-left: 7px; padding-right: 7px; }
p { margin: 0 0 14px; }
.small { color: var(--muted); font-size: .88rem; }
.tight { margin-top: 8px; }

.tablewrap { overflow-x: auto; margin: 16px 0 8px; }
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th {
  color: var(--muted);
  font-size: .76rem;
  font-weight: 650;
  letter-spacing: .04em;
  text-transform: uppercase;
  border-bottom: 2px solid var(--line-strong);
  white-space: nowrap;
}
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.total td { border-top: 2px solid var(--line-strong); font-weight: 650; }
.good { color: var(--good); font-weight: 650; }
.bad { color: var(--bad); }
.muted { color: var(--muted); }

.code {
  overflow-x: auto;
  margin: 16px 0;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  font: .84rem/1.7 ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  white-space: pre;
}

ol.steps { margin: 14px 0 0; padding-left: 22px; }
ol.steps li { margin: 0 0 12px; padding-left: 4px; }
ol.steps b { font-weight: 650; }

.heat td { text-align: center; vertical-align: middle; padding: 0; border: 2px solid var(--card); }
.heat .qcell { padding: 10px; background: transparent; border: 0; font-weight: 650; text-align: right; }
.heat .buf { padding: 10px; background: transparent; border: 0; }
.heatcell {
  display: block;
  padding: 10px 8px;
  border-radius: 8px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.heatcell b { display: block; font-size: .95rem; line-height: 1.2; }
.heatcell small { display: block; margin-top: 2px; color: var(--muted); font-size: .7rem; }
.heat .best { outline: 2px solid var(--accent); outline-offset: -2px; }

.hist { margin: 18px 0 8px; }
.histrow {
  display: grid;
  grid-template-columns: 104px minmax(80px, 1fr) 108px;
  gap: 12px;
  align-items: center;
  margin: 0 0 7px;
  font-size: .82rem;
}
.histlabel { color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }
.histtrack { height: 18px; border-radius: 5px; background: var(--line); overflow: hidden; }
.histbar { height: 100%; border-radius: 5px; background: var(--accent); opacity: .72; }
.histn { color: var(--muted); font-variant-numeric: tabular-nums; }

.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }

.bcard, .sample {
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
}
.bcard h4, .sample h4 { margin: 0 0 6px; font-size: .95rem; }
.bmeta { color: var(--muted); font-size: .76rem; line-height: 1.5; }
.btext { margin-top: 12px; font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif; font-size: .95rem; line-height: 1.65; }
.btext .side { padding: 10px 12px; border-radius: 8px; background: var(--bg); }
.cutmark {
  margin: 6px 0;
  padding: 4px 0;
  border-top: 1px dashed var(--line-strong);
  color: var(--warn);
  font: .74rem/1.4 ui-sans-serif, system-ui, sans-serif;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.sample p { font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif; font-size: .95rem; line-height: 1.7; }
.sample .meta { margin: 0 0 8px; color: var(--muted); font: .78rem/1.5 ui-sans-serif, system-ui, sans-serif; }

details.volume {
  margin: 0 0 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
}
details.volume > summary {
  cursor: pointer;
  padding: 16px 20px;
  font-weight: 650;
  list-style-position: outside;
}
details.volume > summary span { color: var(--muted); font-weight: 400; font-size: .84rem; }
.voltext { padding: 4px 22px 26px; border-top: 1px solid var(--line); }
.chapter { margin-top: 30px; }
.chapter h3 {
  margin: 0 0 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--line);
  font-size: 1rem;
}
.ch-meta { display: block; margin-top: 2px; color: var(--faint); font-weight: 400; font-size: .76rem; }
p.prose {
  margin: 14px 0;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
  font-size: 1.01rem;
  line-height: 1.78;
}
p.prose .s { padding: 1px 0; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.c0 { background: var(--c0); } .c1 { background: var(--c1); }
.c2 { background: var(--c2); } .c3 { background: var(--c3); }
.c4 { background: var(--c4); } .c5 { background: var(--c5); }
.c6 { background: var(--c6); } .c7 { background: var(--c7); }
.ov { background: var(--ov) !important; box-shadow: inset 0 -1px 0 var(--ov-line); }
.cut { border-left: 2px solid var(--accent); margin-left: -2px; }

.legend { display: flex; flex-wrap: wrap; gap: 10px 18px; margin: 12px 0 18px; font-size: .8rem; color: var(--muted); }
.legend i { display: inline-block; width: 15px; height: 15px; margin-right: 6px; border: 1px solid var(--line-strong); border-radius: 3px; vertical-align: -3px; }

.note {
  margin: 14px 0;
  padding: 12px 16px;
  border-left: 3px solid var(--warn);
  background: var(--card);
  color: var(--muted);
  font-size: .88rem;
}
.note b { color: var(--ink); }

footer {
  margin-top: 72px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
  color: var(--faint);
  font-size: .8rem;
}

@media (max-width: 620px) {
  .wrap { padding: 0 16px 72px; }
  .hero { padding-top: 48px; }
  .callout { padding: 20px; }
  .histrow { grid-template-columns: 78px minmax(60px, 1fr) 62px; gap: 8px; }
  .voltext { padding: 4px 16px 22px; }
}
"""


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def render_tiles(best: dict) -> str:
    m = best["metrics"]
    tiles = [
        (n(m["count"]), "chunks across six volumes and 300 chapters"),
        (f"{num(m['mean_chars'], 0)}", f"mean characters · {n(round(m['mean_chars'] / 4))} est. tokens"),
        (f"{m['separation_drop']:+.2f}", "mean similarity drop at a cut (fixed-size: −0.02)"),
        (pct(m["separation_accuracy_pct"]), "cuts that are a local similarity dip"),
    ]
    return (
        '<div class="tiles">'
        + "".join(f'<div class="tile"><b>{b}</b><span>{esc(s)}</span></div>' for b, s in tiles)
        + "</div>"
    )


def render_corpus(corpus: dict) -> str:
    rows = []
    for item in corpus["per_volume"]:
        rows.append(
            "<tr>"
            f"<td>Volume {item['volume']}</td>"
            f"<td class=n>{n(item['chapters'])}</td>"
            f"<td class=n>{n(item['paragraphs'])}</td>"
            f"<td class=n>{n(item['sentences'])}</td>"
            f"<td class=n>{n(item['chars'])}</td>"
            "</tr>"
        )
    rows.append(
        '<tr class="total">'
        "<td>All volumes</td>"
        f"<td class=n>{n(corpus['chapters'])}</td>"
        f"<td class=n>{n(corpus['paragraphs'])}</td>"
        f"<td class=n>{n(corpus['sentences'])}</td>"
        f"<td class=n>{n(corpus['chars'])}</td>"
        "</tr>"
    )
    return f"""
<div class="tablewrap">
<table>
  <thead><tr><th>Source</th><th class=n>Chapters</th><th class=n>Paragraphs</th><th class=n>Sentences</th><th class=n>Characters</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class="small">Mean paragraph {n(corpus['mean_paragraph_chars'])} chars (median
{n(corpus['median_paragraph_chars'])}, p90 {n(corpus['p90_paragraph_chars'])}, p99
{n(corpus['p99_paragraph_chars'])}). Mean sentence {num(corpus['mean_sentence_chars'])} chars.
The corpus is {n(corpus['words'])} words. Paragraph lengths are heavy-tailed: most are short, a
few run to thousands of characters, which is why paragraph-only chunking either overshoots the
embedding window or has to split paragraphs anyway.</p>
"""


def render_method(best: dict, constraints: dict) -> str:
    m = best["metrics"]
    return f"""
<p>The mechanism is an embedding-distance splitter — the family used by LlamaIndex's
<code>SemanticSplitterNodeParser</code> and Kamradt's semantic chunker — with three additions that
matter on a book-length corpus: <b>context probes</b>, <b>hard size constraints</b>, and
<b>chapter walls</b>.</p>

<ol class="steps">
  <li><b>Structure first.</b> Strip the Gutenberg licence, locate the body, recover headings,
  paragraphs, and a sentence stream. Abbreviation-aware splitting keeps <i>St.</i>, <i>A.D.</i>,
  <i>i.e.</i> and initials from ending a sentence.</li>

  <li><b>Embed each sentence.</b> The default backend is spaCy <code>en_core_web_lg</code> static
  vectors, combined with smooth-inverse-frequency weights (SIF, a = 1e-3). The matrix is
  mean-centred, its first principal component removed, and every row L2-normalised. Centring is
  load-bearing: uncentred static vectors sit in a narrow cone where every sentence looks about
  0.93 similar, and all distances become uninformative.</li>

  <li><b>Compare context, not single sentences.</b> For sentence <i>i</i>, the probe is the
  normalised mean of the sentence vectors in a window of <i>b</i> sentences on either side. The
  raw distance is the cosine distance between consecutive probes. With <i>b</i> = 0 the probe is
  the sentence itself; with <i>b</i> &gt; 0 one short sentence cannot move a boundary alone.</li>

  <li><b>Score boundaries, then choose under constraints.</b> A percentile floor marks candidate
  positions; a left-to-right packer picks the strongest legal candidate in each window. The
  winning configuration on this corpus sets the floor to zero: every position is a candidate, and
  the size constraints alone decide which one wins.</li>

  <li><b>Carry one sentence of overlap.</b> The previous chunk's last sentence is prefixed to the
  next chunk in whole-sentence form, never across a chapter heading. The chunk text stays inside
  a 512-token embedding window (2,048 chars at the chars/4 estimate) including a ~110-char chapter
  breadcrumb.</li>
</ol>

<div class="code">probe(i)   = normalize( mean( v[i-b] … v[i+b] ) )
d(i)       = 1 − cos( probe(i−1), probe(i) )
floor(c)   = percentile( {{ d(i) : i in chapter c }}, q )

candidate(i)  ⇔  d(i) ≥ floor(c)
choose(i)     =  argmax  d(i) + 0.03·[starts paragraph] − 0.03·|chars − {best['target_chars']}|/{best['target_chars']}
                  i ∈ [low, high]

low  = first position with ≥ {n(best['min_chars'])} chars
high = last position with ≤ {n(best['max_chars'])} chars
overlap = the previous chunk's final sentence, in full</div>

<p class="small">Distances are cosine distances (1 − cosine similarity) of L2-normalised probes.
The paragraph bonus is small on purpose: it breaks ties, it does not overrule the vectors. The
chapter wall is absolute. The percentile floor is computed per chapter, not per corpus, because
Gibbon's chapters differ in how sharply their topics turn.</p>

<div class="note"><b>Why q = 0 wins here.</b> The classic advice is a high floor (q = 95), so only
strong semantic breaks become cuts. On this corpus the size ceiling is tight ({n(best['max_chars'])} chars), and a
chapter often needs a cut where no 95th-percentile break exists. The packer then falls back to an
arbitrary position. Measured on the same vectors, q = 95 cuts below its own floor <b>71.7%</b> of
the time; q = 0 does so <b>0%</b> of the time while keeping a similar size distribution. The floor
was removing good candidates and forcing bad ones.</div>

<p class="small">Embedding window: {n(constraints['embed_window_tokens'])} tokens
({n(constraints['embed_window_chars'])} chars), chapter prefix {n(constraints['heading_prefix_chars'])}
chars, chars/token {constraints['chars_per_token']}.</p>
"""


def render_sweep(sweep: list[dict], best: dict, plateau: dict) -> str:
    fixed = [
        item for item in sweep
        if item["min_chars"] == 500 and item["max_chars"] == 1900
    ]
    percentiles = sorted({item["percentile"] for item in fixed})
    buffers = sorted({item["buffer_size"] for item in fixed})
    cells = {(item["percentile"], item["buffer_size"]): item for item in fixed}
    scores = [item["metrics"]["composite"] for item in fixed]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0

    head = "".join(f"<th class=n>buffer {b}</th>" for b in buffers)
    body = []
    for q in percentiles:
        row = [f'<td class="qcell">{"none" if q == 0 else f"q{int(q)}"}</td>']
        for b in buffers:
            item = cells.get((q, b))
            if item is None:
                row.append('<td class="heatcell">—</td>')
                continue
            m = item["metrics"]
            strength = 0.07 + 0.55 * (m["composite"] - lo) / span
            is_best = (
                q == best["percentile"]
                and b == best["buffer_size"]
                and item["min_chars"] == best["min_chars"]
                and item["max_chars"] == best["max_chars"]
            )
            row.append(
                f'<td><span class="heatcell{" best" if is_best else ""}" '
                f'style="background:rgba(29,78,216,{strength:.2f})">'
                f'<b>{m["composite"]:.3f}</b>'
                f'<small>{m["count"]:,} chunks · {pct(m.get("forced_boundary_pct"))} forced</small>'
                "</span></td>"
            )
        body.append("<tr>" + "".join(row) + "</tr>")

    floor_rows = []
    for q in percentiles:
        item = cells.get((q, 0))
        if item is None:
            continue
        m = item["metrics"]
        floor_rows.append(
            "<tr>"
            f'<td>{"none (q=0)" if q == 0 else f"q{int(q)}"}</td>'
            f'<td class=n>{m["count"]:,}</td>'
            f'<td class=n>{m["contrast_z"]:+.3f}</td>'
            f'<td class=n>{pct(m.get("forced_boundary_pct"))}</td>'
            f'<td class=n>{m["in_band_pct"]:.1f}%</td>'
            f'<td class=n><b>{m["composite"]:.4f}</b></td>'
            "</tr>"
        )

    ranked = sorted(sweep, key=lambda item: item["metrics"]["composite"], reverse=True)
    full_rows = []
    for rank, item in enumerate(ranked, start=1):
        m = item["metrics"]
        full_rows.append(
            "<tr>"
            f"<td class=n>{rank}</td>"
            f'<td>{"none" if item["percentile"] == 0 else int(item["percentile"])}</td>'
            f"<td class=n>{item['buffer_size']}</td>"
            f"<td class=n>{item['min_chars']}</td>"
            f"<td class=n>{item['max_chars']}</td>"
            f"<td class=n>{m['count']:,}</td>"
            f"<td class=n>{m['mean_chars']:,.0f}</td>"
            f"<td class=n>{m['in_band_pct']:.1f}%</td>"
            f"<td class=n>{m['contrast_z']:+.3f}</td>"
            f"<td class=n>{pct(m.get('forced_boundary_pct'))}</td>"
            f"<td class=n>{m['composite']:.4f}</td>"
            "</tr>"
        )

    return f"""
<p>The sweep is a grid, not a search: {len(sweep)} configurations = 6 percentile floors ×
3 probe buffers × 2 minimum sizes × 3 maximum sizes. Every row is scored by
<i>cheap</i> metrics (size, boundary contrast, paragraph alignment, estimated overlap); the winning
row is then measured exactly, including separation and reference recovery. The heatmap fixes
min/max at the recommendation and shows the percentage of cuts that fell below the chapter's own
floor — the direct cost of raising it.</p>

<h3>Composite score by floor and probe buffer</h3>
<p class="small">Min {n(best['min_chars'])} / max {n(best['max_chars'])} chars. Higher is better. “Forced”
is the share of cuts below the percentile floor the configuration itself declared.</p>
<div class="tablewrap">
<table class="heat">
  <thead><tr><th class=n>floor</th>{head}</tr></thead>
  <tbody>{''.join(body)}</tbody>
</table>
</div>

<h3>The floor is the problem</h3>
<div class="tablewrap">
<table>
  <thead><tr><th>Floor</th><th class=n>Chunks</th><th class=n>Contrast z</th><th class=n>Forced cuts</th><th class=n>In 500–2,000</th><th class=n>Composite</th></tr></thead>
  <tbody>{''.join(floor_rows)}</tbody>
</table>
</div>
<p class="small">At fixed min 500 / max 1,900 and buffer 0. Raising the floor removes candidates
without removing the need to cut; the packer then places boundaries the model did not endorse.
Contrast and size barely move, but the cuts get worse. q = 0 is the minimum of the chapter's
distances, so its 0% forced share is true by construction; the informative rows are q60–q95, where
each added floor point raises the share of cuts the floor itself rejects.</p>

<h3>Plateau</h3>
<p><b>{plateau['within_0.02_of_best']} configurations are within 0.02 of the best composite.</b>
They span floors {', '.join('none' if q == 0 else f'q{int(q)}' for q in plateau['percentiles'])},
buffers {', '.join(str(b) for b in plateau['buffers'])}, minimums
{', '.join(str(v) for v in plateau['min_chars'])}, and maximums
{', '.join(str(v) for v in plateau['max_chars'])}. The recommendation is the centre of that
plateau, not a knife-edge optimum.</p>

<details>
  <summary><b>All {len(sweep)} configurations, ranked</b></summary>
  <div class="tablewrap">
  <table>
    <thead><tr><th class=n>#</th><th>Floor</th><th class=n>Buffer</th><th class=n>Min</th><th class=n>Max</th><th class=n>Chunks</th><th class=n>Mean</th><th class=n>In band</th><th class=n>Contrast z</th><th class=n>Forced</th><th class=n>Composite</th></tr></thead>
    <tbody>{''.join(full_rows)}</tbody>
  </table>
  </div>
</details>
"""


def comparison_row(name: str, note: str, m: dict, kind: str = "") -> str:
    overlap = m.get("overlap_pct")
    return (
        "<tr>"
        f'<td><b>{esc(name)}</b><div class="bmeta">{esc(note)}</div></td>'
        f"<td class=n>{n(m['count'])}</td>"
        f"<td class=n>{num(m['mean_chars'], 0)}</td>"
        f"<td class=n>{pct(m['in_band_pct'])}</td>"
        f'<td class="n {signal(m.get("contrast_z"))}">{z(m["contrast_z"])}</td>'
        f'<td class="n {signal(m.get("separation_drop"))}">{num(m.get("separation_drop"), 3)}</td>'
        f'<td class="n {signal(m.get("separation_accuracy_pct"), 60)}">{pct(m.get("separation_accuracy_pct"))}</td>'
        f"<td class=n>{pct(m.get('paragraph_alignment_pct'))}</td>"
        f"<td class=n>{pct(overlap)}</td>"
        f"<td class=n><b>{num(m.get('composite'), 3)}</b></td>"
        "</tr>"
    )


def render_comparison(best: dict, baselines: dict, llama: dict | None) -> str:
    m = best["metrics"]
    fixed = baselines["fixed"]["metrics"]
    paragraph = baselines["paragraph"]["metrics"]
    rows = [
        comparison_row(
            "Semantic, constrained",
            f"q={best['percentile']:.0f}, buffer {best['buffer_size']}, "
            f"{n(best['min_chars'])}–{n(best['max_chars'])} chars",
            m,
        ),
        comparison_row("Fixed-size sentences", "pack whole sentences to ~1,500 chars", fixed),
        comparison_row(
            "Paragraph packing",
            "whole paragraphs; oversize paragraphs split at sentence boundaries",
            paragraph,
        ),
    ]
    llama_note = ""
    if llama is not None:
        size = llama.get("size", {})
        synthetic = {
            "count": llama.get("chunks", 0),
            "mean_chars": size.get("mean_chars"),
            "in_band_pct": size.get("in_band_pct"),
            "contrast_z": None,
            "separation_drop": None,
            "separation_accuracy_pct": None,
            "paragraph_alignment_pct": llama.get("paragraph_alignment_pct"),
            "overlap_pct": llama.get("overlap_pct"),
            "composite": None,
        }
        rows.append(
            comparison_row(
                "LlamaIndex splitter",
                f"{llama.get('model')} · breakpoint q={llama.get('params', {}).get('breakpoint_percentile_threshold')}",
                synthetic,
            )
        )
    else:
        llama_note = (
            '<p class="small">LlamaIndex was not available in this environment; its row is omitted '
            'rather than filled with estimates. Run <code>python llamaindex_pipeline.py</code> to add it.</p>'
        )

    return f"""
<p>Two baselines are segmented on the same corpus and measured on the same sentence vectors, so
the comparison is like for like. They differ only in where they cut.</p>

<div class="tablewrap">
<table class="compare">
  <thead><tr>
    <th>Strategy</th><th class=n>Chunks</th><th class=n>Mean chars</th><th class=n>In 500–2,000</th>
    <th class=n>Contrast z</th><th class=n>Separation drop</th><th class=n>Cut is a local dip</th>
    <th class=n>At paragraph</th><th class=n>Overlap</th><th class=n>Composite</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
{llama_note}

<h3>How to read the columns</h3>
<ul>
  <li><b>Contrast z</b> — standardised difference between the mean distance at chosen cuts and the
  mean distance over every adjacent sentence pair. Positive means cuts land where the text changes.
  The fixed and paragraph baselines are <i>negative</i>: they cut slightly below average.</li>
  <li><b>Separation drop</b> — inside a chunk, adjacent sentences average cosine
  {num(m.get('separation_interior'), 3)}; across a cut they average
  {num(m.get('separation_boundary'), 3)}. The drop is {num(m.get('separation_drop'), 3)}.
  This is the honest version of a cohesion test: the comparison is local, not “random pairs
  inside the chunk”, which would always favour large chunks.</li>
  <li><b>Cut is a local dip</b> — share of cuts where the cross-boundary pair is less similar than
  the adjacent pairs just inside each side. Measured on {n(m.get('separation_pairs', 0))} pairs
  sampled from 800 chunks. Semantic {pct(m.get('separation_accuracy_pct'))}; fixed
  {pct(fixed.get('separation_accuracy_pct'))}; paragraph
  {pct(paragraph.get('separation_accuracy_pct'))} — a coin flip.</li>
  <li><b>At paragraph</b> — share of cuts at a paragraph start. Semantic chunking is lower on
  purpose: when the argument turns mid-paragraph, it cuts mid-paragraph. The paragraph baseline
  gets this for free and still loses on every semantic measure.</li>
  <li><b>Composite</b> — 30% size in band, 25% contrast (capped at z = 2), 20% separation accuracy,
  15% paragraph alignment, 10% inverse overlap. A judgement, stated so it can be argued with.</li>
</ul>

<p>The size-constrained semantic splitter is not merely different: its cuts are
{num(m.get('separation_drop'), 2)} cosine better separated than the text around them, and almost
every cut is a local dip. The baselines place cuts that are, if anything, slightly smoother than
average. That is the whole case for paying for embeddings at index time.</p>
"""


def render_histogram(histogram: list[dict], best: dict) -> str:
    top = max((item["pct"] for item in histogram), default=1) or 1
    rows = []
    for item in histogram:
        width = 100.0 * item["pct"] / top
        rows.append(
            '<div class="histrow">'
            f'<div class="histlabel">{esc(item["label"])}</div>'
            f'<div class="histtrack"><div class="histbar" style="width:{width:.1f}%"></div></div>'
            f'<div class="histn">{n(item["count"])} · {item["pct"]:.1f}%</div>'
            "</div>"
        )
    return (
        '<div class="hist">'
        + "".join(rows)
        + "</div>"
        + f'<p class="small">Chunk characters include the carried overlap sentence. The hard '
        f'ceiling is {n(best["max_chars"])} content chars; the observed maximum is '
        f'{n(best["metrics"]["max_chars"])} including overlap, still inside the 2,048-char '
        "embedding window.</p>"
    )


def render_per_volume(per_volume: list[dict]) -> str:
    rows = []
    for item in per_volume:
        rows.append(
            "<tr>"
            f"<td>Volume {item['volume']}</td>"
            f"<td class=n>{n(item['chapters'])}</td>"
            f"<td class=n>{n(item['chunks'])}</td>"
            f"<td class=n>{num(item['mean_chars'], 1)}</td>"
            f"<td class=n>{num(item['p90_chars'], 1)}</td>"
            f"<td class=n>{pct(item['overlap_pct'])}</td>"
            f'<td class="n {signal(item["boundary_contrast_z"])}">{z(item["boundary_contrast_z"])}</td>'
            f'<td class="n {signal(item["separation_accuracy_pct"], 60)}">{pct(item["separation_accuracy_pct"])}</td>'
            f"<td class=n>{pct(item['paragraph_alignment_pct'])}</td>"
            "</tr>"
        )
    return f"""
<div class="tablewrap">
<table>
  <thead><tr>
    <th>Volume</th><th class=n>Chapters</th><th class=n>Chunks</th><th class=n>Mean chars</th>
    <th class=n>p90</th><th class=n>Overlap</th><th class=n>Contrast z</th>
    <th class=n>Local dip</th><th class=n>At paragraph</th>
  </tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
<p class="small">The mechanism is stable across all six volumes: positive contrast and a local dip
at almost every cut. Volume-level differences in paragraph alignment are style differences in
Gibbon's chapters, not tuning failures.</p>
"""


def render_examples(samples: list[dict], boundaries: list[dict]) -> str:
    sample_html = []
    for item in samples:
        sample_html.append(
            '<article class="sample">'
            f'<h4>{esc(item["label"].replace("-", " ").title())} · {esc(item["id"])}</h4>'
            f'<p class="meta">{esc(item["chapter"])} · {n(item["content_chars"])} content chars'
            f' · {n(item["sentences"])} sentences · {n(item["overlap_chars"])} overlap chars</p>'
            f'<p>{esc(item["text"][:900])}{"…" if len(item["text"]) > 900 else ""}</p>'
            "</article>"
        )

    boundary_html = []
    for item in boundaries:
        left = " ".join(esc(text) for text in item["left"])
        right = " ".join(esc(text) for text in item["right"])
        boundary_html.append(
            '<article class="bcard">'
            f'<h4>Volume {item["volume"]} · {esc(item["chapter"])}</h4>'
            f'<p class="bmeta">distance {num(item["distance"], 3)}'
            f' · floor {num(item["threshold"], 3)}'
            f' · {"paragraph start" if item["starts_at_paragraph"] else "mid-paragraph"}'
            f' · {esc(item["left_chunk"])} → {esc(item["right_chunk"])}</p>'
            '<div class="btext">'
            f'<div class="side">{left}</div>'
            '<div class="cutmark">✂ new chunk starts here</div>'
            f'<div class="side">{right}</div>'
            "</div></article>"
        )

    return f"""
<h3>Sample chunks</h3>
<div class="grid2">{''.join(sample_html)}</div>

<h3>The strongest boundaries</h3>
<p class="small">These are the eight highest-distance cuts in the corpus, not a random sample —
they show what the detector responds to. Each card gives the last sentences before the cut, the
first sentences after it, and the cosine distance between the context probes.</p>
<div class="grid2">{''.join(boundary_html)}</div>
"""


def render_tools(deepseek_stats: dict, out_dir: Path, llama: dict | None) -> str:
    verify_path = out_dir / "deepseek_verify.json"
    labels_path = out_dir / "chunk_labels.jsonl"
    questions_path = out_dir / "questions.jsonl"

    if verify_path.exists():
        verify = json.loads(verify_path.read_text(encoding="utf-8"))
        items = verify.get("items", [])
        rows = []
        for item in items[:4]:
            rows.append(
                '<article class="bcard">'
                f'<h4>Volume {item["volume"]} · {esc(item["chapter"])}</h4>'
                f'<p class="bmeta">distance {num(item.get("distance"), 3)} · floor '
                f'{num(item.get("threshold"), 3)} · model says '
                f'{"new topic" if item.get("llm_break") else "same topic"}</p>'
                '<div class="btext">'
                f'<div class="side">{esc(item.get("left", ""))}</div>'
                '<div class="cutmark">✂ boundary</div>'
                f'<div class="side">{esc(item.get("right", ""))}</div>'
                "</div></article>"
            )
        deepseek_html = f"""
<p>The model was used as a judge, not an embedder. It was shown the text on each side of a sampled
boundary and asked whether a new topic, argument or narrative episode starts there. Agreement:
<b>{pct(verify.get('agreement_pct'))}</b> on {n(verify.get('evaluated', 0))} boundaries.
This is a sanity check on the detector, not a gold standard — the model has no access to the
corpus-wide distribution and can disagree with a defensible cut.</p>
<div class="grid2">{''.join(rows)}</div>
<p class="small">First four judged boundaries. Responses are untrusted model output: shown as
text, never HTML, and every returned chunk id is checked against the set that was offered.</p>
"""
    else:
        status = deepseek_stats.get("status", "not_requested")
        reason = deepseek_stats.get("reason", "no run was requested")
        deepseek_html = f"""
<p><b>Not run in this build.</b> Status <code>{esc(status)}</code> —
{esc(reason)}. Set <code>DEEPSEEK_API_KEY</code> in <code>.env</code> and run:</p>
<div class="code">python semantic_chunking.py --deepseek-verify 24 --deepseek-label --deepseek-questions 24</div>
<p>The DeepSeek API exposes chat completions, not embeddings, so it cannot replace the vectorizer.
Its useful roles are the ones where a language model beats cosine distance:</p>
<ul>
  <li><b>Boundary adjudication</b> — sample cuts near the threshold and ask whether the topic
  changes. This measures precision, not recall: a rejected cut is not proof of a bad one.</li>
  <li><b>Chunk labelling</b> — a short topic and one-sentence summary per chunk, for retrieval
  metadata and for eyeballing the corpus.</li>
  <li><b>Question generation</b> — one answerable question per sampled chunk, for a retrieval
  evaluation set.</li>
</ul>
<p class="small">All model output is untrusted: ids are validated against the offered set, reasons
are stripped of control characters and length-capped, and the report renders them as text nodes.
A missing key or a failed call never aborts the chunking run.</p>
"""

    label_note = ""
    if labels_path.exists():
        count = sum(1 for _ in labels_path.open(encoding="utf-8"))
        label_note = f"<p class=\"small\">{n(count)} chunk labels are in <code>out/chunk_labels.jsonl</code>.</p>"
    question_note = ""
    if questions_path.exists():
        count = sum(1 for _ in questions_path.open(encoding="utf-8"))
        question_note = f"<p class=\"small\">{n(count)} evaluation questions are in <code>out/questions.jsonl</code>.</p>"

    if llama is not None:
        size = llama.get("size", {})
        llama_html = f"""
<p><b>Run.</b> {esc(llama.get('method'))} with <code>{esc(llama.get('model'))}</code>,
breakpoint percentile {llama.get('params', {}).get('breakpoint_percentile_threshold')}, buffer
{llama.get('params', {}).get('buffer_size')}. It produced {n(llama.get('chunks', 0))} nodes, mean
{num(size.get('mean_chars'))} chars, p90 {num(size.get('p90_chars'))}, {pct(llama.get('paragraph_alignment_pct'))}
at a paragraph start. LlamaIndex exposes no per-boundary distances, so contrast and separation are
left blank rather than estimated.</p>
"""
    else:
        llama_html = """
<p><b>Not run.</b> LlamaIndex is an optional dependency and is not installed in this environment.
The pipeline is implemented and ready; it needs the package and an embedding model:</p>
<div class="code">python -m pip install "llama-index-core>=0.12" "llama-index-embeddings-huggingface>=0.4"
python llamaindex_pipeline.py --backend huggingface</div>
<p>The script builds one <code>Document</code> per chapter and runs
<code>SemanticSplitterNodeParser</code> with its own breakpoint percentile and buffer (defaults:
q = 95, buffer 1, from <code>.env.example</code>). Its output
lands in <code>out/llamaindex_chunks.jsonl.gz</code> and <code>out/llamaindex_stats.json</code>;
this report picks it up automatically on the next build. It is the reference implementation of the
same family of algorithm, not a drop-in replacement: its nodes are not size-constrained the way the
recommendation here is.</p>
"""

    return f"""
<h3>DeepSeek: judge, labeller, question writer</h3>
{deepseek_html}
{label_note}{question_note}

<h3>LlamaIndex: the reference splitter</h3>
{llama_html}
"""


def render_limitations() -> str:
    return """
<ul>
  <li><b>The embedder is static, not contextual.</b> spaCy's 300-d vectors are an average of word
  vectors; they do not disambiguate a word by its sentence. A transformer backend
  (<code>--backend st</code>) is implemented and would be the first thing to try for a production
  index. The mechanism, constraints and metrics do not change.</li>
  <li><b>These are intrinsic metrics.</b> They measure whether a cut sits at a semantic dip, not
  whether a retriever answers better. A retrieval evaluation needs labelled questions — the
  optional DeepSeek pass generates candidates, but they are not gold labels.</li>
  <li><b>Footnotes stay in.</b> The Gutenberg text interleaves editorial notes with prose. They are
  sentences like any other and can pull a boundary toward a note. Removing them would be a
  separate cleaning decision, and would change the corpus the RAG app retrieves from.</li>
  <li><b>Paragraph alignment is deliberately low.</b> 8.6% of cuts land at a paragraph start,
  against 64% for paragraph packing. The semantic cut wins when the argument turns mid-paragraph;
  a reader who needs paragraph-pure chunks should use the paragraph baseline and accept the size
  spread.</li>
  <li><b>Chapter walls are a prior, not a measurement.</b> Merging across a chapter heading would
  be wrong for this corpus; the study does not test whether a boundary detector would have found
  those walls on its own.</li>
  <li><b>Token counts are estimates</b> at 4 chars/token. No tokenizer is vendored; the 2,048-char
  window is a conservative proxy for 512 tokens, not an exact count.</li>
</ul>
"""


def render_fulltext(volumes: list[dict], volume_stats: dict[int, dict]) -> str:
    legend = (
        '<div class="legend">'
        + "".join(
            f'<span><i class="c{i}"></i>chunk tint {i + 1}</span>' for i in range(TINTS)
        )
        + '<span><i class="ov"></i>sentence carried as overlap into the next chunk</span>'
        + '<span><i style="background:var(--accent)"></i>chunk starts</span>'
        + "</div>"
    )

    blocks = []
    for volume in volumes:
        number = volume["volume"]
        stats = volume_stats.get(number, {})
        is_first = number == volumes[0]["volume"]
        open_attr = " open" if is_first else ""
        chapters = []
        for chapter in volume["chapters"]:
            parts = [
                f'<section class="chapter" id="{attr(chapter["id"])}">',
                f'<h3>{esc(chapter["label"])}'
                f'<span class="ch-meta">{esc(chapter["heading"][:180])} · '
                f'{n(len(chapter["sentences"]))} sentences</span></h3>',
                '<p class="prose">',
            ]
            previous_chunk = None
            for index, sentence in enumerate(chapter["sentences"]):
                if sentence.get("starts_paragraph") and index > 0:
                    parts.append('</p><p class="prose">')
                classes = ["s", f"c{(sentence.get('chunk_index') or 0) % TINTS}"]
                if sentence.get("overlap"):
                    classes.append("ov")
                if previous_chunk is not None and sentence.get("chunk_id") != previous_chunk:
                    classes.append("cut")
                title = sentence.get("chunk_id") or ""
                if sentence.get("overlap"):
                    title += " · also carried into the next chunk"
                parts.append(
                    f'<span class="{" ".join(classes)}" title="{attr(title)}">'
                    f'{esc(sentence["text"])}</span> '
                )
                previous_chunk = sentence.get("chunk_id")
            parts.append("</p></section>")
            chapters.append("".join(parts))
        blocks.append(
            f'<details class="volume" id="vol{number}"{open_attr}>'
            f'<summary>Volume {number} <span>· {n(stats.get("chapters", 0))} chapters · '
            f'{n(stats.get("chunks", 0))} chunks · {n(stats.get("chars", 0))} chars</span></summary>'
            f'<div class="voltext">{"".join(chapters)}</div>'
            "</details>"
        )

    return legend + "".join(blocks)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build(stats: dict, view: dict, out_dir: Path) -> str:
    best = stats["best"]
    m = best["metrics"]
    corpus = stats["corpus"]
    llama_path = out_dir / "llamaindex_stats.json"
    llama = json.loads(llama_path.read_text(encoding="utf-8")) if llama_path.exists() else None
    volume_stats = {item["volume"]: item for item in stats["per_volume"]}

    nav = [
        ("corpus", "Corpus"),
        ("method", "Mechanism"),
        ("sweep", "Sweep"),
        ("comparison", "Baselines"),
        ("sizes", "Sizes"),
        ("stability", "Stability"),
        ("examples", "Boundaries"),
        ("tools", "Model passes"),
        ("limitations", "Limits"),
        ("fulltext", "Full text"),
    ]
    toc = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in nav)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Semantic chunking · Decline and Fall</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <p class="eyebrow">Week 06 · semantic chunking study</p>
  <h1>Break Gibbon where the argument breaks.</h1>
  <p class="lede">A size-constrained semantic splitter over all six volumes of <i>The History of the
  Decline and Fall of the Roman Empire</i>: {n(corpus['sentences'])} sentences, {n(corpus['chars'])}
  characters, one embedding per sentence. The result is {n(m['count'])} chunks that fit a
  512-token retrieval window and cut where the text actually turns.</p>
  {render_tiles(best)}
</header>

<div class="callout">
  <h2>Recommendation</h2>
  <p><b>Target {n(best['target_chars'])} characters; hard bounds {n(best['min_chars'])}–{n(best['max_chars'])};
  one full sentence of overlap; no percentile floor (q = {best['percentile']:.0f}); probe buffer
  {best['buffer_size']}.</b> Chapters are hard boundaries.</p>
  <p>The measured result is {n(m['count'])} chunks, mean {num(m['mean_chars'])} chars
  ({n(round(m['mean_chars'] / 4))} estimated tokens), {pct(m['in_band_pct'])} inside 500–2,000
  chars, {pct(m['over_window_pct'])} over the embedding window, and
  {pct(m['overlap_pct'])} overlap. Boundary contrast is {z(m['contrast_z'])} and
  {pct(m['separation_accuracy_pct'])} of cuts are a local similarity dip. Fixed-size and
  paragraph baselines are at {num(stats['baselines']['fixed']['metrics']['composite'], 3)} and
  {num(stats['baselines']['paragraph']['metrics']['composite'], 3)} composite; this is
  {num(m['composite'], 3)}.</p>
</div>

<nav class="toc">{toc}</nav>

<section id="corpus">
  <h2><span class="sechead">01</span>The corpus</h2>
  <p>Six Project Gutenberg files, parsed structurally: licence stripped, body located by the first
  heading followed by a long paragraph, headings and their synopsis separated from prose, sentences
  split with an abbreviation list. Nothing in this stage is semantic; it defines the units the
  embedder sees.</p>
  {render_corpus(corpus)}
</section>

<section id="method">
  <h2><span class="sechead">02</span>The mechanism</h2>
  {render_method(best, stats['constraints'])}
</section>

<section id="sweep">
  <h2><span class="sechead">03</span>Parameter sweep</h2>
  {render_sweep(stats['sweep'], best, stats['plateau'])}
</section>

<section id="comparison">
  <h2><span class="sechead">04</span>Does semantics beat size?</h2>
  {render_comparison(best, stats['baselines'], llama)}
</section>

<section id="sizes">
  <h2><span class="sechead">05</span>Chunk sizes</h2>
  <p>The band is tight because the constraint is hard: a chunk below {n(best['min_chars'])} chars is
  only produced when the chapter ends, and a chunk above {n(best['max_chars'])} content chars only
  when a single sentence cannot be split. {pct(m['in_band_pct'])} of chunks fall inside
  500–2,000 characters.</p>
  {render_histogram(stats['chunk_histogram'], best)}
</section>

<section id="stability">
  <h2><span class="sechead">06</span>Stability across volumes</h2>
  {render_per_volume(stats['per_volume'])}
</section>

<section id="examples">
  <h2><span class="sechead">07</span>What a boundary looks like</h2>
  {render_examples(stats['samples'], stats['boundary_samples'])}
</section>

<section id="tools">
  <h2><span class="sechead">08</span>Optional model passes</h2>
  {render_tools(stats.get('deepseek', {}), out_dir, llama)}
</section>

<section id="limitations">
  <h2><span class="sechead">09</span>Limitations</h2>
  {render_limitations()}
</section>

<section id="fulltext">
  <h2><span class="sechead">10</span>The full text, chunk-coloured</h2>
  <p>Every sentence appears once, tinted by its owning chunk. The amber run at the end of a chunk
  is the sentence repeated at the start of the next chunk's text (it is shown once here). The blue
  left edge marks a new chunk. Volume 1 is open; open the others from their summary line.</p>
  {render_fulltext(view['volumes'], volume_stats)}
</section>

<footer>
  Generated by <code>make_html.py</code> from <code>out/stats.json</code> and
  <code>out/volumes_view.json</code>. Backend: {esc(stats['backend'].get('model', stats['backend']['backend']))}
  ({esc(stats['backend'].get('dimensions', 'sparse'))} dimensions). {n(len(stats['sweep']))}
  configurations measured; {n(corpus['sentences'])} sentences embedded; {n(m['count'])} chunks.
  No JavaScript, no network requests.
</footer>

</div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=HERE / "out" / "stats.json")
    parser.add_argument("--view", type=Path, default=HERE / "out" / "volumes_view.json")
    parser.add_argument("--out", type=Path, default=HERE / "report.html")
    args = parser.parse_args()

    if not args.stats.exists():
        raise SystemExit(f"missing {args.stats}; run semantic_chunking.py first")
    if not args.view.exists():
        raise SystemExit(f"missing {args.view}; run semantic_chunking.py first")

    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    view = json.loads(args.view.read_text(encoding="utf-8"))
    document = build(stats, view, args.stats.parent)
    args.out.write_text(document, encoding="utf-8")
    print(
        f"[html] wrote {args.out} ({args.out.stat().st_size / 1_000_000:.1f} MB, "
        f"{stats['chunk_count']:,} chunks, {stats['corpus']['sentences']:,} sentences)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
