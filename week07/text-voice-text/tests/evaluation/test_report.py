from __future__ import annotations

import copy
import json
from pathlib import Path

from src.evaluation.compare import build_comparison
from src.evaluation.report import build_html, build_markdown, write_reports
from src.fixtures import load_fixture
from tests.evaluation.fakes import (
    DEFAULT_LABELS,
    make_transcript,
    turn_spans,
    write_meeting_manifest,
    write_system,
)


def _document(tmp_path: Path) -> dict:
    fixture = load_fixture()
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)

    whisperx = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    write_system(tmp_path / "whisperx", whisperx, audio_file=str(audio))

    gemini = make_transcript(
        fixture,
        spans,
        DEFAULT_LABELS["gemini"],
        system="gemini",
        model="gemini-3.5-transcribe",
        mutate_turn=2,
        mutate=lambda text: text.replace("catalog", "catalogue", 1),
    )
    write_system(tmp_path / "gemini", gemini, audio_file=str(audio))

    return build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )


def test_markdown_reports_both_metrics_and_checklist(tmp_path: Path) -> None:
    markdown = build_markdown(_document(tmp_path))

    assert "WER (verbatim)" in markdown
    assert "fillers removed" in markdown
    assert "WhisperX + pyannote" in markdown
    assert "Gemini Transcribe" in markdown
    assert "Human review checklist" in markdown
    assert "Tokenizer:" in markdown
    assert "DER" in markdown


def test_html_is_self_contained_and_has_side_by_side_rows(tmp_path: Path) -> None:
    html = build_html(_document(tmp_path))

    assert html.startswith("<!doctype html>")
    assert "viewport" in html
    assert 'class="turn"' in html
    assert "sub-ref" in html and "sub-hyp" in html
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "<script" not in html


def test_html_escapes_untrusted_text(tmp_path: Path) -> None:
    document = _document(tmp_path)
    tampered = copy.deepcopy(document)
    tampered["fixture"]["title"] = '<script>alert("x")</script>'

    html = build_html(tampered)

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_write_reports_creates_three_files(tmp_path: Path) -> None:
    document = _document(tmp_path)
    paths = write_reports(document, tmp_path / "comparison")

    assert set(paths) == {"json", "markdown", "html"}
    for path in paths.values():
        assert path.exists(), path
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["comparison"]["wer_verbatim"]["whisperx"] == 0.0


def test_unavailable_system_is_shown_not_hidden(tmp_path: Path) -> None:
    fixture = load_fixture()
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    whisperx = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    write_system(tmp_path / "whisperx", whisperx, audio_file=str(audio))

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )
    html = build_html(document)

    assert "Not evaluated" in html
    assert "src.asr.gemini run" in html
