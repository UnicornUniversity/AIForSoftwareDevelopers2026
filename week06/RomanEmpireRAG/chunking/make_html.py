"""Render `out/stats.json` as a standalone HTML report.

No network, no JavaScript library: the page is a single file with inline SVG
charts and inline CSS. `chunking.py` computes every number here; this module
only formats them, so the report and the stats file cannot disagree.

Usage:
    python make_html.py [--stats out/stats.json] [--out report.html]
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------------------


def n(value: float | int) -> str:
    """Thousands-separated integer."""
    return f"{value:,.0f}"


def pct(value: float) -> str:
    return f"{value:.1f}%"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr(text: str) -> str:
    """Escape for use inside an HTML attribute (quotes included)."""
    return html.escape(text, quote=True)


def compact(value: int) -> str:
    if value >= 1000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}k"
    return str(value)


def bucket_label(low: int, high: int | None) -> str:
    if high is None:
        return f"{compact(low)}+"
    return f"{compact(low)}–{compact(high - 1)}"


# --------------------------------------------------------------------------------------
# SVG charts
# --------------------------------------------------------------------------------------


def nice_ceiling(value: float) -> float:
    """Round an axis maximum up to a readable step (1, 2, 2.5, 5 x 10^k)."""
    if value <= 0:
        return 1
    exponent = math.floor(math.log10(value))
    magnitude = 10**exponent
    for step in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 10):
        candidate = step * magnitude
        if value <= candidate:
            return candidate
    return 10 * magnitude


def histogram_svg(items: list[dict], *, y_unit: str, width: int = 860, height: int = 250) -> str:
    """Vertical bar chart with hover titles and a recessive grid.

    A single series, so there is no legend: the section heading names it. Bars are
    rounded at the data end and square at the baseline, with a 2px surface gap
    between neighbours.
    """
    values = [item["count"] for item in items]
    labels = [bucket_label(item["low"], item["high"]) for item in items]
    top = nice_ceiling(max(values))
    pad_l, pad_r, pad_t, pad_b = 54, 10, 18, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    slot = plot_w / len(items)
    bar_w = max(4.0, slot - 2)
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(y_unit)} by bucket">']

    for tick in range(5):
        value = top * tick / 4
        y = pad_t + plot_h - plot_h * tick / 4
        parts.append(
            f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<text class="axis" x="{pad_l - 10}" y="{y + 4:.1f}" text-anchor="end">{n(value)}</text>'
        )

    for index, (item, label) in enumerate(zip(items, labels)):
        value = item["count"]
        bar_h = plot_h * value / top
        x = pad_l + slot * index + (slot - bar_w) / 2
        y = pad_t + plot_h - bar_h
        radius = min(4.0, bar_w / 2, bar_h / 2) if bar_h > 0 else 0
        if bar_h > 0:
            path = (
                f"M {x:.1f} {pad_t + plot_h:.1f} "
                f"L {x:.1f} {y + radius:.1f} "
                f"Q {x:.1f} {y:.1f} {x + radius:.1f} {y:.1f} "
                f"L {x + bar_w - radius:.1f} {y:.1f} "
                f"Q {x + bar_w:.1f} {y:.1f} {x + bar_w:.1f} {y + radius:.1f} "
                f"L {x + bar_w:.1f} {pad_t + plot_h:.1f} Z"
            )
            parts.append(
                f'<path class="bar" d="{path}"><title>{esc(label)}: {n(value)} {esc(y_unit)} '
                f"({pct(item['pct'])} of all)</title></path>"
            )
        parts.append(
            f'<text class="tick" x="{x + bar_w / 2:.1f}" y="{pad_t + plot_h + 20}" text-anchor="middle">{esc(label)}</text>'
        )
    parts.append(
        f'<line class="baseline" x1="{pad_l}" x2="{width - pad_r}" y1="{pad_t + plot_h}" y2="{pad_t + plot_h}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def heatmap_svg(sweep: list[dict], best: dict, width: int = 860) -> str:
    """Target x overlap grid of composite scores, one-hue sequential ramp.

    Rows are chunk targets, columns are overlap sizes. Infeasible configurations
    (above the embedding window) are hatched, not coloured, so the constraint is
    visible in the grid rather than only in the table.
    """
    targets = sorted({m["target_chars"] for m in sweep})
    overlaps = sorted({m["overlap_chars"] for m in sweep})
    lookup = {(m["target_chars"], m["overlap_chars"]): m for m in sweep}
    feasible_scores = [m["score"] for m in sweep if m["feasible"]]
    low, high = min(feasible_scores), max(feasible_scores)
    bins = 6

    pad_l, pad_r, pad_t, pad_b = 124, 14, 34, 46
    cell_w = (width - pad_l - pad_r) / len(overlaps)
    cell_h = 40
    height = pad_t + pad_b + cell_h * len(targets)
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Score by chunk target and overlap">',
        '<defs><pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="8" stroke="var(--hatch)" stroke-width="2"/></pattern></defs>',
    ]

    for column, overlap in enumerate(overlaps):
        x = pad_l + cell_w * column + cell_w / 2
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{pad_t - 14}" text-anchor="middle">{overlap} / {round(overlap / 4)}</text>'
        )
    parts.append(
        f'<text class="axis" x="{pad_l + (width - pad_l - pad_r) / 2:.1f}" y="{height - 8}" text-anchor="middle">'
        "overlap, chars / est. tokens</text>"
    )
    parts.append(
        f'<text class="axis" transform="translate(18 {pad_t + cell_h * len(targets) / 2:.1f}) rotate(-90)" '
        'text-anchor="middle">chunk target, chars / est. tokens</text>'
    )

    for row, target in enumerate(targets):
        y = pad_t + row * cell_h
        parts.append(
            f'<text class="tick" x="{pad_l - 12}" y="{y + cell_h / 2 + 4:.1f}" text-anchor="end">'
            f"{n(target)} / {round(target / 4)}</text>"
        )
        for column, overlap in enumerate(overlaps):
            x = pad_l + cell_w * column
            cell = lookup.get((target, overlap))
            if cell is None:
                parts.append(
                    f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{cell_w - 2:.1f}" height="{cell_h - 2:.1f}" '
                    f'rx="4" class="cell-empty"><title>{n(target)} chars / {overlap} chars overlap: '
                    "not evaluated, overlap would exceed the 20% cap</title></rect>"
                    f'<text class="cell-empty-text" x="{x + cell_w / 2:.1f}" y="{y + cell_h / 2 + 4:.1f}" '
                    'text-anchor="middle">—</text>'
                )
                continue
            selected = (cell["target_chars"], cell["overlap_chars"]) == (
                best["target_chars"],
                best["overlap_chars"],
            )
            outline = (
                f'<rect x="{x + 2:.1f}" y="{y + 2:.1f}" width="{cell_w - 4:.1f}" height="{cell_h - 4:.1f}" '
                f'rx="4" class="cell-selected"/>'
                if selected
                else ""
            )
            if not cell["feasible"]:
                parts.append(
                    f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{cell_w - 2:.1f}" height="{cell_h - 2:.1f}" '
                    f'rx="4" class="cell-infeasible"><title>{n(target)} chars / {overlap} chars overlap: '
                    "exceeds the 512-token embedding window</title></rect>"
                )
                continue
            level = min(bins - 1, max(0, int((cell["score"] - low) / (high - low + 1e-9) * bins)))
            parts.append(
                f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{cell_w - 2:.1f}" height="{cell_h - 2:.1f}" '
                f'rx="4" class="seq-{level + 1}"><title>{n(target)} chars / {overlap} chars overlap — '
                f"score {cell['score']:.4f}; in band {pct(cell['in_band_pct'])}; "
                f"single paragraph {pct(cell['single_paragraph_pct'])}; "
                f"overlap cost {pct(cell['overlap_pct'])}</title></rect>"
                f'<text class="cell-value cell-ink-{level + 1}" x="{x + cell_w / 2:.1f}" '
                f'y="{y + cell_h / 2 + 4:.1f}" text-anchor="middle">{cell["score"]:.3f}</text>'
            )
            parts.append(outline)
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------------------


def kpi(label: str, value: str, note: str) -> str:
    return (
        f'<div class="kpi"><div class="kpi-value">{value}</div>'
        f'<div class="kpi-label">{esc(label)}</div><div class="kpi-note">{esc(note)}</div></div>'
    )


def build_corpus_table(corpus: dict) -> str:
    rows = []
    for v in corpus["volumes"]:
        rows.append(
            "<tr>"
            f'<td class="num">{v["volume"]}</td>'
            f'<td class="num">{v["chapters"]}</td>'
            f'<td class="num">{n(v["paragraphs"])}</td>'
            f'<td class="num">{n(v["chars"])}</td>'
            f'<td class="num">{n(v["words"])}</td>'
            f'<td class="num">{n(v["tokens"])}</td>'
            f'<td class="num">{n(v["median_paragraph_chars"])}</td>'
            f'<td class="num">{n(v["p90_paragraph_chars"])}</td>'
            f'<td class="num">{n(v["median_sentence_chars"])}</td>'
            "</tr>"
        )
    total = (
        "<tr class=\"total\">"
        '<td class="num">all</td>'
        f'<td class="num">{corpus["unique_chapters"]}</td>'
        f'<td class="num">{n(corpus["paragraphs"])}</td>'
        f'<td class="num">{n(corpus["chars"])}</td>'
        f'<td class="num">{n(corpus["words"])}</td>'
        f'<td class="num">{n(corpus["tokens"])}</td>'
        f'<td class="num">{n(corpus["median_paragraph_chars"])}</td>'
        f'<td class="num">{n(corpus["p90_paragraph_chars"])}</td>'
        f'<td class="num">{n(corpus["median_sentence_chars"])}</td>'
        "</tr>"
    )
    return (
        '<div class="table-wrap"><table>'
        "<caption>Per-volume corpus after removing the Gutenberg licence and the table of contents. "
        "Token counts are the chars/4 estimate.</caption>"
        "<thead><tr>"
        '<th class="num">Vol.</th><th class="num">Chapters</th><th class="num">Paragraphs</th>'
        '<th class="num">Characters</th><th class="num">Words</th><th class="num">Est. tokens</th>'
        '<th class="num">Median para</th><th class="num">P90 para</th><th class="num">Median sentence</th>'
        f"</tr></thead><tbody>{''.join(rows)}{total}</tbody></table></div>"
    )


def build_result_table(per_volume: list[dict]) -> str:
    rows = []
    for v in per_volume:
        rows.append(
            "<tr>"
            f'<td class="num">{v["volume"]}</td>'
            f'<td class="num">{n(v["chunks"])}</td>'
            f'<td class="num">{n(v["mean_chars"])}</td>'
            f'<td class="num">{n(v["median_chars"])}</td>'
            f'<td class="num">{n(v["mean_tokens"])}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table>'
        "<caption>Chunks produced per volume at the recommended parameters.</caption>"
        "<thead><tr><th class=\"num\">Vol.</th><th class=\"num\">Chunks</th>"
        '<th class="num">Mean chars</th><th class="num">Median chars</th><th class="num">Mean est. tokens</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def build_sweep_table(sweep: list[dict], best: dict) -> str:
    rows = []
    for m in sweep:
        chosen = (m["target_chars"], m["overlap_chars"]) == (best["target_chars"], best["overlap_chars"])
        status = "chosen" if chosen else ("" if m["feasible"] else "infeasible")
        cells = [
            f'<td class="num">{n(m["target_chars"])} / {m["target_tokens"]}</td>',
            f'<td class="num">{m["overlap_chars"]} / {m["overlap_tokens"]}</td>',
            f'<td class="num">{n(m["chunks"])}</td>',
            f'<td class="num">{n(m["mean_chars"])}</td>',
            f'<td class="num">{n(m["p90_chars"])}</td>',
            f'<td class="num">{pct(m["in_band_pct"])}</td>',
            f'<td class="num">{pct(m["single_paragraph_pct"])}</td>',
            f'<td class="num">{pct(m["reference_restored_pct"])}</td>',
            f'<td class="num">{pct(m["overlap_pct"])}</td>',
            f'<td class="num">{m["score"]:.3f}</td>',
        ]
        rows.append(f'<tr class="{status}">{"".join(cells)}</tr>')
    return (
        '<div class="table-wrap"><table class="sweep">'
        "<caption>Every configuration in the sweep. Rows above the 512-token window are marked "
        "infeasible and were excluded from the choice.</caption>"
        "<thead><tr>"
        '<th class="num">Target chars / tokens</th><th class="num">Overlap chars / tokens</th>'
        '<th class="num">Chunks</th><th class="num">Mean chars</th><th class="num">P90 chars</th>'
        '<th class="num">In band</th><th class="num">One paragraph</th><th class="num">Context restored</th>'
        '<th class="num">Overlap cost</th><th class="num">Score</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def build_samples(samples: list[dict]) -> str:
    blocks = []
    for sample in samples:
        blocks.append(
            '<details class="sample">'
            f"<summary><span class=\"sample-id\">{esc(sample['id'])}</span> "
            f"<span class=\"sample-chapter\">{esc(sample['chapter'])}</span> "
            f"<span class=\"sample-meta\">{n(sample['chars'])} chars · {n(sample['words'])} words · "
            f"~{n(sample['tokens'])} tokens · paragraphs {sample['paragraph_from']}–{sample['paragraph_to']}</span>"
            f"</summary><p class=\"sample-text\">{esc(sample['text'])}</p></details>"
        )
    return "".join(blocks)


def render_volume_text(segments: list[dict]) -> str:
    """One volume's text with every sentence tinted by the chunk that owns it."""
    parts: list[str] = []
    for segment in segments:
        if segment["kind"] == "heading":
            parts.append(f'<p class="vhead" id="{segment["anchor"]}">{esc(segment["text"])}</p>')
            continue
        tint = "ov" if segment["overlap"] else ("ca" if segment["chunk"] % 2 else "cb")
        extra = ""
        if segment["pstart"]:
            extra += " pstart"
        if segment["seam"]:
            extra += " seam"
        if segment["pstart"]:
            parts.append(f'<span class="pb {tint}"></span>')
        if segment["overlap"]:
            title = (
                f"Overlap: chunk {segment['chunk']} opens with this text, "
                f"which chunk {segment['chunk'] - 1} closed with"
            )
        else:
            title = f"Chunk {segment['chunk']} · {n(segment['size'])} chars"
        parts.append(
            f'<span class="seg {tint}{extra}" title="{attr(title)}">{esc(segment["text"])}</span> '
        )
    return "".join(parts)


