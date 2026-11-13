from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.fixtures import load_fixture, load_metadata, load_script
from src.schema import (
    MeetingScript,
    SchemaError,
    validate_ground_truth,
    validate_script,
    word_count,
)


def test_controlled_fixture_loads_and_validates() -> None:
    fixture = load_fixture()
    assert fixture.script.fixture_id == "controlled-sdlc-review-en"
    assert len(fixture.script.turns) == 39
    assert fixture.script.participant_ids == ("ANN", "BOB", "GREG")
    assert {p.id for p in fixture.metadata.participants} == {"ANN", "BOB", "GREG"}
    assert fixture.script.fictional is True


def test_turns_are_contiguous_and_non_empty() -> None:
    script = load_script()
    assert [turn.index for turn in script.turns] == list(range(1, 40))
    assert all(turn.text.strip() for turn in script.turns)


def test_ground_truth_is_exact_projection_of_script() -> None:
    fixture = load_fixture()
    assert validate_ground_truth(fixture.script, fixture.ground_truth) == []
    assert [t.text for t in fixture.ground_truth.turns] == [
        t.text for t in fixture.script.turns
    ]
    assert [t.speaker_id for t in fixture.ground_truth.turns] == [
        t.speaker_id for t in fixture.script.turns
    ]


def test_participant_names_do_not_appear_in_spoken_text() -> None:
    fixture = load_fixture()
    joined = " ".join(turn.text for turn in fixture.script.turns).lower()
    for name in ("ann", "bob", "greg", "smith", "hawkins", "cox"):
        assert name not in joined.split()


def test_required_technical_terms_are_present() -> None:
    fixture = load_fixture()
    joined = " ".join(turn.text for turn in fixture.script.turns).lower()
    for term in (
        "api",
        "rest",
        "postgresql",
        "docker",
        "ci/cd",
        "staging",
        "deployment",
        "regression",
        "authentication",
    ):
        assert term in joined, term


def test_metadata_voice_requirements_match_gender() -> None:
    metadata = load_metadata()
    for participant in metadata.participants:
        assert participant.voice_requirements["gender"] == participant.gender
        assert "synthetic" in participant.voice_requirements["constraint"].lower()


def test_missing_fixture_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_fixture(tmp_path)


def test_invalid_turn_indexes_are_reported(tmp_path: Path) -> None:
    fixture = load_fixture()
    payload = fixture.script.to_dict()
    payload["turns"][0]["index"] = 99
    broken = MeetingScript.from_dict(payload)
    errors = validate_script(broken)
    assert any("indexes" in error for error in errors)


def test_metadata_turn_count_mismatch_is_reported() -> None:
    fixture = load_fixture()
    metadata = fixture.metadata
    payload = json.loads(json.dumps(metadata.raw))
    payload["turn_count"] = 1
    from src.schema import MeetingMetadata

    broken = MeetingMetadata.from_dict(payload)
    errors = validate_script(fixture.script, broken)
    assert any("turn_count" in error for error in errors)


def test_word_count_is_consistent() -> None:
    fixture = load_fixture()
    assert word_count("hello, world!") == 2
    assert sum(word_count(t.text) for t in fixture.script.turns) == 586


def test_schema_error_lists_all_errors() -> None:
    error = SchemaError(["a", "b"])
    assert error.errors == ["a", "b"]
