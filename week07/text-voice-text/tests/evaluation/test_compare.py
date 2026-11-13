from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluation.compare import (
    ComparisonError,
    build_comparison,
    load_system,
)
from src.evaluation.text import tokenize
from src.fixtures import load_fixture
from src.schema import NormalizedTranscript, TranscriptSegment
from tests.evaluation.fakes import (
    DEFAULT_LABELS,
    make_transcript,
    turn_spans,
    write_meeting_manifest,
    write_system,
)


@pytest.fixture(scope="module")
def fixture():
    return load_fixture()


def _reference_words(fixture) -> int:
    return sum(
        len(tokenize(turn.text)) for turn in fixture.ground_truth.turns
    )


def _setup(tmp_path: Path, fixture, *, mutate_gemini: bool = True):
    spans = turn_spans(fixture)
    manifest_path = tmp_path / "meeting_manifest.json"
    audio_file = write_meeting_manifest(manifest_path, fixture, spans)

    whisperx_transcript = make_transcript(
        fixture, spans, DEFAULT_LABELS["whisperx"], system="whisperx"
    )
    write_system(
        tmp_path / "whisperx",
        whisperx_transcript,
        audio_file=str(audio_file),
        timing={"audio_decode": 0.2, "transcribe": 1.0, "total_pipeline": 1.2},
        asr={"model": "small.en", "device": "cpu", "compute_type": "int8"},
    )

    gemini_transcript = make_transcript(
        fixture,
        spans,
        DEFAULT_LABELS["gemini"],
        system="gemini",
        model="gemini-3.5-transcribe",
        mutate_turn=1 if mutate_gemini else None,
        mutate=lambda text: "Ah" + text[len("All"):],
    )
    write_system(
        tmp_path / "gemini",
        gemini_transcript,
        audio_file=str(audio_file),
        timing={"upload": 0.4, "transcribe": 2.0, "total_pipeline": 2.6},
        asr={
            "model": "gemini-3.5-transcribe",
            "api_version": "v1beta",
            "diarize": True,
            "verbatim": True,
        },
    )
    return manifest_path


def _build(tmp_path: Path, fixture, manifest_path: Path | None = None):
    return build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=manifest_path or (tmp_path / "missing-manifest.json"),
    )


def test_perfect_local_run_scores_zero(tmp_path: Path, fixture) -> None:
    manifest_path = _setup(tmp_path, fixture)
    document = _build(tmp_path, fixture, manifest_path)

    whisperx = document["systems"]["whisperx"]
    assert whisperx["available"] is True
    assert whisperx["wer_verbatim"]["wer"] == 0.0
    assert whisperx["wer_verbatim"]["reference_words"] == _reference_words(fixture)
    assert whisperx["wer_verbatim"]["errors"] == 0
    assert whisperx["speaker"]["method"] == "time_alignment"
    assert whisperx["speaker"]["der"]["der"] == 0.0
    assert whisperx["counts"]["segments"] == 39
    assert whisperx["runtime"]["total_pipeline_seconds"] == 1.2
    assert len(whisperx["rows"]) == 39


def test_one_substitution_is_scored_exactly(tmp_path: Path, fixture) -> None:
    manifest_path = _setup(tmp_path, fixture)
    document = _build(tmp_path, fixture, manifest_path)

    gemini = document["systems"]["gemini"]
    were = gemini["wer_verbatim"]
    assert were["substitutions"] == 1
    assert were["deletions"] == 0
    assert were["insertions"] == 0
    expected = round(1 / _reference_words(fixture), 4)
    assert were["wer"] == expected
    assert document["comparison"]["wer_delta_gemini_minus_whisperx"] == expected


def test_clusters_are_mapped_not_compared_as_strings(tmp_path: Path, fixture) -> None:
    manifest_path = _setup(tmp_path, fixture)
    document = _build(tmp_path, fixture, manifest_path)

    whisperx_mapping = document["systems"]["whisperx"]["speaker"]["mapping"]
    gemini_mapping = document["systems"]["gemini"]["speaker"]["mapping"]
    assert whisperx_mapping == DEFAULT_LABELS["whisperx"]
    assert gemini_mapping == DEFAULT_LABELS["gemini"]
    assert document["systems"]["gemini"]["speaker"]["der"]["der"] == 0.0


def test_missing_system_is_reported_with_the_command(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    transcript = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    write_system(tmp_path / "whisperx", transcript, audio_file=str(audio))

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )

    assert document["systems"]["whisperx"]["available"] is True
    gemini = document["systems"]["gemini"]
    assert gemini["available"] is False
    assert "src.asr.gemini run" in gemini["reason"]


