"""Assemble per-turn segments into one meeting WAV plus a reference timeline.

The timeline is the only defensible time-aligned reference in this lab: it comes
from the actual segment durations and the configured pauses, not from utterance
order. WhisperX and Gemini never see it. Prompt 05 may use it for DER, and any
DER result must say that it came from this manifest.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from src import config
from src.schema import (
    MeetingAudioManifest,
    MeetingScript,
    SegmentManifest,
    TimelineEntry,
    write_json,
)
from src.tts.audio import (
    AudioError,
    concatenate_with_pauses,
    inspect_wav,
    read_wav,
    resample_linear,
    sha256_file,
    to_mono,
    write_wav,
)
from src.tts.segments import (
    SegmentError,
    environment_info,
    load_segment_manifest,
    utc_now,
)

logger = logging.getLogger(__name__)


def validate_manifest_against_script(
    script: MeetingScript, manifest: SegmentManifest
) -> None:
    """Fail loudly if the segment set is not the fixture's turn set, in order."""

    records = manifest.segments
    if len(records) != len(script.turns):
        raise SegmentError(
            f"segment manifest has {len(records)} turns but the script has "
            f"{len(script.turns)}"
        )
    for turn, record in zip(script.turns, records):
        if turn.index != record.index:
            raise SegmentError(
                f"turn order mismatch: expected index {turn.index}, "
                f"got {record.index}"
            )
        if turn.speaker_id != record.speaker_id:
            raise SegmentError(
                f"turn {turn.index}: expected speaker {turn.speaker_id}, "
                f"got {record.speaker_id}"
            )
        if turn.text != record.text:
            raise SegmentError(
                f"turn {turn.index}: segment text does not match the fixture"
            )


def assemble_meeting(
    script: MeetingScript,
    segments_dir: Path | str,
    output_wav: Path | str,
    *,
    output_manifest: Path | str | None = None,
    sample_rate: int = config.MEETING_SAMPLE_RATE,
    turn_pause_ms: int = config.TURN_PAUSE_MS,
    section_pause_ms: int = config.SECTION_PAUSE_MS,
) -> MeetingAudioManifest:
    """Concatenate segments in script order and write the meeting WAV."""

    if sample_rate <= 0:
        raise SegmentError("sample rate must be positive")
    if turn_pause_ms < 0 or section_pause_ms < 0:
        raise SegmentError("pauses cannot be negative")

    directory = Path(segments_dir)
    manifest = load_segment_manifest(directory / "manifest.json")
    validate_manifest_against_script(script, manifest)

    records = manifest.by_index()
    parts: list[np.ndarray] = []
    pauses_ms: list[int] = []
    timeline: list[TimelineEntry] = []
    cursor = 0.0

    for position, turn in enumerate(script.turns):
        record = records[turn.index]
        segment_path = directory / record.file
        if not segment_path.exists():
            raise SegmentError(f"missing segment file: {segment_path}")

        try:
            samples, info = read_wav(segment_path)
        except AudioError as exc:
            raise SegmentError(str(exc)) from exc

        if info.sample_rate != sample_rate:
            logger.info(
                "turn %03d: resampling %d Hz -> %d Hz",
                turn.index,
                info.sample_rate,
                sample_rate,
            )
            samples = resample_linear(samples, info.sample_rate, sample_rate)
        samples = to_mono(samples)
        if samples.shape[0] == 0:
            raise SegmentError(f"turn {turn.index}: empty audio segment")

        duration = samples.shape[0] / sample_rate
        start = cursor
        end = start + duration

        is_last = position == len(script.turns) - 1
        if is_last:
            pause_ms = 0
        else:
            next_turn = script.turns[position + 1]
            section_changes = bool(
                turn.section and next_turn.section and turn.section != next_turn.section
            )
            pause_ms = section_pause_ms if section_changes else turn_pause_ms

        timeline.append(
            TimelineEntry(
                index=turn.index,
                speaker_id=turn.speaker_id,
                text=turn.text,
                start_seconds=start,
                end_seconds=end,
                pause_after_seconds=pause_ms / 1000,
            )
        )
        parts.append(samples)
        if not is_last:
            pauses_ms.append(pause_ms)
        cursor = end + pause_ms / 1000

    meeting = concatenate_with_pauses(parts, pauses_ms, sample_rate)
    output_path = Path(output_wav)
    write_wav(output_path, meeting, sample_rate)

    manifest_path = (
        Path(output_manifest)
        if output_manifest is not None
        else output_path.with_name("meeting_manifest.json")
    )
    audio_manifest = MeetingAudioManifest(
        schema_version="1.0",
        fixture_id=script.fixture_id,
        meeting_id=script.meeting_id,
        audio_file=str(output_path),
        source=manifest.source,
        model=manifest.model,
        sample_rate=sample_rate,
        channels=config.MEETING_CHANNELS,
        sample_width_bytes=config.MEETING_SAMPLE_WIDTH_BYTES,
        duration_seconds=meeting.shape[0] / sample_rate,
        turn_pause_ms=turn_pause_ms,
        section_pause_ms=section_pause_ms,
        timeline=tuple(timeline),
        environment=environment_info(),
        notes=(
            "Reference timestamps are derived from the TTS segment manifest plus "
            "configured pauses. They are evaluation metadata, never an ASR hint.",
            "No trailing silence is added; the timeline ends at the last turn.",
            "Segment order and text were checked against meeting_script.json.",
        ),
    )
    write_json(manifest_path, audio_manifest.to_dict())
    logger.info(
        "wrote %s (%.2f s, %d turns); manifest %s",
        output_path,
        audio_manifest.duration_seconds,
        len(timeline),
        manifest_path,
    )
    return audio_manifest


def describe_segment_set(segments_dir: Path | str) -> dict[str, object]:
    """Small status helper used by the CLI."""

    directory = Path(segments_dir)
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        return {
            "manifest": str(manifest_path),
            "present": False,
            "segments": 0,
        }
    manifest = load_segment_manifest(manifest_path)
    present = sum(
        1 for record in manifest.segments if (directory / record.file).exists()
    )
    return {
        "manifest": str(manifest_path),
        "present": True,
        "source": manifest.source,
        "model": manifest.model,
        "segments": len(manifest.segments),
        "files_present": present,
    }


def wav_summary(path: Path | str) -> dict[str, object]:
    info = inspect_wav(path)
    return {
        "path": str(info.path),
        "duration_seconds": round(info.duration_seconds, 3),
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "bytes": Path(path).stat().st_size,
        "sha256": sha256_file(path),
    }
