"""Speaker comparison: cluster mapping, DER, and turn-boundary detection.

Diarization labels are arbitrary strings (``SPEAKER_00``, ``spk_1``). Comparing
them means comparing **clusters**, never literal labels. This module therefore
infers one explicit, one-to-one mapping from anonymous label to ground-truth
speaker and reports it, so a reader can check the mapping instead of trusting it.

Two bases are supported:

``time_aligned``
    Requires a real timeline. It comes only from ``audio/meeting_manifest.json``,
    which the TTS stage writes from actual segment durations. Utterance order is
    never used as a time reference. With this basis DER and turn-boundary
    detection are available.

``text_alignment``
    Always available. Reference turns and hypothesis segments are paired through
    the word alignment, and each aligned word pair votes for a
    (ground-truth speaker, label) cell. This supports a confusion table and a
    mapping, but **not** DER: without timestamps there is nothing to align.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from src import config

#: Frame grid for overlap and DER. 10 ms is the usual NIST-style resolution and
#: keeps the ASCII/report values stable.
FRAME_STEP_SECONDS = 0.01

#: A detected segment start within this distance of a reference turn start counts
#: as the same boundary.
BOUNDARY_TOLERANCE_SECONDS = 0.5

#: Above this many clusters, exhaustive matching is too expensive and a greedy
#: assignment is used instead. The fixture has three speakers.
EXHAUSTIVE_MATCHING_LIMIT = 6


@dataclass(frozen=True)
class ReferenceSpan:
    turn_index: int
    speaker: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class HypothesisSpan:
    segment_index: int
    label: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _get(entry: object, name: str) -> object:
    """Read a timeline entry whether it is a mapping or a dataclass."""

    if isinstance(entry, Mapping):
        return entry[name]
    return getattr(entry, name)


def reference_spans(
    timeline: Sequence[Mapping], speaker_by_turn: Mapping[int, str]
) -> list[ReferenceSpan]:
    """Build reference spans from the meeting timeline, if one exists."""

    spans: list[ReferenceSpan] = []
    for entry in timeline:
        turn_index = int(_get(entry, "index"))
        speaker = speaker_by_turn.get(turn_index)
        if speaker is None:
            continue
        start = float(_get(entry, "start_seconds"))
        end = float(_get(entry, "end_seconds"))
        if end <= start:
            continue
        spans.append(
            ReferenceSpan(
                turn_index=turn_index, speaker=speaker, start=start, end=end
            )
        )
    return spans


def hypothesis_spans(segments: Sequence) -> list[HypothesisSpan]:
    spans: list[HypothesisSpan] = []
    for segment in segments:
        start = max(0.0, float(segment.start))
        end = max(start, float(segment.end))
        if end <= start:
            continue
        spans.append(
            HypothesisSpan(
                segment_index=int(segment.index),
                label=str(segment.speaker_label or config.UNKNOWN_SPEAKER),
                start=start,
                end=end,
            )
        )
    return spans


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


@dataclass(frozen=True)
class ClusterMapping:
    #: ground-truth speaker -> anonymous label
    speaker_to_label: Mapping[str, str]
    label_to_speaker: Mapping[str, str]
    #: seconds of overlap per (speaker, label) cell
    overlap_seconds: Mapping[tuple[str, str], float]
    method: str
    unmatched_speakers: tuple[str, ...] = ()
    unmatched_labels: tuple[str, ...] = ()

    def mapped_speaker(self, label: str) -> str | None:
        return self.label_to_speaker.get(label)


def _best_mapping(
    matrix: Mapping[tuple[str, str], float],
    speakers: Sequence[str],
    labels: Sequence[str],
) -> tuple[dict[str, str], float]:
    """Maximum total-overlap one-to-one assignment (deterministic)."""

    if not speakers or not labels:
        return {}, 0.0

    def score(pairs) -> float:
        return sum(matrix.get((speaker, label), 0.0) for speaker, label in pairs)

    if len(speakers) <= EXHAUSTIVE_MATCHING_LIMIT and len(labels) <= 8:
        best_score = -1.0
        best: dict[str, str] = {}
        pairs = min(len(speakers), len(labels))
        for permutation in itertools.permutations(labels, r=pairs):
            candidate = dict(zip(speakers, permutation))
            value = score(candidate.items())
            if value > best_score + 1e-9:
                best_score = value
                best = candidate
        return best, max(0.0, best_score)

    greedy: dict[str, str] = {}
    used: set[str] = set()
    for speaker, label in sorted(
        matrix,
        key=lambda pair: (-matrix[pair], pair[0], pair[1]),
    ):
        if speaker in greedy or label in used:
            continue
        greedy[speaker] = label
        used.add(label)
    return greedy, max(0.0, score(greedy.items()))


def map_clusters(
    reference: Sequence[ReferenceSpan],
    hypothesis: Sequence[HypothesisSpan],
) -> ClusterMapping:
    """Map anonymous labels to speakers by maximum time overlap."""

    matrix: dict[tuple[str, str], float] = {}
    for ref in reference:
        for hyp in hypothesis:
            seconds = _overlap(ref.start, ref.end, hyp.start, hyp.end)
            if seconds <= 0:
                continue
            key = (ref.speaker, hyp.label)
            matrix[key] = matrix.get(key, 0.0) + seconds

    speakers = sorted({span.speaker for span in reference})
    labels = sorted({span.label for span in hypothesis})
    speaker_to_label, _ = _best_mapping(matrix, speakers, labels)
    used_labels = set(speaker_to_label.values())
    return ClusterMapping(
        speaker_to_label=dict(speaker_to_label),
        label_to_speaker={
            label: speaker for speaker, label in speaker_to_label.items()
        },
        overlap_seconds=dict(matrix),
        method="time_alignment",
        unmatched_speakers=tuple(
            speaker for speaker in speakers if speaker not in speaker_to_label
        ),
        unmatched_labels=tuple(
            label for label in labels if label not in used_labels
        ),
    )


def _speaker_at(
    spans: Sequence[HypothesisSpan] | Sequence[ReferenceSpan], time: float
) -> str | None:
    for span in spans:
        if span.start <= time < span.end:
            return span.label if isinstance(span, HypothesisSpan) else span.speaker
    return None


@dataclass(frozen=True)
class DerResult:
    available: bool
    reason: str | None
    frame_step_seconds: float
    reference_seconds: float
    correct_seconds: float
    missed_seconds: float
    false_alarm_seconds: float
    confusion_seconds: float
    der: float | None
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def attribution_accuracy(self) -> float | None:
        if not self.reference_seconds:
            return None
        return self.correct_seconds / self.reference_seconds


def compute_der(
    reference: Sequence[ReferenceSpan],
    hypothesis: Sequence[HypothesisSpan],
    mapping: ClusterMapping,
    *,
    frame_step: float = FRAME_STEP_SECONDS,
) -> DerResult:
    """Frame-based DER with a mapped hypothesis.

    ``DER = (missed + false alarm + speaker error) / total reference speech``.
    Frame counts are converted to seconds; a frame is classified at its centre.
    """

    reference_seconds = sum(span.duration for span in reference)
    if not reference:
        return DerResult(
            available=False,
            reason="no reference timeline",
            frame_step_seconds=frame_step,
            reference_seconds=0.0,
            correct_seconds=0.0,
            missed_seconds=0.0,
            false_alarm_seconds=0.0,
            confusion_seconds=0.0,
            der=None,
        )
    if frame_step <= 0:
        raise ValueError("frame_step must be positive")

    end = max(
        [span.end for span in reference] + [span.end for span in hypothesis] + [0.0]
    )
    frames = int(math.ceil(end / frame_step))

    correct = missed = false_alarm = confusion = 0
    for frame in range(frames):
        time = frame * frame_step + frame_step / 2.0
        ref_speaker = _speaker_at(reference, time)
        hyp_label = _speaker_at(hypothesis, time)
        if ref_speaker is None:
            if hyp_label is not None:
                false_alarm += 1
            continue
        if hyp_label is None:
            missed += 1
            continue
        if mapping.mapped_speaker(hyp_label) == ref_speaker:
            correct += 1
        else:
            confusion += 1

    total_reference = correct + missed + confusion
    if total_reference == 0:
        return DerResult(
            available=False,
            reason="reference timeline has no speech frames",
            frame_step_seconds=frame_step,
            reference_seconds=reference_seconds,
            correct_seconds=0.0,
            missed_seconds=0.0,
            false_alarm_seconds=0.0,
            confusion_seconds=0.0,
            der=None,
        )
    der = (missed + false_alarm + confusion) / total_reference
    scale = frame_step
    return DerResult(
        available=True,
        reason=None,
        frame_step_seconds=frame_step,
        reference_seconds=round(reference_seconds, 3),
        correct_seconds=round(correct * scale, 3),
        missed_seconds=round(missed * scale, 3),
        false_alarm_seconds=round(false_alarm * scale, 3),
        confusion_seconds=round(confusion * scale, 3),
        der=round(der, 4),
        counts={
            "correct": correct,
            "missed": missed,
            "false_alarm": false_alarm,
            "confusion": confusion,
            "reference_frames": total_reference,
        },
    )


@dataclass(frozen=True)
class BoundaryResult:
    available: bool
    reason: str | None
    tolerance_seconds: float
    reference_boundaries: int
    hypothesis_boundaries: int
    matched: int
    precision: float | None
    recall: float | None
    missed_seconds: tuple[float, ...] = ()
    extra_seconds: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "tolerance_seconds": self.tolerance_seconds,
            "reference_boundaries": self.reference_boundaries,
            "hypothesis_boundaries": self.hypothesis_boundaries,
            "matched": self.matched,
            "precision": self.precision,
            "recall": self.recall,
            "missed_seconds": list(self.missed_seconds),
            "extra_seconds": list(self.extra_seconds),
        }


def compare_boundaries(
    reference: Sequence[ReferenceSpan],
    hypothesis: Sequence[HypothesisSpan],
    *,
    tolerance: float = BOUNDARY_TOLERANCE_SECONDS,
) -> BoundaryResult:
    """Match reference turn starts to hypothesis segment starts within tolerance."""

    if not reference:
        return BoundaryResult(
            available=False,
            reason="no reference timeline",
            tolerance_seconds=tolerance,
            reference_boundaries=0,
            hypothesis_boundaries=0,
            matched=0,
            precision=None,
            recall=None,
        )
    ref_times = sorted(span.start for span in reference[1:])
    hyp_times = sorted(span.start for span in hypothesis[1:])

    used: set[int] = set()
    matched = 0
    missed: list[float] = []
    for time in ref_times:
        best_index: int | None = None
        best_delta = tolerance + 1.0
        for index, candidate in enumerate(hyp_times):
            if index in used:
                continue
            delta = abs(candidate - time)
            if delta <= tolerance and delta < best_delta:
                best_delta = delta
                best_index = index
        if best_index is None:
            missed.append(round(time, 3))
            continue
        used.add(best_index)
        matched += 1

    extra = [
        round(time, 3) for index, time in enumerate(hyp_times) if index not in used
    ]
    return BoundaryResult(
        available=True,
        reason=None,
        tolerance_seconds=tolerance,
        reference_boundaries=len(ref_times),
        hypothesis_boundaries=len(hyp_times),
        matched=matched,
        precision=round(matched / len(hyp_times), 4) if hyp_times else None,
        recall=round(matched / len(ref_times), 4) if ref_times else None,
        missed_seconds=tuple(missed),
        extra_seconds=tuple(extra),
    )


@dataclass(frozen=True)
class TurnAttribution:
    turn_index: int
    speaker: str
    start: float
    end: float
    correct_seconds: float
    wrong_seconds: float
    missing_seconds: float
    dominant_label: str | None
    mapped_speaker: str | None

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "correct_seconds": round(self.correct_seconds, 3),
            "wrong_seconds": round(self.wrong_seconds, 3),
            "missing_seconds": round(self.missing_seconds, 3),
            "dominant_label": self.dominant_label,
            "mapped_speaker": self.mapped_speaker,
        }


def attribute_turns(
    reference: Sequence[ReferenceSpan],
    hypothesis: Sequence[HypothesisSpan],
    mapping: ClusterMapping,
    *,
    frame_step: float = FRAME_STEP_SECONDS,
) -> list[TurnAttribution]:
    """Per-turn time attributed to the correct, wrong, or no cluster."""

    rows: list[TurnAttribution] = []
    for span in reference:
        frames = max(0, int(round(span.duration / frame_step)))
        by_label: dict[str, int] = {}
        correct = wrong = missing = 0
        for frame in range(frames):
            time = span.start + frame * frame_step + frame_step / 2.0
            label = _speaker_at(hypothesis, time)
            if label is None:
                missing += 1
                continue
            by_label[label] = by_label.get(label, 0) + 1
            if mapping.mapped_speaker(label) == span.speaker:
                correct += 1
            else:
                wrong += 1
        dominant = (
            max(by_label, key=lambda label: (by_label[label], label))
            if by_label
            else None
        )
        rows.append(
            TurnAttribution(
                turn_index=span.turn_index,
                speaker=span.speaker,
                start=span.start,
                end=span.end,
                correct_seconds=correct * frame_step,
                wrong_seconds=wrong * frame_step,
                missing_seconds=missing * frame_step,
                dominant_label=dominant,
                mapped_speaker=(
                    mapping.mapped_speaker(dominant) if dominant else None
                ),
            )
        )
    return rows


@dataclass(frozen=True)
class TextAttribution:
    """Cluster comparison from word alignment, when no timeline exists."""

    speaker_to_label: Mapping[str, str]
    label_to_speaker: Mapping[str, str]
    cells: Mapping[tuple[str, str], int]
    speaker_words: Mapping[str, int]
    label_words: Mapping[str, int]
    unmapped_labels: tuple[str, ...]
    unmatched_speakers: tuple[str, ...]

    @property
    def correct_words(self) -> int:
        return sum(
            count
            for (speaker, label), count in self.cells.items()
            if self.speaker_to_label.get(speaker) == label
        )

    @property
    def total_words(self) -> int:
        return sum(self.speaker_words.values())

    @property
    def accuracy(self) -> float | None:
        if not self.total_words:
            return None
        return self.correct_words / self.total_words


def attribute_words(
    cell_counts: Mapping[tuple[str, str], int],
) -> TextAttribution:
    """Turn (speaker, label) word counts into an explicit cluster mapping."""

    matrix = {pair: float(count) for pair, count in cell_counts.items()}
    speakers = sorted({speaker for speaker, _ in cell_counts})
    labels = sorted({label for _, label in cell_counts})
    speaker_to_label, _ = _best_mapping(matrix, speakers, labels)
    used = set(speaker_to_label.values())

    speaker_words: dict[str, int] = {}
    label_words: dict[str, int] = {}
    for (speaker, label), count in cell_counts.items():
        speaker_words[speaker] = speaker_words.get(speaker, 0) + count
        label_words[label] = label_words.get(label, 0) + count

    return TextAttribution(
        speaker_to_label=dict(speaker_to_label),
        label_to_speaker={
            label: speaker for speaker, label in speaker_to_label.items()
        },
        cells=dict(cell_counts),
        speaker_words=speaker_words,
        label_words=label_words,
        unmapped_labels=tuple(
            label for label in labels if label not in used
        ),
        unmatched_speakers=tuple(
            speaker for speaker in speakers if speaker not in speaker_to_label
        ),
    )