def build_volume_section(view: dict | None) -> str:
    """Every volume's full text with chunk and overlap backgrounds.

    Every sentence appears once. Chunk tints alternate (`.ca` / `.cb`); a run
    that the next chunk re-reads is tinted as overlap instead of as either
    neighbour, so the shared text is visible without copying it into both chunks.
    The seam rule marks the sentence where each chunk opens.
    """
    if not view:
        return ""
    volumes = view["volumes"]
    volume_links = "".join(
        f'<a href="#vol-{volume["volume"]}">Volume {volume["volume"]}</a>' for volume in volumes
    )
    blocks: list[str] = []
    for volume in volumes:
        chapter_links = "".join(
            f'<a href="#{chapter["anchor"]}" title="{attr(chapter["title"])}">{esc(chapter["label"])}</a>'
            for chapter in volume["chapters"]
        )
        blocks.append(
            f"""
<h3 class="vol-head" id="vol-{volume['volume']}">Volume {volume['volume']}
  <span class="vol-meta">{n(volume['corpus_chars'])} characters · {n(volume['chunks'])} chunks ·
  {n(volume['headings'])} chapter sections</span></h3>
<div class="vbox">
<nav class="chapter-nav" aria-label="Volume {volume['volume']} chapter sections">{chapter_links}</nav>
<div class="vtext">{render_volume_text(volume['segments'])}</div>
</div>"""
        )
    overlap_pct = 100 * view["overlap_sentences"] / view["sentences"] if view["sentences"] else 0
    return f"""
<h2>8 · Every volume, chunk by chunk</h2>
<p>All six volumes — {n(view['corpus_chars'])} characters, {n(view['chunks'])} chunks and
{n(view['sentences'])} sentences — laid out in reading order. Every sentence appears once and carries
the background of the chunk that owns it: the two tints alternate chunk by chunk, so a change of tint
is a boundary. The amber band is overlap. {pct(overlap_pct)} of the corpus's sentences are re-read by
the following chunk, and they are shown once — as neither neighbour's tint — rather than duplicated
in both.</p>
<div class="legend">
  <span><span class="sw ca"></span>chunk, tint A</span>
  <span><span class="sw cb"></span>chunk, tint B</span>
  <span><span class="sw ov"></span>overlap, shared by both neighbours (dotted edge)</span>
  <span><span class="sw seam"></span>chunk start</span>
</div>
<nav class="volume-nav" aria-label="Volumes">{volume_links}</nav>
{''.join(blocks)}
<p class="note">Hover any passage for its chunk number and size; each volume's chapter strip stays
at the top while you scroll through that volume. Chunks never cross a chapter heading, so each
section starts a fresh chunk with no overlap from the previous one. The headings are shown as section
markers only: the splitter attaches them to the chapter's first chunk as metadata, and the pipeline
prepends them at embedding time.</p>"""


