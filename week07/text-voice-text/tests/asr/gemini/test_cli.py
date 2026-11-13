from __future__ import annotations

from pathlib import Path

from src import config
from src.asr.gemini.__main__ import build_parser, main
from tests.conftest import write_wav


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["run"])
    assert args.audio == config.MEETING_WAV_PATH
    assert args.out_dir == config.GEMINI_OUTPUT_DIR
    assert args.model == config.TRANSCRIBE_MODEL
    assert args.diarize is True
    assert args.timestamps is True
    assert args.store is False
    assert args.yes is False


def test_parser_accepts_flags() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--no-diarize",
            "--no-timestamps",
            "--auto-language",
            "--yes",
        ]
    )
    assert args.diarize is False
    assert args.timestamps is False
    assert args.auto_language is True


def test_run_without_audio_returns_a_clear_error(
    tmp_path: Path, capsys
) -> None:
    code = main(["run", "--audio", str(tmp_path / "missing.wav"), "--yes"])
    assert code == 1
    err = capsys.readouterr().err
    assert "meeting WAV not found" in err
    assert "src.tts run" in err


def test_check_runs_offline_and_uploads_nothing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("src.asr.gemini.__main__.load_environment", lambda: None)
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)

    code = main(["check", "--audio", str(tmp_path / "missing.wav")])

    assert code == 0
    out = capsys.readouterr().out
    assert f"Model: {config.TRANSCRIBE_MODEL}" in out
    assert "API key present: no" in out
    assert "not found" in out
    assert "does not upload audio" in out


def test_check_has_a_verbose_flag(tmp_path: Path) -> None:
    args = build_parser().parse_args(["check", "--verbose"])
    assert args.verbose is True
    assert args.command == "check"


class _NonInteractiveStdin:
    def isatty(self) -> bool:
        return False


def test_upload_is_refused_without_confirmation(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.2)
    monkeypatch.setattr("sys.stdin", _NonInteractiveStdin())

    code = main(["run", "--audio", str(audio)])

    assert code == 1
    captured = capsys.readouterr()
    assert "Gemini Transcribe confirmation" in captured.out
    assert "Refusing to upload without confirmation" in captured.err
    assert "Not uploaded: ground truth, participant names" in captured.out
