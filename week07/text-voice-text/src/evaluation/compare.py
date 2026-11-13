"""Build the comparison document from the two ASR routes and the ground truth.

The ground truth is read here and nowhere else. Nothing in this module is
imported by an ASR stage, so there is no path that could send the reference
transcript, participant names, or the turn map to WhisperX or Gemini.

Metric policy:

- **Primary WER** is computed on verbatim output with case and punctuation
  normalized symmetrically. Fillers and repetitions are kept on both sides.
- **Supplementary WER** additionally removes a fixed hesitation list from both
  sides. It is labelled, never substituted for the primary number.
- **DER** is computed only when a real TTS timeline exists. Without one it is
  reported as unavailable; utterance order is never turned into timestamps.
- **Speaker clusters** are compared through an explicit, maximum-overlap
  one-to-one mapping. Literal label strings are never compared.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src import config
from src.evaluation import speakers
from src.evaluation.text import (
    Alignment,
    TokenizedText,
    align,
    tokenize,
    tokenize_texts,
)
from src.fixtures import Fixture, load_fixture
from src.schema import (
    MeetingAudioManifest,
    NormalizedTranscript,
    load_json,
)

SYSTEMS = ("whisperx", "gemini")

MISSING_GUIDANCE = {
    "whisperx": (
        "python -m src.asr.whisperx run            # add --no-diarize without HF_TOKEN"
    ),
    "gemini": "python -m src.asr.gemini run      # needs GEMINI_API_KEY",
}


class ComparisonError(RuntimeError):
    """Raised when the comparison cannot be built at all."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemInput:
    system: str
    out_dir: Path
    transcript: NormalizedTranscript | None
    manifest: Mapping[str, Any]
    raw: Mapping[str, Any] | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.transcript is not None


def _read_optional_json(path: Path) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def load_system(system: str, out_dir: Path) -> SystemInput:
    """Load one route's normalized transcript and manifest, if present."""

    out_dir = Path(out_dir)
    transcript_path = out_dir / "transcript.json"
    manifest_path = out_dir / "run_manifest.json"
    if not transcript_path.exists():
        return SystemInput(
            system=system,
            out_dir=out_dir,
            transcript=None,
            manifest={},
            raw=None,
            reason=(
                f"no normalized transcript at {transcript_path}. Produce it with "
                f"`{MISSING_GUIDANCE.get(system, 'the ASR command')}`."
            ),
        )
    transcript = NormalizedTranscript.from_dict(load_json(transcript_path))
    manifest = _read_optional_json(manifest_path) or {}
    raw = None
    raw_name = transcript.raw_output_file
    if raw_name:
        raw = _read_optional_json(Path(raw_name))
        if raw is None:
            raw = _read_optional_json(out_dir / Path(raw_name).name)
    return SystemInput(
        system=system,
        out_dir=out_dir,
        transcript=transcript,
        manifest=manifest,
        raw=raw,
    )


def load_meeting_manifest(path: Path | None = None) -> MeetingAudioManifest | None:
    path = Path(path) if path is not None else config.MEETING_MANIFEST_PATH
    if not path.exists():
        return None
    try:
        return MeetingAudioManifest.from_dict(load_json(path))
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Rows: pairing reference turns with hypothesis segments
# ---------------------------------------------------------------------------


def _row_assignments(
    reference: TokenizedText,
    hypothesis: TokenizedText,
    alignment: Alignment,
) -> dict[int, list[int]]:
    """Map each reference turn position to the hypothesis segments aligned to it."""

    rows: dict[int, list[int]] = {position: [] for position in range(len(reference.spans))}
    current = 0
    for op in alignment.ops:
        if op.reference_index is not None:
            position = reference.span_of(op.reference_index)
            if position is not None:
                current = position
        if op.hypothesis_index is None:
            continue
        segment_position = hypothesis.span_of(op.hypothesis_index)
        if segment_position is None:
            continue
        assigned = rows[current]
        if not assigned or assigned[-1] != segment_position:
            if segment_position not in assigned:
                assigned.append(segment_position)
    return rows


