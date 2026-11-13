from __future__ import annotations

from src.evaluation import speakers
from src.evaluation.speakers import (
    HypothesisSpan,
    ReferenceSpan,
    attribute_words,
    compare_boundaries,
    compute_der,
    map_clusters,
)


def _ref(*rows: tuple[int, str, float, float]) -> list[ReferenceSpan]:
    return [
        ReferenceSpan(turn_index=index, speaker=speaker, start=start, end=end)
        for index, speaker, start, end in rows
    ]


def _hyp(*rows: tuple[int, str, float, float]) -> list[HypothesisSpan]:
    return [
        HypothesisSpan(segment_index=index, label=label, start=start, end=end)
        for index, label, start, end in rows
    ]


def test_mapping_follows_overlap_not_label_order() -> None:
    reference = _ref((1, "ANN", 0.0, 10.0), (2, "BOB", 10.0, 20.0))
    hypothesis = _hyp((1, "zz_cluster", 0.0, 10.0), (2, "aa_cluster", 10.0, 20.0))

    mapping = map_clusters(reference, hypothesis)

    assert mapping.speaker_to_label == {"ANN": "zz_cluster", "BOB": "aa_cluster"}
    assert mapping.label_to_speaker["zz_cluster"] == "ANN"
    assert mapping.unmatched_labels == ()


def test_der_is_zero_for_perfect_segmentation() -> None:
    reference = _ref((1, "ANN", 0.0, 1.0), (2, "BOB", 1.0, 2.0))
    hypothesis = _hyp((1, "c1", 0.0, 1.0), (2, "c2", 1.0, 2.0))
    mapping = map_clusters(reference, hypothesis)

    der = compute_der(reference, hypothesis, mapping, frame_step=0.1)

    assert der.available
    assert der.der == 0.0
    assert der.attribution_accuracy == 1.0


def test_der_counts_missed_speech() -> None:
    reference = _ref((1, "ANN", 0.0, 1.0), (2, "BOB", 1.0, 2.0))
    # The hypothesis only covers half of ANN's turn.
    hypothesis = _hyp((1, "c1", 0.0, 0.5), (2, "c2", 1.0, 2.0))
    mapping = map_clusters(reference, hypothesis)

    der = compute_der(reference, hypothesis, mapping, frame_step=0.1)

    assert der.available
    assert der.counts["missed"] == 5
    assert der.der == 0.25


def test_der_counts_false_alarm_for_speech_after_the_reference() -> None:
    reference = _ref((1, "ANN", 0.0, 1.0))
    hypothesis = _hyp((1, "c1", 0.0, 2.0))
    mapping = map_clusters(reference, hypothesis)

    der = compute_der(reference, hypothesis, mapping, frame_step=0.1)

    assert der.counts["false_alarm"] == 10
    # One extra second of hypothesis speech over one second of reference speech
    # makes DER 1.0; DER is not capped at 1.
    assert der.der == 1.0


def test_der_counts_speaker_error_when_the_cluster_mapping_is_wrong() -> None:
    reference = _ref((1, "ANN", 0.0, 1.0), (2, "BOB", 1.0, 2.0))
    # One cluster for both speakers: whoever it maps to, half the speech is wrong.
    hypothesis = _hyp((1, "one_voice", 0.0, 2.0))
    mapping = map_clusters(reference, hypothesis)

    der = compute_der(reference, hypothesis, mapping, frame_step=0.1)

    assert der.counts["confusion"] == 10
    assert der.der == 0.5  # 10 wrong frames of 20 reference frames
    assert mapping.unmatched_speakers


def test_der_without_a_timeline_is_unavailable_not_zero() -> None:
    mapping = speakers.ClusterMapping(
        speaker_to_label={},
        label_to_speaker={},
        overlap_seconds={},
        method="time_alignment",
    )
    der = compute_der([], _hyp((1, "c1", 0.0, 1.0)), mapping)

    assert der.available is False
    assert der.reason == "no reference timeline"
    assert der.der is None


def test_boundaries_match_within_tolerance() -> None:
    reference = _ref(
        (1, "ANN", 0.0, 1.0), (2, "BOB", 1.0, 2.0), (3, "GREG", 2.0, 3.0)
    )
    hypothesis = _hyp(
        (1, "c1", 0.0, 1.2), (2, "c2", 1.2, 2.4), (3, "c3", 2.6, 3.0)
    )

    result = compare_boundaries(reference, hypothesis, tolerance=0.5)

    assert result.available
    assert result.matched == 1  # only the 1.2 start is within 0.5 s of 1.0
    assert result.missed_seconds == (2.0,)
    assert result.extra_seconds == (2.6,)
    assert result.precision == 0.5
    assert result.recall == 0.5


def test_boundaries_without_a_timeline_are_unavailable() -> None:
    result = compare_boundaries([], _hyp((1, "c1", 0.0, 1.0)))
    assert result.available is False
    assert result.reason == "no reference timeline"


def test_word_attribution_recovers_the_mapping() -> None:
    attribution = attribute_words(
        {
            ("ANN", "spk_2"): 60,
            ("BOB", "spk_1"): 55,
            ("GREG", "spk_3"): 40,
            ("ANN", "spk_3"): 5,
        }
    )

    assert attribution.speaker_to_label["ANN"] == "spk_2"
    assert attribution.speaker_to_label["BOB"] == "spk_1"
    assert attribution.speaker_to_label["GREG"] == "spk_3"
    assert attribution.correct_words == 155
    assert attribution.total_words == 160
    assert attribution.accuracy == 155 / 160


def test_per_turn_attribution_marks_a_wrong_speaker_turn() -> None:
    reference = _ref((1, "ANN", 0.0, 1.0), (2, "BOB", 1.0, 2.0))
    hypothesis = _hyp((1, "c1", 0.0, 1.0), (2, "c2", 1.0, 2.0))
    mapping = speakers.ClusterMapping(
        speaker_to_label={"ANN": "c1", "BOB": "c1"},
        label_to_speaker={"c1": "ANN"},
        overlap_seconds={},
        method="time_alignment",
    )

    rows = speakers.attribute_turns(reference, hypothesis, mapping, frame_step=0.1)

    assert rows[0].correct_seconds == 1.0
    assert rows[1].correct_seconds == 0.0
    assert rows[1].wrong_seconds == 1.0
    assert rows[1].dominant_label == "c2"
