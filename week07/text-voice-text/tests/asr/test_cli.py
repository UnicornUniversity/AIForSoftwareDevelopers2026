from __future__ import annotations

from pathlib import Path

from src import config
from src.asr.whisperx.__main__ import build_parser, main


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["run"])
    assert args.audio == config.MEETING_WAV_PATH
    assert args.out_dir == config.WHISPERX_OUTPUT_DIR
    assert args.device == "auto"
    assert args.align is True
    assert args.diarize is True
    assert args.min_speakers is None
    assert args.max_speakers is None


def test_parser_accepts_cpu_no_diarize() -> None:
    args = build_parser().parse_args(
        ["run", "--device", "cpu", "--no-diarize", "--no-align"]
    )
    assert args.device == "cpu"
    assert args.diarize is False
    assert args.align is False


def test_run_without_audio_returns_a_clear_error(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("src.asr.whisperx.__main__.load_environment", lambda: None)
    code = main(["run", "--audio", str(tmp_path / "missing.wav")])
    assert code == 1
    err = capsys.readouterr().err
    assert "meeting WAV not found" in err
    assert "src.tts run" in err


def test_main_loads_the_dotenv_file_before_reading_the_token(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        "src.asr.whisperx.__main__.load_environment",
        lambda: calls.append(True),
    )

    main(["run", "--audio", str(tmp_path / "missing.wav")])

    assert calls == [True]
