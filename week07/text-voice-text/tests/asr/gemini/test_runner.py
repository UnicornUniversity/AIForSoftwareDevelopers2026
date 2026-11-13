from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.asr.common import sha256_file
from src.asr.gemini.client import TranscribeResult
from src.asr.gemini.runner import (
    AudioProbe,
    RunError,
    TranscribeSettings,
    check_duration_limits,
    run_cloud_asr,
)
from tests.conftest import write_wav

RAW = {
    "id": "interaction-1",
    "status": "completed",
    "output_text": "Hello there.",
    "steps": [
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "text": "Hello there.",
                    "annotations": [
                        {
                            "type": "word_info",
                            "text": "Hello",
                            "speaker": "spk_1",
                            "start_offset": "0.100s",
                            "end_offset": "0.400s",
                        },
                        {
                            "type": "word_info",
                            "text": "there.",
                            "speaker": "spk_1",
                            "start_offset": "0.400s",
                            "end_offset": "0.800s",
                        },
                        {
                            "type": "word_info",
                            "text": "Hi.",
                            "speaker": "spk_2",
                            "start_offset": "1.000s",
                            "end_offset": "1.300s",
                        },
                    ],
                }
            ],
        }
    ],
}


class FakeTranscribeClient:
    def __init__(self, raw=None, *, file_deleted=True) -> None:
        self.raw = raw or RAW
        self.file_deleted = file_deleted
        self.calls = []

    def transcribe(self, audio_path, options, *, progress=None):
        self.calls.append((Path(audio_path), options))
        if progress:
            progress("fake upload")
        return TranscribeResult(
            raw=self.raw,
            interaction_id="interaction-1",
            uploaded_file="files/fake-123",
            file_deleted=self.file_deleted,
            timings={"upload": 0.1, "transcribe": 0.2, "delete": 0.0},
        )


def _settings(tmp_path: Path, audio: Path, **overrides) -> TranscribeSettings:
    base = dict(
        audio_path=audio,
        out_dir=tmp_path / "out",
        model="gemini-3.5-transcribe",
        diarize=True,
    )
    base.update(overrides)
    return TranscribeSettings(**base)


def test_run_writes_all_artifacts_and_manifest(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=2.0)
    fake = FakeTranscribeClient()

    result = run_cloud_asr(
        _settings(tmp_path, audio),
        client=fake,
        env={"GEMINI_API_KEY": "secret-value"},
    )

    for name in ("manifest", "json", "txt", "srt", "vtt", "raw"):
        assert result.paths[name].exists(), name
    assert result.paths["raw"].name == "gemini_raw.json"

    manifest = json.loads(result.paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["system"] == "gemini"
    assert manifest["asr"]["model"] == "gemini-3.5-transcribe"
    assert manifest["asr"]["verbatim"] is True
    assert manifest["privacy"]["uploaded_file"] == "files/fake-123"
    assert manifest["privacy"]["file_deleted"] is True
    assert manifest["audio"]["sha256"] == sha256_file(audio)
    assert manifest["counts"]["segments"] == 2
    assert manifest["counts"]["words"] == 3
    assert manifest["counts"]["speaker_labels"] == 2
    assert manifest["timing_seconds"]["total_pipeline"] >= 0

    normalized = json.loads(result.paths["json"].read_text(encoding="utf-8"))
    assert normalized["raw_output_file"] == str(result.paths["raw"])
    assert [s["speaker_label"] for s in normalized["segments"]] == [
        "spk_1",
        "spk_2",
    ]

    for path in result.paths.values():
        assert "secret-value" not in path.read_text(encoding="utf-8")


def test_only_audio_and_options_reach_the_client(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=1.0)
    fake = FakeTranscribeClient()

    run_cloud_asr(_settings(tmp_path, audio), client=fake)

    assert len(fake.calls) == 1
    sent_path, options = fake.calls[0]
    assert sent_path == audio
    payload = json.dumps(
        {
            "model": options.model,
            "language_codes": list(options.language_codes),
            "custom_vocabulary": list(options.custom_vocabulary),
        }
    )
    for forbidden in ("Ann", "Bob", "Greg", "Hawkins", "Atlas", "ground"):
        assert forbidden not in payload


def test_missing_audio_explains_the_tts_step(tmp_path: Path) -> None:
    with pytest.raises(RunError) as excinfo:
        run_cloud_asr(
            _settings(tmp_path, tmp_path / "missing.wav"),
            client=FakeTranscribeClient(),
        )
    message = str(excinfo.value)
    assert "src.tts run" in message
    assert "import-wav" in message


def test_no_diarization_marks_unknown(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=1.0)
    raw = dict(RAW)
    raw["steps"] = [
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "text": "Hello there.",
                    "annotations": [
                        {
                            "type": "word_info",
                            "text": "Hello",
                            "start_offset": "0.100s",
                            "end_offset": "0.400s",
                        }
                    ],
                }
            ],
        }
    ]
    result = run_cloud_asr(
        _settings(tmp_path, audio, diarize=False),
        client=FakeTranscribeClient(raw),
    )
    manifest = result.manifest
    assert manifest["asr"]["diarize"] is False
    assert result.transcript.segments[0].speaker_label == "UNKNOWN"
    assert any("UNKNOWN" in note for note in manifest["notes"])


def test_too_long_audio_is_refused_before_any_upload(
    tmp_path: Path, monkeypatch
) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.5)
    fake = FakeTranscribeClient()

    monkeypatch.setattr(
        "src.asr.gemini.runner.probe_wav",
        lambda _path: AudioProbe(
            duration_seconds=1900.0,
            sample_rate=24_000,
            channels=1,
            size_bytes=123,
        ),
    )

    with pytest.raises(RunError) as excinfo:
        run_cloud_asr(_settings(tmp_path, audio), client=fake)
    assert "30 minutes" in str(excinfo.value)
    assert "truncated" in str(excinfo.value)
    assert fake.calls == []


def test_duration_limits_allow_the_short_fixture() -> None:
    check_duration_limits(
        240.0, diarize=True, word_timestamps=True
    )


def test_undeleted_file_is_reported_in_the_manifest(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.5)
    result = run_cloud_asr(
        _settings(tmp_path, audio),
        client=FakeTranscribeClient(file_deleted=False),
    )
    assert result.manifest["privacy"]["file_deleted"] is False
    assert any("could not be deleted" in note for note in result.manifest["notes"])
