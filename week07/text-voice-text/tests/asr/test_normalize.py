from __future__ import annotations

from src import config
from src.asr.whisperx.normalize import NormalizationError, normalize_result
from src.schema import NormalizedTranscript


def _raw(segments, language="en"):
    return {"language": language, "segments": segments}


def _normalize(raw):
    return normalize_result(
        raw,
        fixture_id="fx",
        meeting_id="mtg",
        model="small.en",
    )


def test_normalizes_segments_and_words() -> None:
    raw = _raw(
        [
            {
                "start": 0.5,
                "end": 2.0,
                "text": "  Hello there. ",
                "speaker": "SPEAKER_01",
                "words": [
                    {
                        "word": " Hello",
                        "start": 0.5,
                        "end": 1.0,
                        "score": 0.9,
                        "speaker": "SPEAKER_01",
                    },
                    {
                        "word": " there.",
                        "start": 1.0,
                        "end": 2.0,
                        "score": 0.8,
                        "speaker": "SPEAKER_01",
                    },
                ],
            }
        ]
    )
    transcript = _normalize(raw)
    assert transcript.system == "whisperx"
    assert transcript.model == "small.en"
    assert transcript.language == "en"
    assert len(transcript.segments) == 1
    segment = transcript.segments[0]
    assert segment.index == 1
    assert segment.text == "Hello there."
    assert segment.speaker_label == "SPEAKER_01"
    assert [word.text for word in segment.words] == ["Hello", "there."]
    assert segment.words[0].score == 0.9
    assert segment.words[1].speaker == "SPEAKER_01"


def test_segments_are_ordered_by_start_and_renumbered() -> None:
    raw = _raw(
        [
            {"start": 3.0, "end": 4.0, "text": "third", "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "text": "first", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 3.0, "text": "second", "speaker": "SPEAKER_00"},
        ]
    )
    transcript = _normalize(raw)
    assert [segment.text for segment in transcript.segments] == [
        "first",
        "second",
        "third",
    ]
    assert [segment.index for segment in transcript.segments] == [1, 2, 3]


def test_missing_speaker_becomes_unknown() -> None:
    raw = _raw([{"start": 0.0, "end": 1.0, "text": "Hello."}])
    transcript = _normalize(raw)
    assert transcript.segments[0].speaker_label == config.UNKNOWN_SPEAKER


def test_dominant_word_speaker_fills_missing_segment_speaker() -> None:
    raw = _raw(
        [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "A B C",
                "words": [
                    {"word": "A", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
                    {"word": "B", "start": 0.5, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "C", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
                ],
            }
        ]
    )
    transcript = _normalize(raw)
    assert transcript.segments[0].speaker_label == "SPEAKER_00"


def test_word_speaker_defaults_to_the_segment_speaker() -> None:
    raw = _raw(
        [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Hello.",
                "speaker": "SPEAKER_02",
                "words": [{"word": "Hello.", "start": 0.0, "end": 1.0}],
            }
        ]
    )
    transcript = _normalize(raw)
    assert transcript.segments[0].words[0].speaker == "SPEAKER_02"


def test_empty_segments_are_dropped_but_indices_stay_contiguous() -> None:
    raw = _raw(
        [
            {"start": 0.0, "end": 0.5, "text": "   "},
            {"start": 0.5, "end": 1.0, "text": "Kept.", "speaker": "SPEAKER_00"},
        ]
    )
    transcript = _normalize(raw)
    assert len(transcript.segments) == 1
    assert transcript.segments[0].index == 1
    assert transcript.segments[0].text == "Kept."


def test_missing_word_timings_are_allowed() -> None:
    raw = _raw(
        [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Hello.",
                "words": [{"word": "Hello."}],
            }
        ]
    )
    word = _normalize(raw).segments[0].words[0]
    assert word.start is None
    assert word.end is None


def test_result_without_segments_is_rejected() -> None:
    try:
        _normalize({"language": "en"})
    except NormalizationError as exc:
        assert "segments" in str(exc)
    else:  # pragma: no cover - explicit failure message
        raise AssertionError("expected NormalizationError")


def test_end_before_start_is_rejected() -> None:
    try:
        _normalize(_raw([{"start": 2.0, "end": 1.0, "text": "Bad."}]))
    except NormalizationError as exc:
        assert "ends before" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected NormalizationError")


def test_anonymous_labels_are_preserved_exactly() -> None:
    raw = _raw(
        [
            {"start": 0.0, "end": 1.0, "text": "Hi.", "speaker": "spk_1"},
            {"start": 1.0, "end": 2.0, "text": "Hello.", "speaker": "SPEAKER_00"},
        ]
    )
    transcript = _normalize(raw)
    assert [s.speaker_label for s in transcript.segments] == [
        "spk_1",
        "SPEAKER_00",
    ]
    serialized = str(transcript.to_dict())
    for name in ("ANN", "BOB", "GREG", "Ann Smith", "Bob Hawkins", "Greg Cox"):
        assert name not in serialized


def test_empty_transcript_is_allowed() -> None:
    transcript = _normalize(_raw([]))
    assert transcript.segments == ()
    assert transcript.full_text() == ""


def test_normalized_json_round_trips() -> None:
    raw = _raw(
        [
            {
                "start": 0.0,
                "end": 1.5,
                "text": "Hello there.",
                "speaker": "SPEAKER_00",
                "words": [{"word": "Hello", "start": 0.0, "end": 0.75}],
            }
        ]
    )
    transcript = _normalize(raw)
    restored = NormalizedTranscript.from_dict(transcript.to_dict())
    assert restored == transcript
