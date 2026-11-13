"""Turn a WhisperX result into the shared normalized transcript schema.

Nothing here renames speakers. WhisperX and pyannote produce anonymous labels
such as ``SPEAKER_00``; those strings are preserved exactly. Any segment the
diarizer cannot attribute keeps the ``UNKNOWN`` label.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

from src import config
from src.schema import NormalizedTranscript, TranscriptSegment, Word


class NormalizationError(RuntimeError):
    """Raised when a WhisperX result cannot be normalized safely."""


def _seconds(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{label} is not a number: {value!r}") from exc
    if not math.isfinite(number):
        raise NormalizationError(f"{label} is not finite: {value!r}")
    return max(0.0, number)


def _label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def _dominant_speaker(words: Sequence[Mapping[str, Any]]) -> str | None:
    labels = [
        label
        for word in words
        if (label := _label(word.get("speaker"))) is not None
    ]
    if not labels:
        return None
    # Counter preserves first-seen order for ties, which keeps output stable.
    return Counter(labels).most_common(1)[0][0]


def _word_from(raw: Mapping[str, Any], fallback_speaker: str) -> Word | None:
    text = str(raw.get("word", raw.get("text", ""))).strip()
    if not text:
        return None
    start = raw.get("start")
    end = raw.get("end")
    score = raw.get("score")
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = None
    speaker = _label(raw.get("speaker")) or fallback_speaker
    return Word(
        text=text,
        start=_seconds(start, label="word start") if start is not None else None,
        end=_seconds(end, label="word end") if end is not None else None,
        score=score,
        speaker=speaker,
    )


def _segment_from(raw: Mapping[str, Any], index: int) -> TranscriptSegment | None:
    text = str(raw.get("text", "")).strip()
    if not text:
        return None

    start = _seconds(raw.get("start"), label=f"segment {index} start")
    end = _seconds(raw.get("end"), label=f"segment {index} end")
    if end < start:
        raise NormalizationError(
            f"segment {index} ends before it starts ({start} > {end})"
        )

    raw_words = raw.get("words") or []
    if not isinstance(raw_words, list):
        raise NormalizationError(f"segment {index} words is not a list")

    speaker = (
        _label(raw.get("speaker"))
        or _dominant_speaker([w for w in raw_words if isinstance(w, Mapping)])
        or config.UNKNOWN_SPEAKER
    )

    words = tuple(
        word
        for item in raw_words
        if isinstance(item, Mapping)
        and (word := _word_from(item, speaker)) is not None
    )

    return TranscriptSegment(
        index=index,
        start=start,
        end=end,
        text=text,
        speaker_label=speaker,
        words=words,
    )


def normalize_result(
    raw: Mapping[str, Any],
    *,
    fixture_id: str,
    meeting_id: str,
    model: str,
    language: str | None = None,
    system: str = "whisperx",
    raw_output_file: str | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> NormalizedTranscript:
    """Convert a WhisperX result dict into ``NormalizedTranscript``.

    Segments are ordered by start time (stable for ties) and renumbered from 1.
    Empty segments are dropped. Text is preserved apart from outer whitespace.
    """

    if not isinstance(raw, Mapping):
        raise NormalizationError("WhisperX result is not a mapping")
    raw_segments = raw.get("segments")
    if not isinstance(raw_segments, list):
        raise NormalizationError("WhisperX result has no 'segments' list")

    ordered = sorted(
        (item for item in raw_segments if isinstance(item, Mapping)),
        key=lambda item: _seconds(item.get("start"), label="segment start"),
    )

    segments: list[TranscriptSegment] = []
    for item in ordered:
        segment = _segment_from(item, len(segments) + 1)
        if segment is not None:
            segments.append(segment)

    detected = raw.get("language") if isinstance(raw, Mapping) else None
    resolved_language = str(detected or language or "unknown")

    return NormalizedTranscript(
        schema_version="1.0",
        fixture_id=fixture_id,
        meeting_id=meeting_id,
        system=system,
        model=model,
        language=resolved_language,
        segments=tuple(segments),
        raw_output_file=raw_output_file,
        manifest=dict(manifest or {}),
    )
