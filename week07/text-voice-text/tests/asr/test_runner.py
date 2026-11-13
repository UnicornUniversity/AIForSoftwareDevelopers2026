from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.asr.whisperx.runner import RunError, RunSettings, run_local_asr, sha256_file
from tests.asr.test_engine import FakeWhisperX
from tests.conftest import write_wav


def _settings(tmp_path: Path, audio: Path, **overrides) -> RunSettings:
    base = dict(
        audio_path=audio,
        out_dir=tmp_path / "out",
        device="cpu",
        model="small.en",
        diarize=True,
    )
    base.update(overrides)
    return RunSettings(**base)


def test_run_writes_all_artifacts_and_manifest(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.25)
    result = run_local_asr(
        _settings(tmp_path, audio),
        env={"HF_TOKEN": "hf_test_secret"},
        module=FakeWhisperX(),
        cuda_available=lambda: False,
    )

    for name in ("manifest", "json", "txt", "srt", "vtt", "raw"):
        assert result.paths[name].exists(), name
    assert result.paths["manifest"].name == "run_manifest.json"

    manifest = json.loads(result.paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["system"] == "whisperx"
    assert manifest["fixture_id"] == "controlled-sdlc-review-en"
    assert manifest["asr"]["device"] == "cpu"
    assert manifest["asr"]["model"] == "small.en"
    assert manifest["diarization"]["enabled"] is True
    assert manifest["diarization"]["hf_token_present"] is True
    assert manifest["diarization"]["labels"] == ["SPEAKER_00"]
    assert manifest["counts"]["segments"] == 1
    assert manifest["versions"]["whisperx"]
    assert manifest["timing_seconds"]["total_pipeline"] >= 0
    assert manifest["audio"]["sha256"] == sha256_file(audio)

    normalized = json.loads(result.paths["json"].read_text(encoding="utf-8"))
    assert normalized["raw_output_file"] == str(result.paths["raw"])
    assert normalized["segments"][0]["speaker_label"] == "SPEAKER_00"

    for path in result.paths.values():
        assert "hf_test_secret" not in path.read_text(encoding="utf-8")


def test_run_without_diarization_marks_unknown(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.2)
    result = run_local_asr(
        _settings(tmp_path, audio, diarize=False),
        env={},
        module=FakeWhisperX(),
        cuda_available=lambda: False,
    )
    manifest = json.loads(result.paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["diarization"]["enabled"] is False
    assert manifest["diarization"]["labels"] == []
    assert any("UNKNOWN" in note for note in manifest["notes"])
    assert result.transcript.segments[0].speaker_label == "UNKNOWN"


def test_missing_audio_explains_the_tts_step(tmp_path: Path) -> None:
    with pytest.raises(RunError) as excinfo:
        run_local_asr(
            _settings(tmp_path, tmp_path / "missing.wav"),
            env={"HF_TOKEN": "hf_test"},
            module=FakeWhisperX(),
            cuda_available=lambda: False,
        )
    message = str(excinfo.value)
    assert "src.tts run" in message
    assert "import-wav" in message


def test_audio_sha_matches_the_unchanged_file(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.2)
    before = sha256_file(audio)
    run_local_asr(
        _settings(tmp_path, audio),
        env={"HF_TOKEN": "hf_test"},
        module=FakeWhisperX(),
        cuda_available=lambda: False,
    )
    assert sha256_file(audio) == before
