from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.asr.whisperx.export import (
    ExportError,
    export_all,
    format_timestamp,
    jsonable,
    render_srt,
    render_txt,
    render_vtt,
)
from src.asr.whisperx.normalize import normalize_result


def _transcript():
    raw = {
        "language": "en",
        "segments": [
            {
                "start": 0.0,
                "end": 1.25,
                "text": "Hello there.",
                "speaker": "SPEAKER_00",
                "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
            },
            {
                "start": 3661.5,
                "end": 3662.0,
                "text": "One hour later.",
                "speaker": "SPEAKER_01",
            },
        ],
    }
    return normalize_result(
        raw,
        fixture_id="fx",
        meeting_id="mtg",
        model="small.en",
        manifest={"audio_file": "audio/meeting.wav"},
    )


def test_format_timestamp_srt_and_vtt() -> None:
    assert format_timestamp(0, comma=True) == "00:00:00,000"
    assert format_timestamp(1.25, comma=True) == "00:00:01,250"
    assert format_timestamp(3661.5) == "01:01:01.500"
    assert format_timestamp(-2, comma=True) == "00:00:00,000"


def test_format_timestamp_rejects_non_finite() -> None:
    with pytest.raises(ExportError):
        format_timestamp(float("nan"))


def test_srt_is_numbered_with_comma_timestamps() -> None:
    srt = render_srt(_transcript())
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,250\n")
    assert "SPEAKER_00: Hello there." in srt
    assert "2\n01:01:01,500 --> 01:01:02,000\n" in srt


def test_vtt_starts_with_header_and_dot_timestamps() -> None:
    vtt = render_vtt(_transcript())
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.250" in vtt
    assert "SPEAKER_01: One hour later." in vtt


def test_txt_is_readable_and_labelled() -> None:
    text = render_txt(_transcript())
    assert "# Model: small.en" in text
    assert "# Audio: audio/meeting.wav" in text
    assert "anonymous diarization clusters" in text
    assert "SPEAKER_00: Hello there." in text
    assert "SPEAKER_01: One hour later." in text


def test_export_all_writes_five_files(tmp_path: Path) -> None:
    transcript = _transcript()
    raw = {"segments": [{"start": 0.0, "end": 1.0, "text": "x"}]}
    paths = export_all(tmp_path / "run", transcript, raw)
    assert set(paths) == {"raw", "json", "txt", "srt", "vtt"}
    for path in paths.values():
        assert path.exists() and path.stat().st_size > 0

    normalized = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert normalized["system"] == "whisperx"
    assert normalized["segments"][0]["speaker_label"] == "SPEAKER_00"

    raw_json = json.loads(paths["raw"].read_text(encoding="utf-8"))
    assert raw_json["segments"][0]["text"] == "x"


def test_jsonable_converts_numpy_and_non_finite() -> None:
    payload = {
        "value": np.float32(1.5),
        "count": np.int64(3),
        "bad": float("inf"),
        "path": Path("a/b"),
        "items": (np.float64(2.0),),
    }
    result = jsonable(payload)
    assert result["value"] == pytest.approx(1.5)
    assert result["count"] == 3
    assert result["bad"] is None
    assert result["path"] == str(Path("a/b"))
    assert result["items"] == [2.0]


def test_exports_never_contain_a_token(tmp_path: Path) -> None:
    transcript = _transcript()
    paths = export_all(tmp_path, transcript, {"segments": []})
    for path in paths.values():
        text = path.read_text(encoding="utf-8")
        assert "hf_" not in text
        assert "HF_TOKEN" not in text