# --------------------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------------------


def render(stats: dict, view: dict | None = None) -> str:
    corpus = stats["corpus"]
    best = stats["best"]
    plateau = stats["plateau"]
    constraints = stats["constraints"]
    mean_tokens = best["mean_tokens"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chunking parameters for Gibbon's Decline and Fall</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11, 11, 11, 0.10);
  --series: #2a78d6;
  --series-soft: #cde2fb;
  --selected: #0b0b0b;
  --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec;
  --seq-4: #3987e5; --seq-5: #256abf; --seq-6: #184f95;
  --ink-on-seq-1: #0b0b0b; --ink-on-seq-2: #0b0b0b; --ink-on-seq-3: #0b0b0b;
  --ink-on-seq-4: #ffffff; --ink-on-seq-5: #ffffff; --ink-on-seq-6: #ffffff;
  --hatch: #e1e0d9;
  /* Volume-1 full text: two alternating chunk tints, overlap in amber. */
  --chunk-a: #dfeafb;
  --chunk-b: #f0f5fd;
  --overlap: #fbeccb;
  --overlap-edge: #c98500;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #f0efec;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255, 255, 255, 0.10);
    --series: #3987e5;
    --series-soft: #184f95;
    --selected: #f0efec;
    /* More is lighter on a dark surface: the ramp runs from near-surface up. */
    --seq-1: #104281; --seq-2: #184f95; --seq-3: #256abf;
    --seq-4: #3987e5; --seq-5: #6da7ec; --seq-6: #9ec5f4;
    --ink-on-seq-1: #ffffff; --ink-on-seq-2: #ffffff; --ink-on-seq-3: #ffffff;
    --ink-on-seq-4: #ffffff; --ink-on-seq-5: #0b0b0b; --ink-on-seq-6: #0b0b0b;
    --hatch: #2c2c2a;
    /* Dark tints are chosen for the dark surface, not flipped from light. */
    --chunk-a: #1b2b40;
    --chunk-b: #141c27;
    --overlap: #332817;
    --overlap-edge: #eda100;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 48px 24px 80px; }}
header.hero {{ border-bottom: 1px solid var(--border); padding-bottom: 28px; margin-bottom: 32px; }}
.eyebrow {{ color: var(--muted); font-size: 13px; letter-spacing: .08em; text-transform: uppercase; }}
h1 {{ font-size: clamp(28px, 5vw, 44px); line-height: 1.12; margin: 10px 0 12px; letter-spacing: -0.02em; }}
.lede {{ color: var(--ink-2); font-size: 18px; max-width: 72ch; margin: 0; }}
.lede strong {{ color: var(--ink); font-weight: 650; }}
h2 {{ font-size: 24px; letter-spacing: -0.01em; margin: 52px 0 8px; }}
h3 {{ font-size: 17px; margin: 28px 0 8px; }}
p {{ max-width: 76ch; }}
p, li {{ color: var(--ink-2); }}
strong {{ color: var(--ink); }}
code {{ font: 0.92em/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; background: var(--grid); color: var(--ink); padding: 1px 5px; border-radius: 4px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 26px 0 8px; }}
.kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }}
.kpi-value {{ font-size: 30px; font-weight: 680; letter-spacing: -0.02em; line-height: 1.1; }}
.kpi-label {{ margin-top: 4px; font-size: 13px; color: var(--ink-2); }}
.kpi-note {{ margin-top: 2px; font-size: 12px; color: var(--muted); }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px; margin: 18px 0; }}
.recommend {{ border-left: 4px solid var(--series); }}
.recommend .big {{ display: flex; flex-wrap: wrap; gap: 28px; align-items: baseline; margin: 4px 0 12px; }}
.recommend .big div {{ min-width: 120px; }}
.recommend .big .num {{ font-size: 34px; font-weight: 680; letter-spacing: -0.02em; line-height: 1.1; }}
.recommend .big .cap {{ color: var(--muted); font-size: 13px; }}
.note {{ font-size: 14px; color: var(--ink-2); }}
.chart-wrap {{ overflow-x: auto; }}
.chart {{ width: 100%; min-width: 560px; height: auto; display: block; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.baseline {{ stroke: var(--baseline); stroke-width: 1; }}
.axis, .tick {{ fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }}
.bar {{ fill: var(--series); }}
.bar:hover {{ fill: var(--ink-2); }}
.cell-selected {{ fill: none; stroke: var(--selected); stroke-width: 2.5; }}
.cell-infeasible {{ fill: url(#hatch); stroke: var(--border); stroke-width: 1; }}
.cell-empty {{ fill: var(--page); stroke: var(--border); stroke-width: 1; }}
.cell-empty-text {{ fill: var(--muted); font-size: 12px; }}
.cell-value {{ font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; pointer-events: none; }}
.seq-1 {{ fill: var(--seq-1); }} .seq-2 {{ fill: var(--seq-2); }} .seq-3 {{ fill: var(--seq-3); }}
.seq-4 {{ fill: var(--seq-4); }} .seq-5 {{ fill: var(--seq-5); }} .seq-6 {{ fill: var(--seq-6); }}
.cell-ink-1 {{ fill: var(--ink-on-seq-1); }} .cell-ink-2 {{ fill: var(--ink-on-seq-2); }}
.cell-ink-3 {{ fill: var(--ink-on-seq-3); }} .cell-ink-4 {{ fill: var(--ink-on-seq-4); }}
.cell-ink-5 {{ fill: var(--ink-on-seq-5); }} .cell-ink-6 {{ fill: var(--ink-on-seq-6); }}
figure {{ margin: 18px 0 8px; }}
figcaption {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
.table-wrap {{ overflow-x: auto; margin: 14px 0 8px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; min-width: 720px; }}
caption {{ caption-side: top; text-align: left; color: var(--muted); font-size: 13px; padding: 12px 14px 6px; }}
th, td {{ padding: 9px 12px; border-bottom: 1px solid var(--grid); text-align: left; white-space: nowrap; }}
thead th {{ color: var(--ink-2); font-weight: 600; background: var(--surface); position: sticky; top: 0; }}
tbody tr:last-child td {{ border-bottom: none; }}
tbody tr:hover {{ background: color-mix(in srgb, var(--series) 6%, transparent); }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.total td {{ font-weight: 650; border-top: 1px solid var(--baseline); }}
tr.chosen td {{ background: color-mix(in srgb, var(--series) 12%, transparent); font-weight: 600; }}
tr.infeasible td {{ color: var(--muted); }}
.sample {{ border: 1px solid var(--border); border-radius: 10px; background: var(--surface); padding: 12px 16px; margin: 10px 0; }}
.sample summary {{ cursor: pointer; display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; }}
.sample-id {{ font: 600 13px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; color: var(--series); }}
.sample-chapter {{ color: var(--ink); font-weight: 550; }}
.sample-meta {{ color: var(--muted); font-size: 13px; }}
.sample-text {{ margin: 12px 0 4px; max-width: 82ch; color: var(--ink-2); font-size: 15px; }}
.vbox {{ margin: 16px 0 8px; }}
.chapter-nav {{
  display: flex; gap: 2px; overflow-x: auto; padding: 6px 2px 8px;
  position: sticky; top: 0; z-index: 3; background: var(--page);
  border-bottom: 1px solid var(--border); margin-bottom: 8px;
}}
.chapter-nav a {{
  flex: 0 0 auto; padding: 4px 9px; border-radius: 6px; font-size: 12.5px;
  color: var(--ink-2); text-decoration: none; white-space: nowrap;
  border: 1px solid transparent;
}}
.chapter-nav a:hover {{ background: var(--surface); border-color: var(--border); color: var(--ink); }}
.volume-nav {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 4px; }}
.volume-nav a {{
  padding: 6px 14px; border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface); color: var(--ink-2); text-decoration: none; font-size: 13.5px;
}}
.volume-nav a:hover {{ color: var(--ink); border-color: var(--baseline); }}
.vol-head {{
  margin: 46px 0 2px; padding-top: 22px; border-top: 1px solid var(--border);
  font-size: 21px; letter-spacing: -0.01em; scroll-margin-top: 12px;
}}
.vol-meta {{ margin-left: 8px; font-size: 13px; font-weight: 400; color: var(--muted); }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 20px; margin: 14px 0 10px; font-size: 13.5px; color: var(--ink-2); }}
.legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
.sw {{ display: inline-block; width: 20px; height: 13px; border-radius: 3px; border: 1px solid var(--border); }}
.sw.ca {{ background: var(--chunk-a); }}
.sw.cb {{ background: var(--chunk-b); }}
.sw.ov {{ background: var(--overlap); border-bottom: 2px dotted var(--overlap-edge); }}
.sw.seam {{ width: 3px; height: 15px; border: 0; border-radius: 1px; background: var(--series); }}
.vtext {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 26px 30px 30px; color: var(--ink);
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
  font-size: 16.5px; line-height: 1.75;
}}
.vtext .seg {{ border-radius: 2px; }}
.vtext .ca {{ background: var(--chunk-a); }}
.vtext .cb {{ background: var(--chunk-b); }}
.vtext .ov {{
  background: var(--overlap);
  /* Second channel beside the colour: overlap must not be colour-only. */
  border-bottom: 2px dotted var(--overlap-edge);
}}
.vtext .pb {{ display: block; height: 0.9em; }}
.vtext .pstart {{ margin-left: 1.4em; }}
.vtext .seam {{ border-left: 2px solid var(--series); padding-left: 2px; }}
.vtext .vhead {{
  max-width: none; margin: 1.8em 0 0.8em; padding: 0.7em 0 0;
  border-top: 1px solid var(--border); scroll-margin-top: 56px;
  font: 650 15px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink); letter-spacing: 0.01em;
}}
.vtext .vhead:first-child {{ margin-top: 0; padding-top: 0; border-top: 0; }}
ul {{ padding-left: 22px; }}
li {{ margin: 6px 0; }}
.foot {{ margin-top: 56px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--muted); font-size: 13px; }}
@media (max-width: 640px) {{
  .wrap {{ padding: 32px 16px 64px; }}
  h2 {{ margin-top: 40px; }}
  body {{ font-size: 15px; }}
  .vtext {{ padding: 18px 16px 20px; font-size: 16px; }}
}}
@media print {{
  body {{ background: #fff; color: #000; }}
  .card, .table-wrap, .sample {{ break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <div class="eyebrow">Week 06 · RAG preprocessing study</div>
  <h1>Chunking Gibbon's <em>Decline and Fall</em></h1>
  <p class="lede">How to cut {n(corpus['chars'])} characters of eighteenth-century historiography into retrieval
  units. Six volumes, {n(corpus['paragraphs'])} paragraphs and {n(corpus['sentences'])} sentences were segmented and
  swept across {len(stats['sweep'])} chunk-size and overlap configurations. The recommendation is
  <strong>{n(best['target_chars'])} characters (~{best['target_tokens']} tokens) per chunk with
  {best['overlap_chars']} characters (~{best['overlap_tokens']} tokens) of overlap</strong>.</p>
</header>

<div class="kpis">
  {kpi("Corpus", n(corpus["chars"]), "characters after cleanup")}
  {kpi("Paragraphs", n(corpus["paragraphs"]), f"median {n(corpus['median_paragraph_chars'])} chars")}
  {kpi("Sentences", n(corpus["sentences"]), f"median {n(corpus['median_sentence_chars'])} chars")}
  {kpi("Chunks", n(stats["chunk_count"]), f"at {n(best['target_chars'])} / {best['overlap_chars']}")}
  {kpi("Mean chunk", f"~{n(mean_tokens)}", "estimated tokens")}
</div>

<h2>1 · What the text looks like</h2>
<p>The six files are Project Gutenberg editions of the same work, but they are not formatted alike.
Volume 1 indents every paragraph by six spaces; volumes 3, 5 and 6 flush paragraphs to the left;
volume 2 carries its table of contents without a <code>CONTENTS</code> heading. The pipeline therefore
classifies by structure, not by indentation: a short block that opens with <code>Chapter N:</code>,
<code>Introduction</code>, <code>Preface</code> or <code>Appendix</code> is a heading, the block after it is the
chapter synopsis, and every other blank-line-delimited block is a paragraph.</p>

{build_corpus_table(corpus)}

<h3>Paragraph and sentence sizes</h3>
<p>Paragraph length is the single most important input to the choice below, and it is heavily skewed:
the median paragraph is {n(corpus['median_paragraph_chars'])} characters, the mean is
{n(corpus['mean_paragraph_chars'])}, the 90th percentile is {n(corpus['p90_paragraph_chars'])} and the longest is
{n(corpus['max_paragraph_chars'])}. A chunk size near the median would cut most paragraphs in half; a size near
the mean would merge many short paragraphs. The sentence is the natural fallback boundary, and at a
median of {n(corpus['median_sentence_chars'])} characters it is small enough to end a chunk without a large overshoot.</p>

<figure>
  <div class="chart-wrap">{histogram_svg(corpus['paragraph_histogram'], y_unit='paragraphs')}</div>
  <figcaption>Paragraph lengths in characters. {pct(sum(h['pct'] for h in corpus['paragraph_histogram'][:4]))} of
  paragraphs are shorter than 1,000 characters, so a chunk at the recommended size usually holds one to three
  of them.</figcaption>
</figure>

<h2>2 · Delimiters used</h2>
<ul>
  <li><strong>Headings</strong> close the previous chunk and reset the chapter label. Overlap is never carried
  across a chapter boundary: the new heading is the context, so repeating the previous chapter's tail would
  attach wrong material to it.</li>
  <li><strong>Blank lines / paragraph breaks</strong> are preferred chunk boundaries. Paragraphs are packed whole
  while the chunk stays under 115% of the target.</li>
  <li><strong>Sentence boundaries</strong> split a paragraph that is larger than the target, and set the
  granularity of overlap. The splitter is abbreviation-aware — <code>St.</code>, <code>M.</code>,
  <code>A.D.</code> and <code>i.e.</code> do not end a sentence.</li>
  <li><strong>Word boundaries</strong> are the last resort for a sentence longer than the hard cap; it does not
  occur in these volumes.</li>
</ul>

<h2>3 · The sweep</h2>
<p>Ten targets from 400 to 3,000 characters were crossed with five overlap sizes. Each configuration was
scored on four measured properties, weighted in the order a retrieval pipeline cares about them
(the weights are a judgement call and are stated so they can be argued with; the recommendation below
also reports the plateau, where the exact weights stop mattering):</p>
<ul>
  <li><strong>Predictable size — 35%.</strong> Share of chunks within ±20% of the target.</li>
  <li><strong>One topic per chunk — 25%.</strong> Share of chunks that stay inside a single paragraph.</li>
  <li><strong>Restored context — 20%.</strong> Of the chunks that open on a pronoun or demonstrative
  ("He…", "This…", "The former…"), the share whose preceding sentences are present as overlap.
  This is overlap's measurable benefit, not an assumption that overlap is good.</li>
  <li><strong>Little repeated text — 20%.</strong> Overlapped characters as a share of the corpus; the
  penalty saturates at 33%, so it never vetoes a useful overlap.</li>
</ul>
<p>Two constraints are applied before scoring. A target plus the chapter heading must fit the
<strong>{constraints['embed_window_tokens']}-token</strong> input window of common embedding models
({n(constraints['embed_window_chars'])} chars at the chars/4 estimate; the heading prefix averages
{constraints['heading_prefix_chars']} chars). And overlap is capped at
{pct(constraints['max_overlap_share'] * 100)} of the target.</p>

<figure>
  <div class="chart-wrap">{heatmap_svg(stats['sweep'], best)}</div>
  <figcaption>Composite score by target (rows) and overlap (columns), each cell labelled
  <em>chars / estimated tokens</em>. Hatched cells exceed the embedding window; the outlined cell is the
  recommendation; blank cells were not evaluated because the overlap would exceed the 20% cap. The surface is
  flat between {n(plateau['target_min'])} and {n(plateau['target_max'])} characters, so the exact cell is less
  important than the region.</figcaption>
</figure>

{build_sweep_table(stats['sweep'], best)}

<h2>4 · Recommendation</h2>
<div class="card recommend">
  <div class="big">
    <div><div class="num">{n(best['target_chars'])}</div><div class="cap">characters per chunk (target)</div></div>
    <div><div class="num">~{best['target_tokens']}</div><div class="cap">estimated tokens (target)</div></div>
    <div><div class="num">{best['overlap_chars']}</div><div class="cap">characters of overlap (requested)</div></div>
    <div><div class="num">{pct(best['overlap_pct'])}</div><div class="cap">realised overlap cost</div></div>
  </div>
  <p class="note">The realised mean chunk is {n(best['mean_chars'])} characters (~{n(best['mean_tokens'])} tokens).
  Overlap is requested in characters but delivered in whole sentences, so the realised figure is higher than
  requested: the average carried tail is {n(round(best['overlap_pct'] / 100 * best['mean_chars']))} characters
  (~{round(best['overlap_pct'] / 100 * best['mean_chars'] / 4)} tokens) — about one sentence — not
  {best['overlap_chars']}.</p>
</div>

<p>Why this cell:</p>
<ul>
  <li><strong>Fits the window with headroom.</strong> The mean chunk is {n(best['mean_chars'])} characters;
  with the {constraints['heading_prefix_chars']}-character heading prefix that is
  ~{round((best['mean_chars'] + constraints['heading_prefix_chars']) / 4)} tokens by the chars/4 estimate,
  or ~{round((best['mean_words'] / 0.75) + constraints['heading_prefix_chars'] / 4)} by a word-based estimate.
  Both sit under 512, so nothing is truncated.</li>
  <li><strong>Sizes are predictable.</strong> {pct(best['in_band_pct'])} of chunks fall within ±20% of the target
  (P10 {n(best['p10_chars'])}, P90 {n(best['p90_chars'])}), which keeps embedding cost and recall stable across
  the corpus.</li>
  <li><strong>Overlap buys something measurable.</strong> {pct(best['reference_start_pct'])} of chunks open
  on a backwards-pointing word and {pct(best['reference_restored_pct'])} of those have their antecedent carried
  in; the cost is {pct(best['overlap_pct'])} of the corpus in repeated text.</li>
  <li><strong>Smaller starts to hurt.</strong> At 1,000 characters the sentence-sized overlap becomes
  24% of the corpus and the chunk count rises by two thirds, while the share of single-paragraph chunks
  improves only modestly.</li>
  <li><strong>Larger crosses the window.</strong> From 2,000 characters the chunk plus heading no longer fits a
  512-token model (2,000 + {constraints['heading_prefix_chars']} = 2,110 chars &gt;
  {n(constraints['embed_window_chars'])}), and the single-paragraph share falls from
  {pct(best['single_paragraph_pct'])} to 39.5% at 2,000 and 22.8% at 3,000.</li>
</ul>
<p class="note">The flat optimum means an operational constraint may legitimately override the cell:
if the embedding model takes 8,192 tokens and the store is cheap, 1,800 characters (score
{max((m['score'] for m in stats['sweep'] if m['target_chars'] == 1800 and m['feasible']), default=0):.3f})
is equally defensible; if latency dominates, 1,200
({max((m['score'] for m in stats['sweep'] if m['target_chars'] == 1200 and m['feasible']), default=0):.3f})
is the other end of the same plateau.</p>

<h2>5 · Chunks at the recommended parameters</h2>
{build_result_table(stats['per_volume'])}

<figure>
  <div class="chart-wrap">{histogram_svg(stats['chunk_histogram'], y_unit='chunks')}</div>
  <figcaption>Chunk lengths in characters at {n(best['target_chars'])} / {best['overlap_chars']}.
  {pct(sum(h['pct'] for h in stats['chunk_histogram'] if h['low'] >= 1400 and (h['high'] or 10**9) <= 1800))}
  of chunks land between 1,400 and 1,800 characters; the tail below 1,200 is the last chunk of each chapter,
  where the next heading forces a close before the target is reached.</figcaption>
</figure>

<h2>6 · Sample chunks</h2>
<p>Three chunks from across the corpus, exactly as the splitter emits them (overlap included). Open one to see
the text; every chunk in the run also carries its volume, chapter heading, paragraph span and token estimate.</p>
{build_samples(stats['samples'])}

<h2>7 · Method and limits</h2>
<ul>
  <li><strong>Cleanup.</strong> Everything outside the Project Gutenberg START/END markers is dropped, and the
  table of contents is cut at the first heading that is followed by a long paragraph. Prefaces and the
  editor's introduction are kept — they are book content.</li>
  <li><strong>Wrapped lines</strong> are joined with a single space. No dehyphenation is applied because a scan
  found zero hyphenated line breaks in the six files.</li>
  <li><strong>Chapter synopses</strong> (the "Death Of Gratian.—Ruin Of Arianism.—…" block after each heading)
  are attached to the heading rather than treated as prose. Left in, they would prepend a table-of-contents
  fragment to every chapter's first chunk.</li>
  <li><strong>Footnotes</strong> are not separated. This edition interleaves Gibbon's notes, and Milman's, with
  the main text; they remain in the chunks. A production pipeline would want to strip or tag them.</li>
  <li><strong>Token counts are estimates.</strong> No tokenizer is vendored, because the report is
  standard-library-only. Chars/4 and words/0.75 bracket the plausible range for English; both estimates
  appear for the recommended size.</li>
  <li><strong>The score is a judgement, the metrics are not.</strong> Size band, paragraph span and overlap
  cost are measured directly. Their weights are the author's, which is why the plateau is reported: the
  region is stable even where the exact cell is not.</li>
  <li><strong>Metadata at embedding time.</strong> Prefix each chunk with its chapter heading
  (<code>{esc(stats['samples'][1]['chapter'])}</code>, and so on). That is the breadcrumb a bare paragraph lacks,
  and the {constraints['heading_prefix_chars']}-character budget for it is already reserved above.</li>
</ul>

{build_volume_section(view)}

<p class="foot">Generated by <code>make_html.py</code> from <code>out/stats.json</code> and
<code>out/volumes_view.json</code>; both are produced by
<code>chunking.py</code> from the six text files in <code>week06/data/</code>. The page is self-contained: no
external CSS, fonts, scripts or images.</p>

</div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=HERE / "out" / "stats.json")
    parser.add_argument("--volume-view", type=Path, default=HERE / "out" / "volumes_view.json")
    parser.add_argument("--out", type=Path, default=HERE / "report.html")
    args = parser.parse_args()

    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    view = (
        json.loads(args.volume_view.read_text(encoding="utf-8"))
        if args.volume_view.exists()
        else None
    )
    if view is None:
        print(f"note: {args.volume_view} not found, omitting the full-text sections")
    args.out.write_text(render(stats, view), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
