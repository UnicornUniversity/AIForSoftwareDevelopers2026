from __future__ import annotations

from pathlib import Path

from src import config
from src.evaluation.__main__ import build_parser, main
from src.fixtures import load_fixture
from tests.evaluation.fakes import (
    DEFAULT_LABELS,
    make_transcript,
    turn_spans,
    write_meeting_manifest,
    write_system,
)


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["build"])
    assert args.whisperx_dir == config.WHISPERX_OUTPUT_DIR
    assert args.gemini_dir == config.GEMINI_OUTPUT_DIR
    assert args.out_dir == config.COMPARISON_OUTPUT_DIR
    assert args.meeting_manifest == config.MEETING_MANIFEST_PATH


def test_build_without_outputs_explains_what_to_run(
    tmp_path: Path, capsys
) -> None:
    code = main(
        [
            "build",
            "--whisperx-dir",
            str(tmp_path / "none-whisperx"),
            "--gemini-dir",
            str(tmp_path / "none-gemini"),
            "--out-dir",
            str(tmp_path / "out"),
            "--meeting-manifest",
            str(tmp_path / "none.json"),
        ]
    )

    assert code == 1
    err = capsys.readouterr().err
    assert "src.asr.whisperx run" in err
    assert "src.asr.gemini run" in err


def test_build_writes_reports_and_prints_the_table(
    tmp_path: Path, capsys
) -> None:
    fixture = load_fixture()
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    write_system(
        tmp_path / "whisperx",
        make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"]),
        audio_file=str(audio),
    )
    write_system(
        tmp_path / "gemini",
        make_transcript(
            fixture, spans, DEFAULT_LABELS["gemini"], system="gemini"
        ),
        audio_file=str(audio),
    )

    code = main(
        [
            "build",
            "--whisperx-dir",
            str(tmp_path / "whisperx"),
            "--gemini-dir",
            str(tmp_path / "gemini"),
            "--out-dir",
            str(tmp_path / "comparison"),
            "--meeting-manifest",
            str(tmp_path / "meeting_manifest.json"),
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "WER" in out
    assert "does not measure speaker diarization" in out
    for name in ("comparison.json", "comparison.md", "comparison.html"):
        assert (tmp_path / "comparison" / name).exists(), name
