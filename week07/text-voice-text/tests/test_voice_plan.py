from __future__ import annotations

import dataclasses

from src import config
from src.fixtures import load_fixture
from src.tts.voices import validate_voice_plan, voice_assignments


def test_config_voice_plan_matches_metadata(fixture) -> None:
    assert validate_voice_plan(config.VOICE_PLAN, fixture.metadata) == []


def test_every_participant_gets_one_stable_voice(fixture) -> None:
    assignments = voice_assignments(fixture.script, fixture.metadata)
    by_id = {assignment.speaker_id: assignment for assignment in assignments}
    assert set(by_id) == {"ANN", "BOB", "GREG"}
    assert [a.speaker_id for a in assignments] == list(fixture.script.participant_ids)
    assert len({a.voice_name for a in assignments}) == 3
    assert by_id["ANN"].gender == "female"
    assert by_id["BOB"].gender == "male"
    assert by_id["GREG"].gender == "male"


def test_two_male_voices_are_distinct(fixture) -> None:
    assignments = {
        a.speaker_id: a for a in voice_assignments(fixture.script, fixture.metadata)
    }
    assert assignments["BOB"].voice_name != assignments["GREG"].voice_name


def test_all_selected_voices_are_documented_prebuilt_voices() -> None:
    for profile in config.VOICE_PLAN.values():
        assert profile.voice_name in config.PREBUILT_VOICES


def test_gender_mismatch_is_rejected(fixture) -> None:
    plan = dict(config.VOICE_PLAN)
    plan["ANN"] = dataclasses.replace(plan["ANN"], gender="male")
    errors = validate_voice_plan(plan, fixture.metadata)
    assert any("gender" in error for error in errors)


def test_shared_voice_between_same_gender_speakers_is_rejected(fixture) -> None:
    plan = dict(config.VOICE_PLAN)
    plan["GREG"] = dataclasses.replace(plan["GREG"], voice_name=plan["BOB"].voice_name)
    errors = validate_voice_plan(plan, fixture.metadata)
    assert any("share the voice" in error for error in errors)


def test_unknown_voice_is_rejected(fixture) -> None:
    plan = dict(config.VOICE_PLAN)
    plan["BOB"] = dataclasses.replace(plan["BOB"], voice_name="NotAVoice")
    errors = validate_voice_plan(plan, fixture.metadata)
    assert any("not in the documented prebuilt voice set" in error for error in errors)


def test_missing_participant_is_rejected(fixture) -> None:
    plan = dict(config.VOICE_PLAN)
    del plan["GREG"]
    errors = validate_voice_plan(plan, fixture.metadata)
    assert any("missing participants" in error for error in errors)


def test_style_is_never_a_participant_name() -> None:
    for profile in config.VOICE_PLAN.values():
        lowered = profile.style.lower()
        assert profile.full_name.lower() not in lowered
        assert profile.voice_name.lower() not in lowered
