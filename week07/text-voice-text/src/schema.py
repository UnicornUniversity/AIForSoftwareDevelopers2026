"""Shared data model and validation for the Meeting Voice AI Lab.

The same schema is used by the TTS stage, both ASR routes, and the evaluation
stage. Keeping one schema is what makes a blind comparison possible: WhisperX
and Gemini outputs normalize into :class:`NormalizedTranscript`, while the
fixture's :class:`MeetingScript` and :class:`GroundTruth` stay evaluation-only
and are never handed to an ASR system.

Only the standard library is used here so the schema stays importable in tests
and scripts that do not install the audio or vendor SDKs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "1.0"


class SchemaError(ValueError):
    """Raised when a fixture or manifest fails validation."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")


def word_count(text: str) -> int:
    """Count word-like tokens consistently across fixtures and transcripts."""

    return len(_WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# Fixture models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    index: int
    speaker_id: str
    text: str
    delivery: str = ""
    section: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Turn":
        return cls(
            index=int(data["index"]),
            speaker_id=str(data["speaker_id"]),
            text=str(data["text"]),
            delivery=str(data.get("delivery", "")),
            section=str(data.get("section", "")),
        )

    def to_dict(self, *, include_delivery: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "speaker_id": self.speaker_id,
            "text": self.text,
        }
        if include_delivery:
            payload["delivery"] = self.delivery
            payload["section"] = self.section
        return payload


@dataclass(frozen=True)
class Participant:
    id: str
    full_name: str
    role: str
    gender: str
    meeting_role: str = ""
    delivery_notes: str = ""
    voice_requirements: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Participant":
        return cls(
            id=str(data["id"]),
            full_name=str(data["full_name"]),
            role=str(data["role"]),
            gender=str(data["gender"]),
            meeting_role=str(data.get("meeting_role", "")),
            delivery_notes=str(data.get("delivery_notes", "")),
            voice_requirements=dict(data.get("voice_requirements", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "role": self.role,
            "gender": self.gender,
            "meeting_role": self.meeting_role,
            "delivery_notes": self.delivery_notes,
            "voice_requirements": dict(self.voice_requirements),
        }


@dataclass(frozen=True)
class MeetingScript:
    schema_version: str
    fixture_id: str
    meeting_id: str
    title: str
    language: str
    fictional: bool
    participant_ids: tuple[str, ...]
    turns: tuple[Turn, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeetingScript":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            title=str(data.get("title", "")),
            language=str(data.get("language", "en-US")),
            fictional=bool(data.get("fictional", False)),
            participant_ids=tuple(str(x) for x in data.get("participant_ids", [])),
            turns=tuple(Turn.from_dict(t) for t in data["turns"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "meeting_id": self.meeting_id,
            "title": self.title,
            "language": self.language,
            "fictional": self.fictional,
            "participant_ids": list(self.participant_ids),
            "turns": [turn.to_dict() for turn in self.turns],
        }


@dataclass(frozen=True)
class MeetingMetadata:
    schema_version: str
    fixture_id: str
    meeting_id: str
    title: str
    language: str
    fictional: bool
    participants: tuple[Participant, ...]
    agenda: tuple[str, ...] = ()
    turn_count: int = 0
    word_count_estimate: int = 0
    estimated_duration_seconds: tuple[int, int] = (0, 0)
    project: Mapping[str, str] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeetingMetadata":
        duration = data.get("estimated_duration_seconds", [0, 0])
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            title=str(data.get("title", "")),
            language=str(data.get("language", "en-US")),
            fictional=bool(data.get("fictional", False)),
            participants=tuple(
                Participant.from_dict(p) for p in data.get("participants", [])
            ),
            agenda=tuple(str(item) for item in data.get("agenda", [])),
            turn_count=int(data.get("turn_count", 0)),
            word_count_estimate=int(data.get("word_count_estimate", 0)),
            estimated_duration_seconds=(int(duration[0]), int(duration[1])),
            project=dict(data.get("project", {})),
            raw=dict(data),
        )

    def participant_by_id(self, speaker_id: str) -> Participant | None:
        for participant in self.participants:
            if participant.id == speaker_id:
                return participant
        return None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True)
class GroundTruth:
    schema_version: str
    fixture_id: str
    meeting_id: str
    language: str
    turn_count: int
    turns: tuple[Turn, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GroundTruth":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            language=str(data.get("language", "en-US")),
            turn_count=int(data.get("turn_count", len(data.get("turns", [])))),
            turns=tuple(Turn.from_dict(t) for t in data["turns"]),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_script(
    script: MeetingScript, metadata: MeetingMetadata | None = None
) -> list[str]:
    """Return human-readable problems; an empty list means valid."""

    errors: list[str] = []
    if not script.turns:
        errors.append("script has no turns")
        return errors

    indexes = [turn.index for turn in script.turns]
    expected = list(range(1, len(script.turns) + 1))
    if indexes != expected:
        errors.append(f"turn indexes are not 1..{len(script.turns)}: {indexes}")

    known = set(script.participant_ids)
    seen = {turn.speaker_id for turn in script.turns}
    if seen != known:
        errors.append(
            f"script speaker IDs {sorted(seen)} do not match participant_ids "
            f"{sorted(known)}"
        )

    for turn in script.turns:
        if not turn.text.strip():
            errors.append(f"turn {turn.index} has empty text")
        if turn.speaker_id not in known:
            errors.append(f"turn {turn.index} uses unknown speaker {turn.speaker_id!r}")

    if metadata is not None:
        if metadata.turn_count and metadata.turn_count != len(script.turns):
            errors.append(
                f"metadata turn_count {metadata.turn_count} != "
                f"script turns {len(script.turns)}"
            )
        meta_ids = {p.id for p in metadata.participants}
        if meta_ids != known:
            errors.append(
                f"metadata participant IDs {sorted(meta_ids)} do not match "
                f"script {sorted(known)}"
            )
        if metadata.fixture_id != script.fixture_id:
            errors.append("fixture_id differs between script and metadata")
        if metadata.meeting_id != script.meeting_id:
            errors.append("meeting_id differs between script and metadata")
    return errors


def validate_ground_truth(
    script: MeetingScript, ground_truth: GroundTruth
) -> list[str]:
    """The evaluation reference must be an exact projection of the script."""

    errors: list[str] = []
    if len(script.turns) != len(ground_truth.turns):
        errors.append("script and ground truth have different turn counts")
        return errors
    for script_turn, truth_turn in zip(script.turns, ground_truth.turns):
        if script_turn.index != truth_turn.index:
            errors.append(f"turn index mismatch at {script_turn.index}")
        if script_turn.speaker_id != truth_turn.speaker_id:
            errors.append(f"speaker mismatch at turn {script_turn.index}")
        if script_turn.text != truth_turn.text:
            errors.append(f"text mismatch at turn {script_turn.index}")
    if ground_truth.turn_count != len(ground_truth.turns):
        errors.append("ground truth turn_count does not match its turns")
    return errors


# ---------------------------------------------------------------------------
# TTS segment and meeting manifests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentRecord:
    index: int
    speaker_id: str
    voice: str
    text: str
    file: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    duration_seconds: float
    sha256: str
    model: str | None
    created_utc: str
    synthesis_seconds: float | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SegmentRecord":
        return cls(
            index=int(data["index"]),
            speaker_id=str(data["speaker_id"]),
            voice=str(data["voice"]),
            text=str(data["text"]),
            file=str(data["file"]),
            sample_rate=int(data["sample_rate"]),
            channels=int(data["channels"]),
            sample_width_bytes=int(data["sample_width_bytes"]),
            duration_seconds=float(data["duration_seconds"]),
            sha256=str(data["sha256"]),
            model=None if data.get("model") is None else str(data["model"]),
            created_utc=str(data["created_utc"]),
            synthesis_seconds=(
                None
                if data.get("synthesis_seconds") is None
                else float(data["synthesis_seconds"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "speaker_id": self.speaker_id,
            "voice": self.voice,
            "text": self.text,
            "file": self.file,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
            "duration_seconds": round(self.duration_seconds, 6),
            "sha256": self.sha256,
            "model": self.model,
            "created_utc": self.created_utc,
            "synthesis_seconds": self.synthesis_seconds,
        }


@dataclass(frozen=True)
class SegmentManifest:
    schema_version: str
    fixture_id: str
    meeting_id: str
    source: str
    model: str | None
    generated_utc: str
    segments: tuple[SegmentRecord, ...]
    environment: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SegmentManifest":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            source=str(data.get("source", "unknown")),
            model=None if data.get("model") is None else str(data["model"]),
            generated_utc=str(data.get("generated_utc", "")),
            segments=tuple(SegmentRecord.from_dict(s) for s in data["segments"]),
            environment=dict(data.get("environment", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "meeting_id": self.meeting_id,
            "source": self.source,
            "model": self.model,
            "generated_utc": self.generated_utc,
            "segments": [segment.to_dict() for segment in self.segments],
            "environment": dict(self.environment),
        }

    def by_index(self) -> dict[int, SegmentRecord]:
        return {segment.index: segment for segment in self.segments}


@dataclass(frozen=True)
class TimelineEntry:
    index: int
    speaker_id: str
    text: str
    start_seconds: float
    end_seconds: float
    pause_after_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "speaker_id": self.speaker_id,
            "text": self.text,
            "start_seconds": round(self.start_seconds, 6),
            "end_seconds": round(self.end_seconds, 6),
            "pause_after_seconds": round(self.pause_after_seconds, 6),
        }


@dataclass(frozen=True)
class MeetingAudioManifest:
    schema_version: str
    fixture_id: str
    meeting_id: str
    audio_file: str
    source: str
    model: str | None
    sample_rate: int
    channels: int
    sample_width_bytes: int
    duration_seconds: float
    turn_pause_ms: int
    section_pause_ms: int
    timeline: tuple[TimelineEntry, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeetingAudioManifest":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            audio_file=str(data["audio_file"]),
            source=str(data.get("source", "unknown")),
            model=None if data.get("model") is None else str(data["model"]),
            sample_rate=int(data["sample_rate"]),
            channels=int(data["channels"]),
            sample_width_bytes=int(data["sample_width_bytes"]),
            duration_seconds=float(data["duration_seconds"]),
            turn_pause_ms=int(data.get("turn_pause_ms", 0)),
            section_pause_ms=int(data.get("section_pause_ms", 0)),
            timeline=tuple(
                TimelineEntry(
                    index=int(entry["index"]),
                    speaker_id=str(entry["speaker_id"]),
                    text=str(entry["text"]),
                    start_seconds=float(entry["start_seconds"]),
                    end_seconds=float(entry["end_seconds"]),
                    pause_after_seconds=float(entry["pause_after_seconds"]),
                )
                for entry in data.get("timeline", [])
            ),
            environment=dict(data.get("environment", {})),
            notes=tuple(str(note) for note in data.get("notes", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "meeting_id": self.meeting_id,
            "audio_file": self.audio_file,
            "source": self.source,
            "model": self.model,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
            "duration_seconds": round(self.duration_seconds, 6),
            "turn_pause_ms": self.turn_pause_ms,
            "section_pause_ms": self.section_pause_ms,
            "timeline": [entry.to_dict() for entry in self.timeline],
            "environment": dict(self.environment),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Shared ASR output schema (both routes normalize into this)
# ---------------------------------------------------------------------------


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class Word:
    text: str
    start: float | None = None
    end: float | None = None
    score: float | None = None
    speaker: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Word":
        return cls(
            text=str(data["text"]),
            start=_optional_float(data.get("start")),
            end=_optional_float(data.get("end")),
            score=_optional_float(data.get("score")),
            speaker=None
            if data.get("speaker") is None
            else str(data["speaker"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "speaker": self.speaker,
        }


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    speaker_label: str
    words: tuple[Word, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptSegment":
        return cls(
            index=int(data["index"]),
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data["text"]),
            speaker_label=str(data.get("speaker_label", "UNKNOWN")),
            words=tuple(Word.from_dict(word) for word in data.get("words", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": round(self.start, 6),
            "end": round(self.end, 6),
            "text": self.text,
            "speaker_label": self.speaker_label,
            "words": [word.to_dict() for word in self.words],
        }


@dataclass(frozen=True)
class NormalizedTranscript:
    schema_version: str
    fixture_id: str
    meeting_id: str
    system: str
    model: str
    language: str
    segments: tuple[TranscriptSegment, ...]
    raw_output_file: str | None = None
    manifest: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizedTranscript":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            fixture_id=str(data["fixture_id"]),
            meeting_id=str(data["meeting_id"]),
            system=str(data["system"]),
            model=str(data["model"]),
            language=str(data.get("language", "unknown")),
            segments=tuple(
                TranscriptSegment.from_dict(segment)
                for segment in data.get("segments", [])
            ),
            raw_output_file=None
            if data.get("raw_output_file") is None
            else str(data["raw_output_file"]),
            manifest=dict(data.get("manifest", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "meeting_id": self.meeting_id,
            "system": self.system,
            "model": self.model,
            "language": self.language,
            "segments": [segment.to_dict() for segment in self.segments],
            "raw_output_file": self.raw_output_file,
            "manifest": dict(self.manifest),
        }

    def full_text(self) -> str:
        return " ".join(segment.text for segment in self.segments)


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SchemaError([f"{path} does not contain a JSON object"])
    return data


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write indented UTF-8 JSON atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_turns(data: Mapping[str, Any]) -> Sequence[Turn]:
    return tuple(Turn.from_dict(turn) for turn in data.get("turns", []))
