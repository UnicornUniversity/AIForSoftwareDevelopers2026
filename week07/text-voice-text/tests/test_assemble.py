from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tts.assemble import (
    assemble_meeting,
    describe_segment_set,
    validate_manifest_against_script,
    wav_summary,
)
from src.tts.audio import inspect_wav
from src.tts.segments import (
    SegmentError,
    load_segment_manifest,
    plan_segments,
    synthesize_segments,
)
from tests.conftest import FakeTTSClient


def _build_segments(fixture, tmp_path: Path, **client_kwargs) -> Path:
    plans = plan_segments(fixture.script, fixture.metadata)
    segments = tmp_path / "segments"
    synthesize_segments(
        plans,
        segments,
        FakeTTSClient(**client_kwargs),
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    return segments


def test_assemble_writes_meeting_and_manifest(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    output = tmp_path / "meeting.wav"
    manifest_path = tmp_path / "meeting_manifest.json"
    manifest = assemble_meeting(
        fixture.script, segments, output, output_manifest=manifest_path
    )
    assert output.exists()
    assert manifest_path.exists()
    info = inspect_wav(output)
    assert info.sample_rate == 24_000
    assert info.channels == 1
    assert manifest.duration_seconds == pytest.approx(info.duration_seconds)
    assert len(manifest.timeline) == 39
    assert manifest.source == "gemini_api"


def test_duration_includes_turn_and_section_pauses(
    fixture, tmp_path: Path
) -> None:
    segments = _build_segments(fixture, tmp_path)
    segment_manifest = load_segment_manifest(segments / "manifest.json")
    speech = sum(record.duration_seconds for record in segment_manifest.segments)
    expected = speech + 35 * 0.350 + 3 * 0.900
    manifest = assemble_meeting(
        fixture.script,
        segments,
        tmp_path / "meeting.wav",
        output_manifest=tmp_path / "m.json",
    )
    assert manifest.duration_seconds == pytest.approx(expected, abs=0.02)


def test_no_trailing_pause(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest = assemble_meeting(
        fixture.script,
        segments,
        tmp_path / "meeting.wav",
        output_manifest=tmp_path / "m.json",
    )
    assert manifest.timeline[-1].pause_after_seconds == 0
    assert manifest.duration_seconds == pytest.approx(
        manifest.timeline[-1].end_seconds, abs=0.001
    )


def test_section_boundaries_use_the_longer_pause(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest = assemble_meeting(
        fixture.script,
        segments,
        tmp_path / "meeting.wav",
        output_manifest=tmp_path / "m.json",
        turn_pause_ms=200,
        section_pause_ms=750,
    )
    by_index = {entry.index: entry for entry in manifest.timeline}
    # Turn 13 ends "Status and integration"; turn 14 starts "Database migration".
    assert by_index[13].pause_after_seconds == pytest.approx(0.750)
    assert by_index[14].pause_after_seconds == pytest.approx(0.200)
    assert by_index[39].pause_after_seconds == 0


def test_timeline_is_contiguous(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest = assemble_meeting(
        fixture.script,
        segments,
        tmp_path / "meeting.wav",
        output_manifest=tmp_path / "m.json",
    )
    for previous, current in zip(manifest.timeline, manifest.timeline[1:]):
        assert current.start_seconds == pytest.approx(
            previous.end_seconds + previous.pause_after_seconds, abs=1e-6
        )
        assert current.end_seconds > current.start_seconds


def test_segments_are_resampled_to_target(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path, sample_rate=16_000)
    manifest = assemble_meeting(
        fixture.script,
        segments,
        tmp_path / "meeting.wav",
        output_manifest=tmp_path / "m.json",
        sample_rate=24_000,
    )
    assert manifest.sample_rate == 24_000
    assert inspect_wav(tmp_path / "meeting.wav").sample_rate == 24_000


def test_wrong_turn_order_is_rejected(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest_path = segments / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["segments"][0], payload["segments"][1] = (
        payload["segments"][1],
        payload["segments"][0],
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SegmentError, match="turn order mismatch"):
        assemble_meeting(
            fixture.script,
            segments,
            tmp_path / "meeting.wav",
            output_manifest=tmp_path / "m.json",
        )


def test_missing_segment_file_is_reported(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    (segments / "turn_010_GREG.wav").unlink()
    with pytest.raises(SegmentError, match="missing segment file"):
        assemble_meeting(
            fixture.script,
            segments,
            tmp_path / "meeting.wav",
            output_manifest=tmp_path / "m.json",
        )


def test_text_mismatch_is_rejected(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest_path = segments / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["segments"][0]["text"] = "Edited words"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SegmentError, match="does not match the fixture"):
        assemble_meeting(
            fixture.script,
            segments,
            tmp_path / "meeting.wav",
            output_manifest=tmp_path / "m.json",
        )


def test_manifest_validation_counts_turns(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    manifest = load_segment_manifest(segments / "manifest.json")
    from dataclasses import replace

    truncated = replace(manifest, segments=manifest.segments[:-1])
    with pytest.raises(SegmentError, match="has 38 turns"):
        validate_manifest_against_script(fixture.script, truncated)


def test_describe_segment_set(fixture, tmp_path: Path) -> None:
    empty = describe_segment_set(tmp_path / "nothing")
    assert empty["present"] is False
    segments = _build_segments(fixture, tmp_path)
    described = describe_segment_set(segments)
    assert described["present"] is True
    assert described["segments"] == 39
    assert described["files_present"] == 39


def test_wav_summary(fixture, tmp_path: Path) -> None:
    segments = _build_segments(fixture, tmp_path)
    output = tmp_path / "meeting.wav"
    assemble_meeting(
        fixture.script, segments, output, output_manifest=tmp_path / "m.json"
    )
    summary = wav_summary(output)
    assert summary["sample_rate"] == 24_000
    assert summary["channels"] == 1
    assert summary["bytes"] > 44
    assert len(summary["sha256"]) == 64
