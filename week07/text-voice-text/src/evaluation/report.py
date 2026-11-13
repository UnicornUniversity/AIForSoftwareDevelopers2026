"""Render the comparison document as JSON, Markdown, and a self-contained HTML.

The HTML report is one file with inline CSS: it opens from disk with no server,
no network, and no external assets. Every value is escaped, and the side-by-side
rows highlight substitutions, deletions, and insertions at word level using the
same alignment the metrics use.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.evaluation.text import Op, align, tokenize
from src.schema import write_json

SYSTEM_LABELS = {"whisperx": "WhisperX + pyannote", "gemini": "Gemini Transcribe"}


def _fmt(value: Any, *, places: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def _pct(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value * 100:.1f}%"


def _word_ops(
    reference_text: str, hypothesis_text: str
) -> list[Op]:
    return list(align(tokenize(reference_text), tokenize(hypothesis_text)).ops)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _md_summary(document: Mapping[str, Any]) -> list[str]:
    lines = [
        "| System | Model | WER (verbatim) | WER (fillers removed) | S | D | I | DER | Attribution | Runtime |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        if not block.get("available"):
            lines.append(
                f"| {SYSTEM_LABELS[system]} | not run | — | — | — | — | — | — | — | — |"
            )
            continue
        wer = block["wer_verbatim"]
        normalized = block["wer_filler_removed"]
        der = (block.get("speaker") or {}).get("der") or {}
        attribution = (block.get("speaker") or {}).get("der") or {}
        lines.append(
            "| {label} | `{model}` | {wer} ({errors}/{ref}) | {nwer} | {s} | {d} | "
            "{i} | {der} | {attr} | {runtime}s |".format(
                label=SYSTEM_LABELS[system],
                model=block.get("model"),
                wer=_fmt(wer.get("wer"), places=4),
                errors=wer.get("errors"),
                ref=wer.get("reference_words"),
                nwer=_fmt(normalized.get("wer"), places=4),
                s=wer.get("substitutions"),
                d=wer.get("deletions"),
                i=wer.get("insertions"),
                der=_fmt(der.get("der"), places=4)
                if der.get("available")
                else "unavailable",
                attr=_pct(attribution.get("attribution_accuracy")),
                runtime=_fmt(
                    (block.get("runtime") or {}).get("total_pipeline_seconds"), places=1
                ),
            )
        )
    return lines


def _md_system(system: str, block: Mapping[str, Any]) -> list[str]:
    label = SYSTEM_LABELS[system]
    if not block.get("available"):
        return [
            f"## {label}",
            "",
            f"Not evaluated. {block.get('reason')}",
            "",
        ]

    config = block.get("config") or {}
    runtime = block.get("runtime") or {}
    speaker = block.get("speaker") or {}
    der = speaker.get("der") or {}
    boundaries = speaker.get("boundaries") or {}
    wer = block.get("wer_verbatim") or {}
    normalized = block.get("wer_filler_removed") or {}

    lines = [
        f"## {label}",
        "",
        f"- Model: `{block.get('model')}`",
        f"- Transcript: `{block.get('transcript_file')}`",
        f"- Settings: {', '.join(f'{key}={_fmt(value)}' for key, value in config.items())}",
        "",
        "### Word accuracy",
        "",
        "| Basis | WER | Substitutions | Deletions | Insertions | Correct | Reference words |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        f"| verbatim (primary) | {_fmt(wer.get('wer'), places=4)} | "
        f"{wer.get('substitutions')} | {wer.get('deletions')} | "
        f"{wer.get('insertions')} | {wer.get('correct')} | "
        f"{wer.get('reference_words')} |",
        f"| fillers removed (supplementary) | {_fmt(normalized.get('wer'), places=4)} | "
        f"{normalized.get('substitutions')} | {normalized.get('deletions')} | "
        f"{normalized.get('insertions')} | {normalized.get('correct')} | "
        f"{normalized.get('reference_words')} |",
        "",
        "WER counts words. It says nothing about who said them, when, or whether "
        "the segmentation is usable.",
        "",
        "### Speaker comparison",
        "",
    ]

    if speaker.get("method") == "time_alignment":
        lines += [
            f"- Cluster mapping (speaker ← label): "
            f"{', '.join(f'{key} ← {value}' for key, value in (speaker.get('mapping') or {}).items())}",
            f"- Unmapped clusters: {speaker.get('unmapped_labels') or 'none'}",
            f"- Speakers without a cluster: {speaker.get('unmatched_speakers') or 'none'}",
            f"- Audio matches the reference timeline: "
            f"{_fmt(speaker.get('audio_matches_reference'))}",
        ]
        if der.get("available"):
            lines.append(
                f"- DER: **{_fmt(der.get('der'), places=4)}** "
                f"(missed {der.get('missed_seconds')}s, false alarm "
                f"{der.get('false_alarm_seconds')}s, speaker error "
                f"{der.get('confusion_seconds')}s, reference speech "
                f"{der.get('reference_seconds')}s)"
            )
            lines.append(
                f"- Attribution accuracy inside reference speech: "
                f"{_pct(der.get('attribution_accuracy'))}"
            )
        else:
            lines.append(
                f"- DER: unavailable — {der.get('reason')}. Not reported as zero."
            )
        if boundaries.get("available"):
            lines.append(
                f"- Turn-start boundaries: {boundaries.get('matched')} matched of "
                f"{boundaries.get('reference_boundaries')} reference "
                f"(recall {_pct(boundaries.get('recall'))}), "
                f"precision {_pct(boundaries.get('precision'))} "
                f"within ±{boundaries.get('tolerance_seconds')} s."
            )
            if boundaries.get("missed_seconds"):
                lines.append(
                    f"- Missed boundaries at {boundaries.get('missed_seconds')}"
                )
            if boundaries.get("extra_seconds"):
                lines.append(
                    f"- Extra boundaries at {boundaries.get('extra_seconds')}"
                )
        review_turns = speaker.get("turns_needing_review") or []
        if review_turns:
            lines += [
                "",
                "| Turn | Speaker | Start–end | Correct s | Wrong s | Missing s | Dominant label |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for row in review_turns[:10]:
                lines.append(
                    f"| {row['turn_index']} | {row['speaker']} | "
                    f"{_fmt(row['start'], places=2)}–{_fmt(row['end'], places=2)} | "
                    f"{_fmt(row['correct_seconds'], places=2)} | "
                    f"{_fmt(row['wrong_seconds'], places=2)} | "
                    f"{_fmt(row['missing_seconds'], places=2)} | "
                    f"{row['dominant_label'] or '—'} |"
                )
    else:
        text_attr = speaker.get("text_alignment") or {}
        lines += [
            "- No generated timeline, so the comparison uses **word alignment** "
            "rather than time.",
            f"- Cluster mapping: "
            f"{', '.join(f'{key} ← {value}' for key, value in (text_attr.get('mapping') or {}).items()) or 'none'}",
            f"- Words attributed to the mapped speaker: "
            f"{text_attr.get('correct_words')} of {text_attr.get('total_words')} "
            f"({_pct(text_attr.get('accuracy'))})",
            f"- DER: unavailable — {der.get('reason')}. Not reported as zero.",
        ]

    lines += [
        "",
        "### Runtime",
        "",
        f"- Whole pipeline: {_fmt(runtime.get('total_pipeline_seconds'), places=2)} s "
        f"on {_fmt(runtime.get('audio_duration_seconds'), places=1)} s of audio "
        f"(real-time factor {_fmt(runtime.get('realtime_factor'))})",
        f"- Stages: {runtime.get('stage_seconds')}",
        "",
        "### Usage and cost",
        "",
        f"- Recorded by the run: {block.get('usage', {}).get('recorded') or 'not recorded'}",
        f"- Cost: {block.get('usage', {}).get('cost')}. "
        f"See {block.get('usage', {}).get('pricing_url')} and "
        f"{block.get('usage', {}).get('usage_url')}.",
        "",
    ]

    rows = [
        row
        for row in block.get("rows") or []
        if row["substitutions"] + row["deletions"] + row["insertions"]
    ]
    rows.sort(key=lambda row: -(row["substitutions"] + row["deletions"] + row["insertions"]))
    lines += [
        "### Differences worth reading",
        "",
    ]
    if not rows:
        lines.append("No word differences in this run.")
    else:
        lines += [
            "| Turn | Speaker | Reference | Hypothesis | S | D | I |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in rows[:15]:
            lines.append(
                "| {turn} | {speaker} | {ref} | {hyp} | {s} | {d} | {i} |".format(
                    turn=row["turn_index"],
                    speaker=row["speaker"],
                    ref=_md_cell(row["reference_text"]),
                    hyp=_md_cell(row["hypothesis_text"]) or "_(nothing)_",
                    s=row["substitutions"],
                    d=row["deletions"],
                    i=row["insertions"],
                )
            )
        if len(rows) > 15:
            lines.append(
                f"\n… {len(rows) - 15} more turn(s) with differences; open the HTML "
                "report for the full side-by-side."
            )
    lines.append("")
    return lines


def _md_cell(text: str, *, limit: int = 160) -> str:
    cleaned = " ".join(str(text).split()).replace("|", "\\|")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def build_markdown(document: Mapping[str, Any]) -> str:
    fixture = document["fixture"]
    comparison = document["comparison"]
    method = document["method"]

    lines = [
        "# ASR comparison — WhisperX vs Gemini Transcribe",
        "",
        f"Fixture: **{fixture['title']}** (`{fixture['meeting_id']}`), "
        f"{fixture['turn_count']} turns, {fixture['reference_words']} reference words.",
        "",
        f"_Generated {document['created_utc']}. {fixture['disclaimer']}_",
        "",
        "## Metric basis",
        "",
        f"- Primary WER: {method['primary']}.",
        f"- Supplementary WER: {method['supplementary']}",
        f"- Formula: {method['wer']}.",
        f"- Tokenizer: {method['tokenizer']}.",
        f"- DER basis: {method['der_basis']}.",
        f"- Clusters: {method['clusters']}",
        f"- Scope: {method['wer_scope']}",
        "",
        "## Summary",
        "",
    ]
    lines += _md_summary(document)
    lines += [
        "",
        f"WER difference (Gemini − WhisperX): "
        f"{_fmt(comparison.get('wer_delta_gemini_minus_whisperx'), places=4)}. "
        f"{comparison.get('note')}",
        "",
    ]

    for system in ("whisperx", "gemini"):
        lines += _md_system(system, document["systems"][system])

    lines += ["## Human review checklist", ""]
    for entry in document["review_checklist"]:
        lines.append(f"- [ ] **{entry['item']}** — {entry['why']}")
    lines.append("")

    if document["review_items"]:
        lines += ["## Generated review items", ""]
        for item in document["review_items"]:
            lines.append(
                f"- `{item['severity']}` {SYSTEM_LABELS.get(item['system'], item['system'])}: "
                f"{item['message']}"
            )
        lines.append("")

    lines += ["## Notes", ""]
    for note in document["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root {
  color-scheme: light;
  --bg: #f7f7f5;
  --panel: #ffffff;
  --ink: #1d1d1f;
  --muted: #6b6b70;
  --line: #dcdcd8;
  --accent: #3a5a8c;
  --del-bg: #fde2e1;
  --del-ink: #8f1d18;
  --ins-bg: #e2f4e4;
  --ins-ink: #17602a;
  --warn-bg: #fff4d6;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #141517;
    --panel: #1c1e21;
    --ink: #e8e8ea;
    --muted: #9a9aa2;
    --line: #33363b;
    --accent: #8fb0e0;
    --del-bg: #4a1f1d;
    --del-ink: #ffb4ad;
    --ins-bg: #17351f;
    --ins-ink: #a8e6b3;
    --warn-bg: #3b3216;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 18px 60px; background: var(--bg); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.2rem; margin: 32px 0 10px; }
h3 { font-size: 1rem; margin: 22px 0 8px; }
p, li { color: var(--ink); }
.sub { color: var(--muted); margin: 0 0 20px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin: 12px 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.mono { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 13px; }
.del { background: var(--del-bg); color: var(--del-ink); text-decoration: line-through; border-radius: 3px; padding: 0 2px; }
.ins { background: var(--ins-bg); color: var(--ins-ink); border-radius: 3px; padding: 0 2px; }
.sub-ref { background: var(--del-bg); color: var(--del-ink); border-radius: 3px; padding: 0 2px; }
.sub-hyp { background: var(--ins-bg); color: var(--ins-ink); border-radius: 3px; padding: 0 2px; }
.turn { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.turn:last-child { border-bottom: none; }
.turn-meta { grid-column: 1 / -1; color: var(--muted); font-size: 12.5px; margin-bottom: -4px; }
.side-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.badge { display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px; font-size: 12px; color: var(--muted); margin-right: 6px; }
.warn { background: var(--warn-bg); border-radius: 6px; padding: 8px 10px; }
details summary { cursor: pointer; color: var(--accent); }
@media (max-width: 640px) {
  .turn { grid-template-columns: 1fr; }
  body { padding: 16px 12px 48px; }
}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _html_ops(ops: Sequence[Op], side: str) -> str:
    parts: list[str] = []
    for op in ops:
        if side == "reference":
            if op.kind == "equal":
                parts.append(_e(op.reference))
            elif op.kind == "sub":
                parts.append(f'<span class="sub-ref">{_e(op.reference)}</span>')
            elif op.kind == "del":
                parts.append(f'<span class="del">{_e(op.reference)}</span>')
        else:
            if op.kind == "equal":
                parts.append(_e(op.hypothesis))
            elif op.kind == "sub":
                parts.append(f'<span class="sub-hyp">{_e(op.hypothesis)}</span>')
            elif op.kind == "ins":
                parts.append(f'<span class="ins">{_e(op.hypothesis)}</span>')
    return " ".join(part for part in parts if part)


def _html_rows(block: Mapping[str, Any]) -> str:
    rows = block.get("rows") or []
    parts: list[str] = ['<div class="panel">']
    for row in rows:
        ops = _word_ops(row["reference_text"], row["hypothesis_text"])
        errors = row["substitutions"] + row["deletions"] + row["insertions"]
        marker = (
            f' <span class="badge">{errors} difference(s)</span>' if errors else ""
        )
        parts.append('<div class="turn">')
        parts.append(
            f'<div class="turn-meta">Turn {row["turn_index"]} · {_e(row["speaker"])}'
            f'{marker}</div>'
        )
        parts.append(
            '<div><div class="side-label">Reference</div>'
            f'<div class="mono">{_html_ops(ops, "reference")}</div></div>'
        )
        hypothesis_html = _html_ops(ops, "hypothesis") or "<em>(nothing)</em>"
        parts.append(
            '<div><div class="side-label">Hypothesis</div>'
            f'<div class="mono">{hypothesis_html}</div></div>'
        )
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _html_summary(document: Mapping[str, Any]) -> str:
    header = (
        "<tr><th>System</th><th>WER verbatim</th><th>WER fillers removed</th>"
        "<th>S</th><th>D</th><th>I</th><th>DER</th><th>Runtime</th></tr>"
    )
    rows: list[str] = []
    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        label = SYSTEM_LABELS[system]
        if not block.get("available"):
            rows.append(
                f"<tr><td>{_e(label)}</td><td colspan='7'>not run</td></tr>"
            )
            continue
        wer = block["wer_verbatim"]
        normalized = block["wer_filler_removed"]
        der = (block.get("speaker") or {}).get("der") or {}
        rows.append(
            "<tr>"
            f"<td>{_e(label)}<br><span class='mono'>{_e(block.get('model'))}</span></td>"
            f"<td>{_e(_fmt(wer.get('wer'), places=4))}</td>"
            f"<td>{_e(_fmt(normalized.get('wer'), places=4))}</td>"
            f"<td>{_e(wer.get('substitutions'))}</td>"
            f"<td>{_e(wer.get('deletions'))}</td>"
            f"<td>{_e(wer.get('insertions'))}</td>"
            f"<td>{_e(_fmt(der.get('der'), places=4)) if der.get('available') else 'unavailable'}</td>"
            f"<td>{_e(_fmt((block.get('runtime') or {}).get('total_pipeline_seconds'), places=1))} s</td>"
            "</tr>"
        )
    return f"<div class='panel'><table>{header}{''.join(rows)}</table></div>"


def _html_speaker(system: str, block: Mapping[str, Any]) -> str:
    speaker = block.get("speaker") or {}
    if not speaker:
        return ""
    parts = [f"<h3>{_e(SYSTEM_LABELS[system])}</h3>"]
    if speaker.get("method") == "time_alignment":
        mapping = speaker.get("mapping") or {}
        parts.append(
            "<p>Cluster mapping: "
            + ", ".join(
                f"<span class='mono'>{_e(label)}</span> → {_e(name)}"
                for name, label in mapping.items()
            )
            + "</p>"
        )
        der = speaker.get("der") or {}
        if der.get("available"):
            parts.append(
                "<p>DER <strong>{}</strong> — missed {} s, false alarm {} s, "
                "speaker error {} s over {} s of reference speech.</p>".format(
                    _e(_fmt(der.get("der"), places=4)),
                    _e(der.get("missed_seconds")),
                    _e(der.get("false_alarm_seconds")),
                    _e(der.get("confusion_seconds")),
                    _e(der.get("reference_seconds")),
                )
            )
        else:
            parts.append(
                f"<p>DER unavailable — {_e(der.get('reason'))}. "
                "It is not reported as zero.</p>"
            )
        boundaries = speaker.get("boundaries") or {}
        if boundaries.get("available"):
            parts.append(
                "<p>Turn boundaries matched within ±{} s: {}/{} "
                "(recall {}, precision {}).</p>".format(
                    _e(boundaries.get("tolerance_seconds")),
                    _e(boundaries.get("matched")),
                    _e(boundaries.get("reference_boundaries")),
                    _e(_pct(boundaries.get("recall"))),
                    _e(_pct(boundaries.get("precision"))),
                )
            )
        turns = speaker.get("turns_needing_review") or []
        if turns:
            rows = "".join(
                "<tr><td>{}</td><td>{}</td><td>{:.2f}–{:.2f}</td>"
                "<td>{:.2f}</td><td>{:.2f}</td><td>{}</td></tr>".format(
                    row["turn_index"],
                    _e(row["speaker"]),
                    row["start"],
                    row["end"],
                    row["correct_seconds"],
                    row["wrong_seconds"],
                    _e(row["dominant_label"] or "—"),
                )
                for row in turns
            )
            parts.append(
                "<p>Most uncertain turns:</p><table><tr><th>Turn</th><th>Speaker</th>"
                "<th>Start–end</th><th>Correct s</th><th>Wrong s</th>"
                f"<th>Label</th></tr>{rows}</table>"
            )
    else:
        text_attr = speaker.get("text_alignment") or {}
        parts.append(
            "<p>No generated timeline, so words rather than time were compared. "
            f"Words attributed correctly: {_e(text_attr.get('correct_words'))} of "
            f"{_e(text_attr.get('total_words'))} "
            f"({_e(_pct(text_attr.get('accuracy')))}). DER is unavailable.</p>"
        )
    return "".join(parts)


def build_html(document: Mapping[str, Any]) -> str:
    fixture = document["fixture"]
    method = document["method"]

    checklist = "".join(
        f"<li><strong>{_e(entry['item'])}</strong> — {_e(entry['why'])}</li>"
        for entry in document["review_checklist"]
    )
    review_items = "".join(
        "<li><span class='badge'>{}</span> {}: {}</li>".format(
            _e(item["severity"]),
            _e(SYSTEM_LABELS.get(item["system"], item["system"])),
            _e(item["message"]),
        )
        for item in document["review_items"]
    ) or "<li>No generated flags.</li>"

    sections: list[str] = []
    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        if not block.get("available"):
            sections.append(
                f"<h2>{_e(SYSTEM_LABELS[system])}</h2>"
                f"<div class='panel warn'>Not evaluated. {_e(block.get('reason'))}</div>"
            )
            continue
        sections.append(f"<h2>{_e(SYSTEM_LABELS[system])}</h2>")
        sections.append(_html_speaker(system, block))
        sections.append("<h3>Side by side</h3>")
        sections.append(_html_rows(block))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASR comparison — WhisperX vs Gemini Transcribe</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>ASR comparison — WhisperX vs Gemini Transcribe</h1>
<p class="sub">{_e(fixture['title'])} · {_e(fixture['meeting_id'])} ·
{_e(fixture['turn_count'])} turns · {_e(fixture['reference_words'])} reference words ·
generated {_e(document['created_utc'])}</p>
<p class="sub"><span class="badge">verbatim primary</span>
<span class="badge">fillers removed = supplementary</span>
<span class="badge">clusters, not labels</span>
<span class="badge">DER only with a real timeline</span></p>

<div class="panel warn">{_e(fixture['disclaimer'])}</div>

<h2>Summary</h2>
{_html_summary(document)}
<p class="sub">{_e(method['wer_scope'])}</p>

{''.join(sections)}

<h2>Human review checklist</h2>
<div class="panel"><ul>{checklist}</ul></div>

<h2>Generated review items</h2>
<div class="panel"><ul>{review_items}</ul></div>

<h2>Notes</h2>
<div class="panel"><ul>{''.join(f'<li>{_e(note)}</li>' for note in document['notes'])}</ul></div>

<p class="sub">Metric basis: {_e(method['primary'])} · Tokenizer: {_e(method['tokenizer'])} · DER basis: {_e(method['der_basis'])}</p>
</main>
</body>
</html>
"""


def write_reports(document: Mapping[str, Any], out_dir: Path) -> dict[str, Path]:
    """Write ``comparison.json``, ``comparison.md``, and ``comparison.html``."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "comparison.json"
    md_path = out_dir / "comparison.md"
    html_path = out_dir / "comparison.html"

    write_json(json_path, document)
    md_path.write_text(build_markdown(document), encoding="utf-8")
    html_path.write_text(build_html(document), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "html": html_path}