def _build_rows(
    turns: Sequence,
    segments: Sequence,
    reference: TokenizedText,
    hypothesis: TokenizedText,
    alignment: Alignment,
    *,
    mode: str,
) -> list[dict[str, Any]]:
    assignments = _row_assignments(reference, hypothesis, alignment)
    rows: list[dict[str, Any]] = []
    for position, turn in enumerate(turns):
        assigned = assignments.get(position, [])
        hypothesis_text = " ".join(
            segments[index].text.strip()
            for index in assigned
            if segments[index].text.strip()
        )
        local = align(
            tokenize(turn.text, mode=mode),
            tokenize(hypothesis_text, mode=mode),
        )
        rows.append(
            {
                "turn_index": turn.index,
                "speaker": turn.speaker_id,
                "reference_text": turn.text,
                "hypothesis_text": hypothesis_text,
                "segment_indexes": [
                    segments[index].index for index in assigned
                ],
                "reference_segments": [
                    segments[index].speaker_label for index in assigned
                ],
                "substitutions": local.substitutions,
                "deletions": local.deletions,
                "insertions": local.insertions,
                "correct": local.correct,
                "reference_words": local.reference_length,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Runtime and usage
# ---------------------------------------------------------------------------


def _runtime(manifest: Mapping[str, Any]) -> dict[str, Any]:
    timings = manifest.get("timing_seconds") or {}
    if not isinstance(timings, Mapping):
        timings = {}
    total = timings.get("total_pipeline")
    audio = manifest.get("audio") or {}
    duration = audio.get("duration_seconds") if isinstance(audio, Mapping) else None
    realtime_factor = None
    if total is not None and duration:
        try:
            realtime_factor = round(float(total) / float(duration), 3)
        except (TypeError, ValueError, ZeroDivisionError):
            realtime_factor = None
    return {
        "total_pipeline_seconds": total,
        "stage_seconds": {
            str(key): value
            for key, value in timings.items()
            if key != "total_pipeline"
        },
        "audio_duration_seconds": duration,
        "realtime_factor": realtime_factor,
        "note": (
            "Wall-clock seconds of the whole pipeline, including decoding and "
            "export. Real-time factor is pipeline time divided by audio "
            "duration; lower is faster."
        ),
    }


def _usage(manifest: Mapping[str, Any], raw: Mapping[str, Any] | None) -> dict[str, Any]:
    recorded = None
    for holder in (manifest, raw or {}):
        if isinstance(holder, Mapping) and holder.get("usage") is not None:
            recorded = holder.get("usage")
            break
    return {
        "recorded": recorded,
        "cost": "not computed",
        "pricing_url": config.PRICING_URL,
        "usage_url": config.USAGE_URL,
        "note": (
            "A price is deliberately not quoted: it changes and depends on the "
            "account. The provider's usage page is the source of truth; local "
            "WhisperX has no API cost."
        ),
    }


# ---------------------------------------------------------------------------
# Per-system evaluation
# ---------------------------------------------------------------------------


def _speaker_block(
    system_input: SystemInput,
    fixture: Fixture,
    alignment: Alignment,
    reference_tokens: TokenizedText,
    hypothesis_tokens: TokenizedText,
    ground_truth: Sequence,
    timeline: MeetingAudioManifest | None,
) -> dict[str, Any]:
    transcript = system_input.transcript
    assert transcript is not None
    segments = transcript.segments

    # Text-based attribution is always available.
    cells: dict[tuple[str, str], int] = {}
    for op in alignment.ops:
        if op.reference_index is None or op.hypothesis_index is None:
            continue
        position = reference_tokens.span_of(op.reference_index)
        segment_position = hypothesis_tokens.span_of(op.hypothesis_index)
        if position is None or segment_position is None:
            continue
        speaker = ground_truth[position].speaker_id
        label = segments[segment_position].speaker_label or config.UNKNOWN_SPEAKER
        cells[(speaker, label)] = cells.get((speaker, label), 0) + 1
    text_attribution = speakers.attribute_words(cells)

    block: dict[str, Any] = {
        "text_alignment": {
            "method": "word alignment through the paired segments",
            "mapping": dict(text_attribution.speaker_to_label),
            "correct_words": text_attribution.correct_words,
            "total_words": text_attribution.total_words,
            "accuracy": (
                None
                if text_attribution.accuracy is None
                else round(text_attribution.accuracy, 4)
            ),
            "confusion_words": [
                {"speaker": speaker, "label": label, "words": count}
                for (speaker, label), count in sorted(cells.items())
            ],
            "unmapped_labels": list(text_attribution.unmapped_labels),
            "unmatched_speakers": list(text_attribution.unmatched_speakers),
        }
    }

    unknown_segments = sum(
        1
        for segment in segments
        if (segment.speaker_label or config.UNKNOWN_SPEAKER)
        == config.UNKNOWN_SPEAKER
    )
    block["unknown_segments"] = unknown_segments

    if timeline is None or not timeline.timeline:
        block["method"] = "text_alignment"
        block["time_derivation"] = (
            "unavailable: no generated timeline. Imported or hand-made audio has "
            "no time-aligned reference. Utterance order is not used as a "
            "substitute, so DER and turn-boundary detection are not reported."
        )
        block["der"] = {"available": False, "reason": "no reference timeline"}
        block["boundaries"] = {
            "available": False,
            "reason": "no reference timeline",
        }
        block["audio_matches_reference"] = None
        return block

    speaker_by_turn = {
        turn.index: turn.speaker_id for turn in ground_truth
    }
    reference = speakers.reference_spans(timeline.timeline, speaker_by_turn)
    hypothesis = speakers.hypothesis_spans(segments)
    mapping = speakers.map_clusters(reference, hypothesis)
    der = speakers.compute_der(reference, hypothesis, mapping)
    boundaries = speakers.compare_boundaries(reference, hypothesis)
    turn_rows = speakers.attribute_turns(reference, hypothesis, mapping)

    audio_file = (
        (system_input.manifest.get("audio") or {}).get("file")
        if isinstance(system_input.manifest.get("audio"), Mapping)
        else None
    )
    audio_matches = (
        None
        if not audio_file
        else Path(str(audio_file)).resolve()
        == Path(timeline.audio_file).resolve()
    )

    block["method"] = "time_alignment"
    block["audio_matches_reference"] = audio_matches
    block["mapping"] = dict(mapping.speaker_to_label)
    block["label_to_speaker"] = dict(mapping.label_to_speaker)
    block["mapping_method"] = mapping.method
    block["unmapped_labels"] = list(mapping.unmatched_labels)
    block["unmatched_speakers"] = list(mapping.unmatched_speakers)
    block["der"] = {
        "available": der.available,
        "reason": der.reason,
        "frame_step_seconds": der.frame_step_seconds,
        "reference_seconds": der.reference_seconds,
        "correct_seconds": der.correct_seconds,
        "missed_seconds": der.missed_seconds,
        "false_alarm_seconds": der.false_alarm_seconds,
        "confusion_seconds": der.confusion_seconds,
        "der": der.der,
        "attribution_accuracy": (
            None
            if der.attribution_accuracy is None
            else round(der.attribution_accuracy, 4)
        ),
        "definition": (
            "(missed + false alarm + speaker error) / total reference speech, "
            "on a fixed frame grid"
        ),
    }
    block["boundaries"] = boundaries.to_dict()
    block["confusion_seconds"] = [
        {"speaker": speaker, "label": label, "seconds": round(value, 3)}
        for (speaker, label), value in sorted(mapping.overlap_seconds.items())
    ]
    block["turns"] = [row.to_dict() for row in turn_rows]
    block["turns_needing_review"] = [
        row.to_dict()
        for row in turn_rows
        if row.wrong_seconds + row.missing_seconds
        > 0.5 * max(1e-9, row.end - row.start)
    ]
    return block


def _wer_block(alignment: Alignment) -> dict[str, Any]:
    return {
        "wer": round(alignment.wer, 4),
        "defined": alignment.defined,
        "substitutions": alignment.substitutions,
        "deletions": alignment.deletions,
        "insertions": alignment.insertions,
        "correct": alignment.correct,
        "errors": alignment.errors,
        "reference_words": alignment.reference_length,
        "hypothesis_words": alignment.hypothesis_length,
    }


def evaluate_system(
    system_input: SystemInput,
    fixture: Fixture,
    timeline: MeetingAudioManifest | None,
) -> dict[str, Any]:
    """Score one route; ``available: false`` when its output does not exist."""

    if not system_input.available:
        return {
            "available": False,
            "out_dir": str(system_input.out_dir),
            "reason": system_input.reason,
        }

    transcript = system_input.transcript
    assert transcript is not None
    ground_truth = fixture.ground_truth.turns
    segments = transcript.segments

    reference_text = " ".join(turn.text for turn in ground_truth)
    hypothesis_text = " ".join(segment.text for segment in segments)

    reference_verbatim = tokenize_texts([turn.text for turn in ground_truth])
    hypothesis_verbatim = tokenize_texts([segment.text for segment in segments])
    alignment_verbatim = align(
        reference_verbatim.tokens, hypothesis_verbatim.tokens
    )

    reference_normalized = tokenize_texts(
        [turn.text for turn in ground_truth], mode="filler_removed"
    )
    hypothesis_normalized = tokenize_texts(
        [segment.text for segment in segments], mode="filler_removed"
    )
    alignment_normalized = align(
        reference_normalized.tokens, hypothesis_normalized.tokens
    )

    if transcript.fixture_id != fixture.script.fixture_id:
        fixture_note: str | None = (
            f"transcript fixture_id {transcript.fixture_id!r} differs from the "
            f"fixture {fixture.script.fixture_id!r}"
        )
    elif transcript.meeting_id != fixture.script.meeting_id:
        fixture_note = (
            f"transcript meeting_id {transcript.meeting_id!r} differs from the "
            f"fixture {fixture.script.meeting_id!r}"
        )
    else:
        fixture_note = None

    manifest = system_input.manifest
    asr = manifest.get("asr") or {}
    if not isinstance(asr, Mapping):
        asr = {}
    diarization = manifest.get("diarization") or {}
    if not isinstance(diarization, Mapping):
        diarization = {}

    speaker_block = _speaker_block(
        system_input,
        fixture,
        alignment_verbatim,
        reference_verbatim,
        hypothesis_verbatim,
        ground_truth,
        timeline,
    )

    rows = _build_rows(
        ground_truth,
        segments,
        reference_verbatim,
        hypothesis_verbatim,
        alignment_verbatim,
        mode="verbatim",
    )

    return {
        "available": True,
        "system": system_input.system,
        "out_dir": str(system_input.out_dir),
        "transcript_file": str(system_input.out_dir / "transcript.json"),
        "manifest_file": (
            str(system_input.out_dir / "run_manifest.json")
            if (system_input.out_dir / "run_manifest.json").exists()
            else None
        ),
        "model": transcript.model,
        "language": transcript.language,
        "config": {
            "model": asr.get("model", transcript.model),
            "device": asr.get("device"),
            "compute_type": asr.get("compute_type"),
            "api_version": asr.get("api_version"),
            "diarization_enabled": diarization.get(
                "enabled", manifest.get("asr", {}).get("diarize")
            ),
            "diarization_model": diarization.get("model"),
            "verbatim_mode": (
                (manifest.get("asr") or {}).get("verbatim")
                if isinstance(manifest.get("asr"), Mapping)
                else None
            ),
        },
        "counts": {
            "segments": len(segments),
            "words": _wer_block(alignment_verbatim)["hypothesis_words"],
            "speaker_labels": len(
                {segment.speaker_label for segment in segments}
            ),
        },
        "wer_verbatim": _wer_block(alignment_verbatim),
        "wer_filler_removed": _wer_block(alignment_normalized),
        "speaker": speaker_block,
        "runtime": _runtime(manifest),
        "usage": _usage(manifest, system_input.raw),
        "rows": rows,
        "reference_text": reference_text,
        "hypothesis_text": hypothesis_text,
        "fixture_note": fixture_note,
    }


# ---------------------------------------------------------------------------
# Review material
# ---------------------------------------------------------------------------


REVIEW_CHECKLIST: tuple[dict[str, str], ...] = (
    {
        "id": "boundaries",
        "item": "Listen to each missed or extra turn boundary.",
        "why": "A missed boundary usually means two speakers were merged into one "
        "cluster; decide whether that changes the meeting's meaning.",
    },
    {
        "id": "unknown",
        "item": "Review every segment labelled UNKNOWN.",
        "why": "UNKNOWN means no cluster was confident; it is not a participant.",
    },
    {
        "id": "mapping",
        "item": "Confirm the cluster-to-speaker mapping is one-to-one and stable.",
        "why": "Clusters are arbitrary. A wrong mapping moves every error onto the "
        "wrong person even when the segmentation is right.",
    },
    {
        "id": "terms",
        "item": "Check substituted technical terms, product and release numbers.",
        "why": "WER treats every word alike; a wrong release number matters more "
        "than a wrong article.",
    },
    {
        "id": "fillers",
        "item": "Compare filler handling before reading the supplementary WER.",
        "why": "One system may emit 'um' and the other drop it; that difference is "
        "not a transcription mistake.",
    },
    {
        "id": "short-turns",
        "item": "Inspect turns under one second and any overlaps.",
        "why": "Very short turns are where attribution and boundaries are weakest.",
    },
    {
        "id": "der",
        "item": "If DER is unavailable, do not quote a number.",
        "why": "Utterance order is not a timeline; a made-up DER would be a "
        "fabricated metric.",
    },
)


def _review_items(system: str, block: Mapping[str, Any]) -> list[dict[str, str]]:
    if not block.get("available"):
        return []
    items: list[dict[str, str]] = []
    speaker = block.get("speaker") or {}
    der = speaker.get("der") or {}
    boundaries = speaker.get("boundaries") or {}
    rows = block.get("rows") or []

    if speaker.get("unknown_segments"):
        items.append(
            {
                "system": system,
                "severity": "info",
                "message": (
                    f"{speaker['unknown_segments']} segment(s) are labelled "
                    "UNKNOWN; check whether real speech was left unattributed."
                ),
            }
        )
    if der.get("available") and float(der.get("der") or 0) > 0.1:
        items.append(
            {
                "system": system,
                "severity": "warning",
                "message": (
                    f"DER is {der['der']} — review the speaker confusion and the "
                    "cluster mapping before reading it as a transcription problem."
                ),
            }
        )
    if boundaries.get("available"):
        missed = boundaries.get("missed_seconds") or []
        if missed:
            items.append(
                {
                    "system": system,
                    "severity": "info",
                    "message": (
                        "No detected boundary within "
                        f"{boundaries['tolerance_seconds']} s of reference turn "
                        f"starts at {missed[:8]}{' …' if len(missed) > 8 else ''}."
                    ),
                }
            )
        extra = boundaries.get("extra_seconds") or []
        if extra:
            items.append(
                {
                    "system": system,
                    "severity": "info",
                    "message": (
                        f"{len(extra)} extra detected boundary(ies) with no "
                        "reference turn start nearby."
                    ),
                }
            )
    if der.get("available") is False:
        items.append(
            {
                "system": system,
                "severity": "info",
                "message": f"DER not reported: {der.get('reason')}. Quote it as "
                "unavailable, not as zero.",
            }
        )
    if speaker.get("audio_matches_reference") is False:
        items.append(
            {
                "system": system,
                "severity": "warning",
                "message": (
                    "This transcript was produced from a different audio file "
                    "than the reference timeline. Time-based numbers are not "
                    "comparable across the two."
                ),
            }
        )
    if speaker.get("unmapped_labels"):
        items.append(
            {
                "system": system,
                "severity": "warning",
                "message": (
                    "Unmapped clusters: "
                    f"{speaker['unmapped_labels']} — a fourth 'speaker' may be a "
                    "noise cluster or a split of a real voice."
                ),
            }
        )
    if speaker.get("unmatched_speakers"):
        items.append(
            {
                "system": system,
                "severity": "warning",
                "message": (
                    "Ground-truth speakers with no matched cluster: "
                    f"{speaker['unmatched_speakers']} — the mapping is not "
                    "one-to-one."
                ),
            }
        )
    if speaker.get("method") == "text_alignment":
        items.append(
            {
                "system": system,
                "severity": "info",
                "message": (
                    "Speaker comparison used word alignment, not a timeline. "
                    "DER and boundary detection are unavailable; the word-based "
                    "confusion table is a weaker substitute."
                ),
            }
        )

    worst = sorted(
        (row for row in rows if row["substitutions"] + row["deletions"] + row["insertions"]),
        key=lambda row: (
            -(row["substitutions"] + row["deletions"] + row["insertions"]),
            row["turn_index"],
        ),
    )[:3]
    for row in worst:
        items.append(
            {
                "system": system,
                "severity": "info",
                "message": (
                    f"Turn {row['turn_index']} ({row['speaker']}) has "
                    f"{row['substitutions']} substitution(s), "
                    f"{row['deletions']} deletion(s), "
                    f"{row['insertions']} insertion(s); read it against the script."
                ),
            }
        )
    return items


# ---------------------------------------------------------------------------
# The comparison document
# ---------------------------------------------------------------------------


def _comparison_summary(systems: Mapping[str, Any]) -> dict[str, Any]:
    def value(system: str, path: Sequence[str]) -> Any:
        node: Any = systems.get(system) or {}
        for key in path:
            if not isinstance(node, Mapping):
                return None
            node = node.get(key)
        return node

    wer = {
        system: value(system, ("wer_verbatim", "wer"))
        for system in SYSTEMS
    }
    normalized = {
        system: value(system, ("wer_filler_removed", "wer"))
        for system in SYSTEMS
    }
    der = {
        system: value(system, ("speaker", "der", "der"))
        for system in SYSTEMS
    }
    runtime = {
        system: value(system, ("runtime", "total_pipeline_seconds"))
        for system in SYSTEMS
    }

    def delta(a: Any, b: Any) -> float | None:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(float(b) - float(a), 4)
        return None

    return {
        "wer_verbatim": wer,
        "wer_filler_removed": normalized,
        "der": der,
        "runtime_seconds": runtime,
        "wer_delta_gemini_minus_whisperx": delta(wer["whisperx"], wer["gemini"]),
        "der_delta_gemini_minus_whisperx": delta(der["whisperx"], der["gemini"]),
        "note": (
            "A difference is arithmetic, not a verdict. One controlled clean "
            "meeting cannot establish which system is better on real recordings."
        ),
    }


def build_comparison(
    *,
    fixture: Fixture | None = None,
    whisperx_dir: Path | None = None,
    gemini_dir: Path | None = None,
    meeting_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Score both routes and return the comparison document as a dict."""

    fixture = fixture or load_fixture()
    inputs = {
        "whisperx": load_system(
            "whisperx",
            whisperx_dir or config.WHISPERX_OUTPUT_DIR,
        ),
        "gemini": load_system("gemini", gemini_dir or config.GEMINI_OUTPUT_DIR),
    }
    if not any(item.available for item in inputs.values()):
        raise ComparisonError(
            "no ASR output found. Run one route first:\n"
            + "\n".join(
                f"  {system}: {MISSING_GUIDANCE[system]}" for system in SYSTEMS
            )
        )

    meeting_manifest = load_meeting_manifest(meeting_manifest_path)
    timeline = meeting_manifest if meeting_manifest else None

    ground_truth = fixture.ground_truth.turns
    reference_words = sum(
        len(tokenize(turn.text)) for turn in ground_truth
    )

    systems: dict[str, Any] = {}
    for system in SYSTEMS:
        systems[system] = evaluate_system(inputs[system], fixture, timeline)

    review_items: list[dict[str, str]] = []
    for system in SYSTEMS:
        review_items.extend(_review_items(system, systems[system]))

    der_basis = (
        "audio/meeting_manifest.json timeline (generated from real segment "
        "durations plus pauses)"
        if timeline and timeline.timeline
        else "unavailable: no generated meeting timeline"
    )

    return {
        "schema_version": "1.0",
        "created_utc": utc_now(),
        "fixture": {
            "fixture_id": fixture.script.fixture_id,
            "meeting_id": fixture.script.meeting_id,
            "title": fixture.script.title,
            "language": fixture.script.language,
            "fictional": fixture.script.fictional,
            "turn_count": len(ground_truth),
            "reference_words": reference_words,
            "ground_truth_file": str(
                fixture.fixture_dir / "ground_truth.json"
            ),
            "participants": [
                {"id": participant.id, "full_name": participant.full_name}
                for participant in fixture.metadata.participants
            ],
            "disclaimer": (
                "Fictional fixture at Brightline Components Ltd. This is a "
                "controlled demonstration, not a benchmark of real meetings."
            ),
        },
        "method": {
            "primary": (
                "verbatim ASR text; lowercase, punctuation removed symmetrically; "
                "fillers and repetitions kept on both sides"
            ),
            "supplementary": (
                "filler_removed: the same, minus a fixed hesitation list on both "
                "sides. Reported separately and never as the primary WER."
            ),
            "wer": "word error rate = (substitutions + deletions + insertions) / reference words",
            "tokenizer": (
                "a word is a run of letters and digits; internal apostrophes, "
                "dots, and hyphens are kept (\"don't\", \"2.4\", \"read-only\"); "
                "punctuation is not a word"
            ),
            "der_basis": der_basis,
            "der_requires_timeline": (
                "DER is computed only from a real timeline. Utterance order is "
                "never treated as time-aligned truth."
            ),
            "clusters": (
                "Anonymous diarization labels are compared as clusters through a "
                "maximum-overlap one-to-one mapping, never as literal strings."
            ),
            "wer_scope": (
                "WER measures words. It does not evaluate diarization, speaker "
                "attribution, punctuation, or timing."
            ),
        },
        "systems": systems,
        "comparison": _comparison_summary(systems),
        "review_checklist": list(REVIEW_CHECKLIST),
        "review_items": review_items,
        "notes": [
            "Neither ASR system was given the ground truth, participant names, or "
            "the turn map; this module reads what they produced.",
            "The controlled fixture is generated speech and unusually clean; "
            "results do not generalize to real meeting recordings.",
            "Cluster labels are arbitrary and are reported unchanged.",
            "Runtime is wall-clock on this machine and is not a performance "
            "benchmark across hardware.",
        ],
    }
