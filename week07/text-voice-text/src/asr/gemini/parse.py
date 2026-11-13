"""Parse a Gemini transcription interaction into the shared schema.

Annotations are read from the structured response (``steps`` → ``content`` →
``annotations``), never by scraping the prose. The format is documented as::

    {"type": "word_info", "text": "Hello", "speaker": "spk_1",
     "start_offset": "0.100s", "end_offset": "0.400s"}

Speaker labels are preserved exactly. This module never maps ``spk_1`` to a
participant, and it never receives participant names to map with.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src import config
from src.schema import NormalizedTranscript, TranscriptSegment, Word


class ParseError(RuntimeError):
    """Raised when a transcription response cannot be normalized safely."""


_OFFSET_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:ms|s|sec|secs|seconds?)?\s*$")
_CLOCK_RE = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)\s*$"
)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def interaction_to_mapping(interaction: Any) -> dict[str, Any]:
    """Return a JSON-safe dict for an SDK Interaction or a test mapping."""

    if isinstance(interaction, Mapping):
        return dict(interaction)
    dump = getattr(interaction, "model_dump", None)
    if callable(dump):
        try:
            data = dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:  # pragma: no cover - older pydantic signature
            data = dump()
        if isinstance(data, Mapping):
            return dict(data)
    # Last resort: read the fields the parser needs. This keeps a fake object
    # usable without teaching every test double pydantic.
    payload: dict[str, Any] = {}
    for name in ("id", "status", "model", "output_text", "steps", "usage"):
        value = _field(interaction, name)
        if value is not None:
            payload[name] = value
    return payload


def parse_offset(value: Any, *, label: str = "offset") -> float | None:
    """Parse a documented offset such as ``"0.100s"`` into seconds.

    Accepts a number, a seconds string (optionally with an ``s``/``ms`` unit),
    or ``HH:MM:SS.mmm``. Returns ``None`` for an absent value; raises on text
    that is present but unparseable, so a schema change is visible instead of
    silently becoming zero.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ParseError(f"{label} is a bool, not a time: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ParseError(f"{label} is not finite: {value!r}")
        return max(0.0, number)

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered.endswith("ms"):
        try:
            number = float(lowered[:-2].strip())
        except ValueError as exc:
            raise ParseError(f"{label} is not a time: {value!r}") from exc
        if not math.isfinite(number):
            raise ParseError(f"{label} is not finite: {value!r}")
        return max(0.0, number / 1000.0)

    match = _OFFSET_RE.match(lowered)
    if match:
        return max(0.0, float(match.group(1)))

    match = _CLOCK_RE.match(text)
    if match:
        hours = float(match.group(1) or 0)
        minutes = float(match.group(2))
        seconds = float(match.group(3))
        return max(0.0, hours * 3600 + minutes * 60 + seconds)

    raise ParseError(f"{label} is not a time: {value!r}")


def _label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


@dataclass(frozen=True)
class ParsedResponse:
    """What the response itself says, before it becomes a transcript."""

    text: str
    words: tuple[Word, ...]


def _text_from_steps(steps: Sequence[Any]) -> str:
    parts: list[str] = []
    for step in steps:
        if _field(step, "type") != "model_output":
            continue
        for content in _field(step, "content") or []:
            if _field(content, "type") != "text":
                continue
            text = _field(content, "text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def parse_response(raw: Mapping[str, Any]) -> ParsedResponse:
    """Extract the text and word annotations from a raw interaction dump."""

    if not isinstance(raw, Mapping):
        raise ParseError("transcription response is not a mapping")

    steps = _field(raw, "steps") or []
    if not isinstance(steps, (list, tuple)):
        raise ParseError("transcription response has a non-list 'steps' field")

    text = _field(raw, "output_text")
    if not isinstance(text, str) or not text.strip():
        text = _text_from_steps(steps)

    words: list[Word] = []
    for step in steps:
        if _field(step, "type") != "model_output":
            continue
        for content in _field(step, "content") or []:
            if _field(content, "type") != "text":
                continue
            for annotation in _field(content, "annotations") or []:
                if _field(annotation, "type") != "word_info":
                    continue
                word_text = str(_field(annotation, "text") or "").strip()
                if not word_text:
                    continue
                start = parse_offset(
                    _field(annotation, "start_offset"), label="word start_offset"
                )
                end = parse_offset(
                    _field(annotation, "end_offset"), label="word end_offset"
                )
                if start is not None and end is not None and end < start:
                    raise ParseError(
                        f"word {word_text!r} ends before it starts "
                        f"({start} > {end})"
                    )
                speaker = _label(_field(annotation, "speaker"))
                words.append(
                    Word(
                        text=word_text,
                        start=start,
                        end=end,
                        score=None,
                        speaker=speaker,
                    )
                )

    if not text.strip() and not words:
        raise ParseError(
            "transcription response contains neither output_text nor word_info "
            "annotations; check the model id and that verbatim mode was used"
        )
    return ParsedResponse(text=text.strip(), words=tuple(words))


def _group_words(
    words: Sequence[Word], *, gap_seconds: float
) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current:
            previous = current[-1]
            speaker_change = (word.speaker or config.UNKNOWN_SPEAKER) != (
                previous.speaker or config.UNKNOWN_SPEAKER
            )
            timed = (
                word.start is not None
                and previous.end is not None
                and word.start - previous.end > gap_seconds
            )
            if speaker_change or timed:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _segment_from_words(
    group: Sequence[Word],
    *,
    index: int,
    fallback_end: float,
) -> TranscriptSegment | None:
    text = " ".join(word.text for word in group).strip()
    if not text:
        return None

    speaker = _label(group[0].speaker) or config.UNKNOWN_SPEAKER
    starts = [word.start for word in group if word.start is not None]
    ends = [word.end for word in group if word.end is not None]
    start = min(starts) if starts else 0.0
    end = max(ends) if ends else max(start, fallback_end)
    if end < start:
        end = start
    return TranscriptSegment(
        index=index,
        start=start,
        end=end,
        text=text,
        speaker_label=speaker,
        words=tuple(group),
    )


def normalize_interaction(
    raw: Mapping[str, Any],
    *,
    fixture_id: str,
    meeting_id: str,
    model: str,
    language: str,
    duration_seconds: float | None = None,
    raw_output_file: str | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> NormalizedTranscript:
    """Convert a raw interaction dump into ``NormalizedTranscript``.

    Word-level output has no segment boundaries, so segments are rebuilt from
    the word annotations: a new segment starts on a speaker change or on a gap
    longer than ``config.TRANSCRIBE_SEGMENT_GAP_SECONDS``.
    """

    parsed = parse_response(raw)
    fallback_end = float(duration_seconds or 0.0)

    if parsed.words:
        groups = _group_words(
            parsed.words, gap_seconds=config.TRANSCRIBE_SEGMENT_GAP_SECONDS
        )
        segments = [
            segment
            for group in groups
            if (
                segment := _segment_from_words(
                    group, index=0, fallback_end=fallback_end
                )
            )
            is not None
        ]
        # Re-index from 1 after any dropped group.
        segments = [
            TranscriptSegment(
                index=index,
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker_label=segment.speaker_label,
                words=segment.words,
            )
            for index, segment in enumerate(segments, start=1)
        ]
    else:
        segments = [
            TranscriptSegment(
                index=1,
                start=0.0,
                end=max(0.0, fallback_end),
                text=parsed.text,
                speaker_label=config.UNKNOWN_SPEAKER,
                words=(),
            )
        ]

    return NormalizedTranscript(
        schema_version="1.0",
        fixture_id=fixture_id,
        meeting_id=meeting_id,
        system="gemini",
        model=model,
        language=language or "unknown",
        segments=tuple(segments),
        raw_output_file=raw_output_file,
        manifest=dict(manifest or {}),
    )