def test_no_outputs_at_all_is_a_clear_error(tmp_path: Path, fixture) -> None:
    with pytest.raises(ComparisonError) as excinfo:
        build_comparison(
            fixture=fixture,
            whisperx_dir=tmp_path / "none-whisperx",
            gemini_dir=tmp_path / "none-gemini",
        )
    message = str(excinfo.value)
    assert "src.asr.whisperx run" in message
    assert "src.asr.gemini run" in message


def test_der_is_unavailable_without_a_timeline(tmp_path: Path, fixture) -> None:
    _setup(tmp_path, fixture)
    document = _build(tmp_path, fixture)

    speaker = document["systems"]["whisperx"]["speaker"]
    assert speaker["method"] == "text_alignment"
    assert speaker["der"] == {"available": False, "reason": "no reference timeline"}
    assert speaker["text_alignment"]["accuracy"] == 1.0
    assert any(
        "DER not reported" in item["message"] for item in document["review_items"]
    )


def test_a_different_meeting_is_flagged(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture, per_turn=1.0)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    original = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    foreign = NormalizedTranscript(
        schema_version=original.schema_version,
        fixture_id=original.fixture_id,
        meeting_id="another-meeting",
        system="whisperx",
        model=original.model,
        language="en",
        segments=original.segments,
    )
    write_system(tmp_path / "whisperx", foreign, audio_file=str(audio))

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )

    assert "another-meeting" in document["systems"]["whisperx"]["fixture_note"]


def test_audio_file_mismatch_is_visible(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture)
    write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    transcript = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    write_system(
        tmp_path / "whisperx",
        transcript,
        audio_file=str(tmp_path / "some-other-take.wav"),
    )

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )

    assert document["systems"]["whisperx"]["speaker"]["audio_matches_reference"] is False
    assert any(
        "different audio file" in item["message"]
        for item in document["review_items"]
    )


def test_no_fillers_means_both_scores_agree(tmp_path: Path, fixture) -> None:
    manifest_path = _setup(tmp_path, fixture)
    document = _build(tmp_path, fixture, manifest_path)

    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        assert (
            block["wer_verbatim"]["wer"] == block["wer_filler_removed"]["wer"]
        )


def test_unknown_segments_are_flagged_for_review(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    transcript = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    segments = list(transcript.segments)
    segments[0] = TranscriptSegment(
        index=segments[0].index,
        start=segments[0].start,
        end=segments[0].end,
        text=segments[0].text,
        speaker_label="UNKNOWN",
    )
    with_unknown = NormalizedTranscript(
        schema_version=transcript.schema_version,
        fixture_id=transcript.fixture_id,
        meeting_id=transcript.meeting_id,
        system=transcript.system,
        model=transcript.model,
        language=transcript.language,
        segments=tuple(segments),
    )
    write_system(tmp_path / "whisperx", with_unknown, audio_file=str(audio))

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )

    assert document["systems"]["whisperx"]["speaker"]["unknown_segments"] == 1
    assert any(
        "UNKNOWN" in item["message"] for item in document["review_items"]
    )


def test_manifest_secrets_are_not_copied(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture)
    audio = write_meeting_manifest(tmp_path / "meeting_manifest.json", fixture, spans)
    transcript = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    write_system(
        tmp_path / "whisperx",
        transcript,
        audio_file=str(audio),
        extra={"privacy": {"api_key_present": True}},
    )

    document = build_comparison(
        fixture=fixture,
        whisperx_dir=tmp_path / "whisperx",
        gemini_dir=tmp_path / "gemini",
        meeting_manifest_path=tmp_path / "meeting_manifest.json",
    )
    dumped = json.dumps(document)
    for needle in ("sk-", "AIza", "hf_", "api_key_present"):
        assert needle not in dumped


def test_evaluation_never_imports_an_asr_or_tts_stage() -> None:
    """The blind-run boundary is structural: evaluation cannot feed the models."""

    package = Path(__file__).resolve().parents[2] / "src" / "evaluation"
    sources = sorted(package.glob("*.py"))
    assert sources
    for path in sources:
        imports = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        for statement in imports:
            assert "src.asr" not in statement, (path.name, statement)
            assert "src.tts" not in statement, (path.name, statement)


def test_load_system_ignores_a_broken_manifest(tmp_path: Path, fixture) -> None:
    spans = turn_spans(fixture)
    transcript = make_transcript(fixture, spans, DEFAULT_LABELS["whisperx"])
    out_dir = write_system(
        tmp_path / "whisperx", transcript, audio_file=str(tmp_path / "meeting.wav")
    )
    (out_dir / "run_manifest.json").write_text("{ not json", encoding="utf-8")

    loaded = load_system("whisperx", out_dir)

    assert loaded.available is True
    assert loaded.manifest == {}
