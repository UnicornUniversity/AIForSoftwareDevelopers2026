from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import config
from src.tts import __main__ as cli
from src.tts.audio import inspect_wav
from tests.conftest import FakeTTSClient, write_wav


def test_main_loads_the_dotenv_file(tmp_path: Path, capsys, monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        "src.tts.__main__.load_environment", lambda: calls.append(True)
    )

    code = cli.main(["plan", "--segments-dir", str(tmp_path / "segments")])

    assert code == 0
    assert calls == [True]


def test_plan_command_is_offline(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "plan",
            "--segments-dir",
            str(tmp_path / "segments"),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "Voice plan" in output
    assert "Kore" in output and "Puck" in output and "Charon" in output
    assert "turn_001_ANN.wav" in output
    assert "no three-speaker request" in output.lower()


def test_synthesize_without_confirmation_in_noninteractive_shell(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    code = cli.main(
        [
            "synthesize",
            "--segments-dir",
            str(tmp_path / "segments"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Refusing to call the cloud API" in captured.err


def test_synthesize_without_key_fails_clearly(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    code = cli.main(
        [
            "synthesize",
            "--yes",
            "--segments-dir",
            str(tmp_path / "segments"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "no Gemini API key found" in captured.err


def test_assemble_without_segments_fails_clearly(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "assemble",
            "--segments-dir",
            str(tmp_path / "segments"),
            "--audio-out",
            str(tmp_path / "meeting.wav"),
            "--manifest-out",
            str(tmp_path / "meeting_manifest.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 4
    assert "Assembly failed" in captured.err


def test_status_command(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [
            "status",
            "--segments-dir",
            str(tmp_path / "segments"),
            "--audio-out",
            str(tmp_path / "meeting.wav"),
            "--manifest-out",
            str(tmp_path / "m.json"),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "Turns: 39" in output
    assert "Meeting WAV: not found" in output
    assert "API key present:" in output


def test_import_wav_command(tmp_path: Path, capsys) -> None:
    source = write_wav(tmp_path / "external.wav", seconds=0.3)
    destination = tmp_path / "audio" / "meeting.wav"
    manifest = tmp_path / "audio" / "meeting_manifest.json"
    code = cli.main(
        [
            "import-wav",
            str(source),
            "--audio-out",
            str(destination),
            "--manifest-out",
            str(manifest),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert destination.read_bytes() == source.read_bytes()
    assert "DER must be reported as unavailable" in output
    assert json.loads(manifest.read_text(encoding="utf-8"))["source"] == "imported"


def test_run_command_end_to_end_offline(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    # Replace only the vendor client; the rest of the pipeline is real.
    monkeypatch.setattr(
        cli, "GeminiTTSClient", lambda **kwargs: FakeTTSClient()
    )
    secret = "super-secret-test-key"
    monkeypatch.setenv(config.GEMINI_API_KEY_ENV, secret)

    segments = tmp_path / "segments"
    audio = tmp_path / "audio" / "meeting.wav"
    manifest = tmp_path / "audio" / "meeting_manifest.json"
    code = cli.main(
        [
            "run",
            "--yes",
            "--segments-dir",
            str(segments),
            "--audio-out",
            str(audio),
            "--manifest-out",
            str(manifest),
            "--turn-pause-ms",
            "100",
            "--section-pause-ms",
            "200",
        ]
    )
    output = capsys.readouterr().out
    assert code == 0, output
    assert audio.exists()
    assert manifest.exists()
    assert inspect_wav(audio).duration_seconds > 0
    assert len(json.loads(manifest.read_text(encoding="utf-8"))["timeline"]) == 39

    # No generated artifact may contain the key.
    for path in [*segments.rglob("*"), audio, manifest]:
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


def test_run_command_partial_limit_skips_assembly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(
        cli, "GeminiTTSClient", lambda **kwargs: FakeTTSClient()
    )
    code = cli.main(
        [
            "run",
            "--yes",
            "--limit",
            "2",
            "--segments-dir",
            str(tmp_path / "segments"),
            "--audio-out",
            str(tmp_path / "meeting.wav"),
            "--manifest-out",
            str(tmp_path / "m.json"),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "skipping assembly" in output.lower()
    assert not (tmp_path / "meeting.wav").exists()
