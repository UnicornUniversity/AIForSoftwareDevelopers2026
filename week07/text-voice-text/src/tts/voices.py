"""Resolve each fixture participant to one stable synthetic Gemini voice.

The voice plan lives in :mod:`src.config`. This module checks it against the
fixture metadata: every participant must have a voice, the voice gender must
match the metadata, the two male voices must differ, and every name must be a
documented prebuilt voice. It never infers identity from a transcript.
"""

from __future__ import annotations

from dataclasses import dataclass

from src import config
from src.schema import MeetingMetadata, MeetingScript, SchemaError


@dataclass(frozen=True)
class VoiceAssignment:
    speaker_id: str
    full_name: str
    gender: str
    voice_name: str
    style: str
    rationale: str


def voice_assignments(
    script: MeetingScript,
    metadata: MeetingMetadata,
    plan: dict[str, config.VoiceProfile] | None = None,
) -> list[VoiceAssignment]:
    """Return the voice assignment for each participant in script order.

    Raises:
        SchemaError: if the plan is incomplete or inconsistent with metadata.
    """

    active_plan = plan if plan is not None else config.VOICE_PLAN
    errors = validate_voice_plan(active_plan, metadata)
    if errors:
        raise SchemaError(errors)

    assignments: list[VoiceAssignment] = []
    for speaker_id in script.participant_ids:
        profile = active_plan[speaker_id]
        participant = metadata.participant_by_id(speaker_id)
        assignments.append(
            VoiceAssignment(
                speaker_id=speaker_id,
                full_name=participant.full_name if participant else profile.full_name,
                gender=participant.gender if participant else profile.gender,
                voice_name=profile.voice_name,
                style=profile.style,
                rationale=profile.rationale,
            )
        )
    return assignments


def validate_voice_plan(
    plan: dict[str, config.VoiceProfile],
    metadata: MeetingMetadata,
    *,
    allowed_voices: frozenset[str] | None = None,
) -> list[str]:
    """Return problems with a voice plan; an empty list means valid."""

    errors: list[str] = []
    allowed = allowed_voices if allowed_voices is not None else config.PREBUILT_VOICES

    metadata_ids = {participant.id for participant in metadata.participants}
    missing = metadata_ids - set(plan)
    extra = set(plan) - metadata_ids
    if missing:
        errors.append(f"voice plan is missing participants: {sorted(missing)}")
    if extra:
        errors.append(f"voice plan has unknown participants: {sorted(extra)}")

    for participant in metadata.participants:
        profile = plan.get(participant.id)
        if profile is None:
            continue
        if profile.gender != participant.gender:
            errors.append(
                f"{participant.id}: voice plan gender {profile.gender!r} does not "
                f"match metadata gender {participant.gender!r}"
            )
        if not profile.voice_name:
            errors.append(f"{participant.id}: voice name is empty")
        elif profile.voice_name not in allowed:
            errors.append(
                f"{participant.id}: voice {profile.voice_name!r} is not in the "
                "documented prebuilt voice set"
            )
        if not profile.style.strip():
            errors.append(f"{participant.id}: delivery style is empty")

    # Every two participants of the same gender must use different voices;
    # otherwise diarization has no acoustic reason to separate them.
    by_gender: dict[str, list[tuple[str, str]]] = {}
    for participant in metadata.participants:
        profile = plan.get(participant.id)
        if profile is not None:
            by_gender.setdefault(participant.gender, []).append(
                (participant.id, profile.voice_name)
            )
    for gender, entries in by_gender.items():
        used: dict[str, str] = {}
        for speaker_id, voice_name in entries:
            if voice_name in used:
                errors.append(
                    f"{gender} participants {used[voice_name]} and {speaker_id} "
                    f"share the voice {voice_name!r}; they must be distinct"
                )
            else:
                used[voice_name] = speaker_id

    return errors
