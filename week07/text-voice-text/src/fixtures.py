"""Fixture loading and validation.

The fixture is the controlled three-person meeting at Brightline Components
Ltd. ``meeting_script.json`` is the authoring source; ``ground_truth.json`` is
its exact projection and is evaluation-only. Neither file may be sent to an ASR
system during a blind run — this module only loads them for TTS and evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src import config
from src.schema import (
    GroundTruth,
    MeetingMetadata,
    MeetingScript,
    SchemaError,
    load_json,
    validate_ground_truth,
    validate_script,
)


@dataclass(frozen=True)
class Fixture:
    """The three files that describe the primary lab meeting."""

    script: MeetingScript
    metadata: MeetingMetadata
    ground_truth: GroundTruth
    fixture_dir: Path

    def participant_names(self) -> dict[str, str]:
        return {p.id: p.full_name for p in self.metadata.participants}


def load_fixture(fixture_dir: Path | None = None) -> Fixture:
    """Load and cross-validate the controlled fixture.

    Raises:
        FileNotFoundError: if a required file is missing.
        SchemaError: if the files disagree or fail structural validation.
    """

    directory = Path(fixture_dir) if fixture_dir is not None else config.FIXTURE_DIR
    script_path = directory / "meeting_script.json"
    metadata_path = directory / "meeting_metadata.json"
    ground_truth_path = directory / "ground_truth.json"

    for path in (script_path, metadata_path, ground_truth_path):
        if not path.exists():
            raise FileNotFoundError(f"fixture file not found: {path}")

    script = MeetingScript.from_dict(load_json(script_path))
    metadata = MeetingMetadata.from_dict(load_json(metadata_path))
    ground_truth = GroundTruth.from_dict(load_json(ground_truth_path))

    errors = validate_script(script, metadata)
    errors.extend(validate_ground_truth(script, ground_truth))
    if errors:
        raise SchemaError(errors)

    return Fixture(
        script=script,
        metadata=metadata,
        ground_truth=ground_truth,
        fixture_dir=directory,
    )


def load_script(fixture_dir: Path | None = None) -> MeetingScript:
    directory = Path(fixture_dir) if fixture_dir is not None else config.FIXTURE_DIR
    script = MeetingScript.from_dict(load_json(directory / "meeting_script.json"))
    errors = validate_script(script)
    if errors:
        raise SchemaError(errors)
    return script


def load_metadata(fixture_dir: Path | None = None) -> MeetingMetadata:
    directory = Path(fixture_dir) if fixture_dir is not None else config.FIXTURE_DIR
    return MeetingMetadata.from_dict(load_json(directory / "meeting_metadata.json"))
