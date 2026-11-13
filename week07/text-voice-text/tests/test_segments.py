from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.tts.segments import (
    SegmentError,
    ingest_manual_segments,
    load_segment_manifest,
    plan_segments,
    segment_filename,
    synthesize_segments,
)
from tests.conftest import FakeResult, FakeTTSClient, wav_bytes, write_wav


class BarrierClient:
    """Only answers when ``parties`` calls are in flight at the same time.

    A serial implementation would block on the first call until the barrier
    times out, so this proves real concurrency rather than merely asserting on
    the result.
    """

    def __init__(self, parties: int) -> None:
        self.model = "fake-tts-model"
        self.barrier = threading.Barrier(parties, timeout=5)
        self._lock = threading.Lock()
        self.calls = 0

    def synthesize(self, text, voice) -> FakeResult:
        self.barrier.wait()
        with self._lock:
            self.calls += 1
            call_number = self.calls
        return FakeResult(
            audio_bytes=wav_bytes(
                max(0.08, len(text) / 80), frequency=220.0 + 40.0 * call_number
            )
        )


def test_plan_follows_script_order_and_names(fixture) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    assert [plan.index for plan in plans] == list(range(1, 40))
    assert [plan.speaker_id for plan in plans] == [
        turn.speaker_id for turn in fixture.script.turns
    ]
    assert plans[0].filename == "turn_001_ANN.wav"
    assert plans[1].filename == "turn_002_BOB.wav"
    assert segment_filename(7, "GREG") == "turn_007_GREG.wav"


def test_synthesis_writes_one_file_per_turn(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    client = FakeTTSClient()
    manifest = synthesize_segments(
        plans,
        tmp_path,
        client,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    assert len(manifest.segments) == 39
    assert len(client.calls) == 39
    for plan, record in zip(plans, manifest.segments):
        assert record.index == plan.index
        assert record.speaker_id == plan.speaker_id
        assert record.text == plan.text
        assert record.voice == plan.voice.voice_name
        assert (tmp_path / record.file).exists()
        assert record.duration_seconds > 0
        assert len(record.sha256) == 64
    assert (tmp_path / "manifest.json").exists()


def test_manifest_records_model_and_environment(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    manifest = synthesize_segments(
        plans,
        tmp_path,
        FakeTTSClient(),
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    assert manifest.source == "gemini_api"
    assert manifest.model == "fake-tts-model"
    assert manifest.environment["python"]
    assert "packages" in manifest.environment
    assert manifest.environment["packages"].count("=") >= 3


def test_resume_keeps_existing_segments(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    first = FakeTTSClient()
    synthesize_segments(
        plans,
        tmp_path,
        first,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    second = FakeTTSClient()
    manifest = synthesize_segments(
        plans,
        tmp_path,
        second,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    assert len(first.calls) == 39
    assert second.calls == []
    assert len(manifest.segments) == 39


def test_corrupt_manifest_is_reported_as_segment_error(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SegmentError, match="unreadable"):
        load_segment_manifest(path)


def test_resume_ignores_a_corrupt_manifest(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    client = FakeTTSClient()
    manifest = synthesize_segments(
        plans,
        tmp_path,
        client,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    assert len(client.calls) == 39
    assert len(manifest.segments) == 39
    load_segment_manifest(tmp_path / "manifest.json")


def test_overwrite_regenerates_everything(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    synthesize_segments(
        plans,
        tmp_path,
        FakeTTSClient(),
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    second = FakeTTSClient()
    synthesize_segments(
        plans,
        tmp_path,
        second,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        overwrite=True,
    )
    assert len(second.calls) == 39


def test_limit_synthesizes_only_the_first_turns(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    client = FakeTTSClient()
    manifest = synthesize_segments(
        plans,
        tmp_path,
        client,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        limit=3,
    )
    assert len(manifest.segments) == 3
    assert [record.index for record in manifest.segments] == [1, 2, 3]
    assert len(client.calls) == 3


def test_invalid_limit_is_rejected(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    with pytest.raises(SegmentError):
        synthesize_segments(
            plans,
            tmp_path,
            FakeTTSClient(),
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
            limit=0,
        )


def test_manifest_is_persisted_after_a_mid_run_failure(
    fixture, tmp_path: Path
) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    client = FakeTTSClient(fail_on=3)
    with pytest.raises(RuntimeError):
        synthesize_segments(
            plans,
            tmp_path,
            client,
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
        )
    manifest = load_segment_manifest(tmp_path / "manifest.json")
    assert [record.index for record in manifest.segments] == [1, 2]


def test_turns_are_synthesized_concurrently_and_stay_in_order(
    fixture, tmp_path: Path
) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    client = BarrierClient(parties=4)

    manifest = synthesize_segments(
        plans,
        tmp_path,
        client,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        limit=8,
        concurrency=4,
    )

    # The barrier makes a serial run raise instead of returning, so reaching
    # this line means four requests really were in flight together.
    assert client.calls == 8
    assert [record.index for record in manifest.segments] == list(range(1, 9))
    assert all((tmp_path / record.file).exists() for record in manifest.segments)


def test_parallel_run_writes_the_same_manifest_as_serial(
    fixture, tmp_path: Path
) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    serial_dir = tmp_path / "serial"
    parallel_dir = tmp_path / "parallel"

    synthesize_segments(
        plans,
        serial_dir,
        FakeTTSClient(),
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        concurrency=1,
    )
    synthesize_segments(
        plans,
        parallel_dir,
        FakeTTSClient(),
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        concurrency=4,
    )

    serial = load_segment_manifest(serial_dir / "manifest.json")
    parallel = load_segment_manifest(parallel_dir / "manifest.json")
    assert [record.index for record in serial.segments] == [
        record.index for record in parallel.segments
    ]
    assert [record.file for record in serial.segments] == [
        record.file for record in parallel.segments
    ]
    assert [record.duration_seconds for record in serial.segments] == [
        record.duration_seconds for record in parallel.segments
    ]


def test_invalid_concurrency_is_rejected(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    with pytest.raises(SegmentError, match="concurrency"):
        synthesize_segments(
            plans,
            tmp_path,
            FakeTTSClient(),
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
            concurrency=0,
        )


def test_manual_ingest_copies_files_and_uses_manual_source(
    fixture, tmp_path: Path
) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    source = tmp_path / "manual"
    for plan in plans:
        write_wav(source / plan.filename, seconds=0.1)
    destination = tmp_path / "segments"
    manifest = ingest_manual_segments(
        plans,
        source,
        destination,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
    )
    assert manifest.source == "manual_ai_studio"
    assert manifest.model is None
    assert len(manifest.segments) == 39
    assert (destination / "turn_001_ANN.wav").exists()
    assert (destination / "manifest.json").exists()


def test_manual_ingest_reports_missing_files(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    source = tmp_path / "manual"
    source.mkdir()
    write_wav(source / plans[0].filename, seconds=0.1)
    with pytest.raises(SegmentError, match="missing"):
        ingest_manual_segments(
            plans,
            source,
            tmp_path / "segments",
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
        )


def test_manual_ingest_rejects_non_wav(fixture, tmp_path: Path) -> None:
    plans = plan_segments(fixture.script, fixture.metadata)
    source = tmp_path / "manual"
    source.mkdir()
    for plan in plans:
        write_wav(source / plan.filename, seconds=0.05)
    (source / plans[0].filename).write_bytes(b"not a wav")
    with pytest.raises(SegmentError):
        ingest_manual_segments(
            plans,
            source,
            tmp_path / "segments",
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
        )
