from __future__ import annotations

import pytest

from src import config
from src.asr.gemini.parse import (
    ParseError,
    normalize_interaction,
    parse_offset,
    parse_response,
)


def _word(text, start, end, speaker=None):
    annotation = {
        "type": "word_info",
        "text": text,
        "start_offset": start,
        "end_offset": end,
    }
    if speaker is not None:
        annotation["speaker"] = speaker
    return annotation


def _interaction(words, text=None):
    annotations = {"type": "text", "text": "", "annotations": words}
    return {
        "id": "interaction-1",
        "status": "completed",
        "output_text": text
        if text is not None
        else " ".join(word["text"] for word in words),
        "steps": [
            {
                "type": "model_output",
                "content": [annotations],
            }
        ],
    }


def _normalize(raw, duration=60.0):
    return normalize_interaction(
        raw,
        fixture_id="controlled-sdlc-review-en",
        meeting_id="controlled-meeting-en",
        model="gemini-3.5-transcribe",
        language="en-US",
        duration_seconds=duration,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.100s", 0.1),
        ("12s", 12.0),
        ("250ms", 0.25),
        ("00:00:01.500", 1.5),
        ("01:02:03.250", 3723.25),
        (2.5, 2.5),
        (None, None),
        ("", None),
    ],
)
def test_parse_offset_forms(value, expected) -> None:
    assert parse_offset(value) == expected


def test_parse_offset_rejects_garbage() -> None:
    with pytest.raises(ParseError):
        parse_offset("soon")


def test_parse_response_reads_word_annotations() -> None:
    parsed = parse_response(
        _interaction([_word("Hello", "0.100s", "0.400s", "spk_1")], text="Hello")
    )
    assert parsed.text == "Hello"
    assert [word.text for word in parsed.words] == ["Hello"]
    assert parsed.words[0].start == 0.1
    assert parsed.words[0].end == 0.4
    assert parsed.words[0].speaker == "spk_1"


def test_segments_split_on_speaker_change_and_keep_labels() -> None:
    transcript = _normalize(
        _interaction(
            [
                _word("Hello", "0.100s", "0.400s", "spk_1"),
                _word("there.", "0.400s", "0.800s", "spk_1"),
                _word("Hi.", "0.900s", "1.200s", "spk_2"),
            ]
        )
    )
    assert [segment.speaker_label for segment in transcript.segments] == [
        "spk_1",
        "spk_2",
    ]
    assert transcript.segments[0].text == "Hello there."
    assert transcript.segments[1].text == "Hi."
    assert transcript.segments[1].start == 0.9
    assert transcript.system == "gemini"


def test_segments_split_on_a_long_gap_for_the_same_speaker() -> None:
    transcript = _normalize(
        _interaction(
            [
                _word("First.", "0.000s", "0.400s", "spk_1"),
                _word("Later.", "5.000s", "5.400s", "spk_1"),
            ]
        )
    )
    assert len(transcript.segments) == 2
    assert transcript.segments[1].start == 5.0


def test_missing_speaker_becomes_unknown() -> None:
    transcript = _normalize(
        _interaction([_word("Hello", "0.100s", "0.400s")])
    )
    assert transcript.segments[0].speaker_label == config.UNKNOWN_SPEAKER


def test_no_word_annotations_uses_output_text_and_duration() -> None:
    raw = {
        "id": "interaction-1",
        "status": "completed",
        "output_text": "A whole transcript without annotations.",
        "steps": [],
    }
    transcript = _normalize(raw, duration=42.5)
    assert len(transcript.segments) == 1
    assert transcript.segments[0].start == 0.0
    assert transcript.segments[0].end == 42.5
    assert transcript.segments[0].speaker_label == config.UNKNOWN_SPEAKER


def test_text_falls_back_to_step_content_when_output_text_is_absent() -> None:
    raw = {
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "From the steps."}],
            }
        ]
    }
    parsed = parse_response(raw)
    assert parsed.text == "From the steps."


def test_empty_response_is_an_error() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_response({"steps": [], "output_text": ""})
    assert "neither output_text nor word_info" in str(excinfo.value)


def test_word_ending_before_it_starts_is_an_error() -> None:
    with pytest.raises(ParseError):
        _normalize(
            _interaction([_word("Broken", "2.000s", "1.000s", "spk_1")])
        )


def test_words_keep_anonymous_labels_and_are_not_renamed() -> None:
    transcript = _normalize(
        _interaction([_word("Hello", "0.100s", "0.400s", "spk_1")])
    )
    assert transcript.segments[0].words[0].speaker == "spk_1"
    assert transcript.segments[0].speaker_label == "spk_1"
    assert "Ann" not in transcript.full_text()
