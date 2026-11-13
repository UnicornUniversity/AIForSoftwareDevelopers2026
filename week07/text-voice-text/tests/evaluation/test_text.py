from __future__ import annotations

import pytest

from src.evaluation.text import (
    AlignmentError,
    align_texts,
    tokenize,
    tokenize_texts,
)


def test_identical_text_has_zero_wer() -> None:
    result = align_texts("The meeting starts now", "The meeting starts now")
    assert result.wer == 0.0
    assert result.substitutions == 0
    assert result.deletions == 0
    assert result.insertions == 0
    assert result.correct == 4


def test_one_substitution_out_of_four_words() -> None:
    result = align_texts("the quick brown fox", "the quick brown box")
    assert result.substitutions == 1
    assert result.deletions == 0
    assert result.insertions == 0
    assert result.reference_length == 4
    assert result.wer == 0.25


def test_case_and_punctuation_are_normalized_symmetrically() -> None:
    result = align_texts("Hello, world. It's ready!", "hello world it's ready")
    assert result.substitutions == 0
    assert result.deletions == 0
    assert result.insertions == 0
    assert result.reference_length == 4


def test_a_release_number_is_one_token() -> None:
    tokens = tokenize("Release 2.4 ships Thursday.")
    assert [token.key for token in tokens] == ["release", "2.4", "ships", "thursday"]


def test_one_deletion_out_of_three() -> None:
    result = align_texts("one two three", "one three")
    assert result.deletions == 1
    assert result.substitutions == 0
    assert result.insertions == 0
    assert result.wer == pytest.approx(1 / 3)


def test_one_insertion_out_of_two() -> None:
    result = align_texts("one three", "one two three")
    assert result.insertions == 1
    assert result.substitutions == 0
    assert result.deletions == 0
    assert result.wer == 0.5


def test_empty_hypothesis_is_all_deletions() -> None:
    result = align_texts("alpha beta gamma", "")
    assert result.deletions == 3
    assert result.wer == 1.0
    assert result.hypothesis_length == 0


def test_both_empty_is_zero_wer() -> None:
    result = align_texts("", "")
    assert result.errors == 0
    assert result.wer == 0.0
    assert result.defined is False


def test_repetitions_are_not_collapsed() -> None:
    result = align_texts("no no no", "no")
    assert result.deletions == 2
    assert result.reference_length == 3


def test_fillers_are_kept_in_the_primary_tokenizer() -> None:
    tokens = tokenize("Um, so, um, the build is ready")
    assert [token.key for token in tokens][:3] == ["um", "so", "um"]
    assert len(tokens) == 7


def test_fillers_can_be_removed_only_as_a_supplementary_view() -> None:
    primary = align_texts("um the build is uh ready", "the build is ready")
    secondary = align_texts(
        "um the build is uh ready", "the build is ready", mode="filler_removed"
    )
    assert primary.insertions == 0
    assert primary.deletions == 2
    assert secondary.deletions == 0
    assert secondary.wer == 0.0


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(AlignmentError):
        tokenize("text", mode="aggressive")


def test_ops_cover_every_reference_token() -> None:
    result = align_texts("the quick brown fox jumps", "the slow brown fox")
    covered = sum(
        1
        for op in result.ops
        if op.kind in {"equal", "sub", "del"} and op.reference is not None
    )
    assert covered == result.reference_length
    assert result.correct + result.substitutions + result.deletions == covered


def test_spans_track_which_segment_a_token_came_from() -> None:
    tokenized = tokenize_texts(["Hello there.", "General Kenobi."])
    assert tokenized.spans == ((0, 2), (2, 4))
    assert tokenized.span_text(1) == "General Kenobi"  # punctuation is not a token
    assert tokenized.span_of(2) == 1
    assert tokenized.span_of(0) == 0


def test_alignment_exposes_both_surface_forms_for_display() -> None:
    result = align_texts("Release 2.4 is ready", "release 2.5 is ready")
    substitution = next(op for op in result.ops if op.kind == "sub")
    assert substitution.reference == "2.4"
    assert substitution.hypothesis == "2.5"
