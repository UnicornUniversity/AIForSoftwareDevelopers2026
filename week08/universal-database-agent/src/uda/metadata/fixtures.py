"""Recorded metadata fixtures for offline extraction (``Q-06``).

Fixtures let the DDL Repository writer and its tests run without SMO or a live SQL
Server. A fixture is the same normalized metadata model produced by the adapter, wrapped
in a small versioned envelope. It contains metadata only; never table rows.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..errors import FixtureError
from .models import DatabaseMetadata

FIXTURE_FORMAT = "uda.database-metadata"
FIXTURE_VERSION = "1.0"


def fixture_payload(metadata: DatabaseMetadata) -> dict[str, Any]:
    return {
        "format": FIXTURE_FORMAT,
        "fixture_version": FIXTURE_VERSION,
        "metadata": metadata.model_dump(mode="json", by_alias=True),
    }


def load_metadata_fixture(path: Path) -> DatabaseMetadata:
    """Load a normalized metadata fixture, accepting envelope or raw metadata JSON."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"Could not read metadata fixture {path}.") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"Metadata fixture is not valid JSON: {path}") from exc

    payload: Any = raw
    if isinstance(raw, dict) and "metadata" in raw:
        fixture_version = raw.get("fixture_version")
        if fixture_version is not None and fixture_version != FIXTURE_VERSION:
            raise FixtureError(
                f"Unsupported fixture version {fixture_version!r} in {path}."
            )
        payload = raw["metadata"]
    try:
        return DatabaseMetadata.model_validate(payload)
    except ValidationError as exc:
        raise FixtureError(
            f"Metadata fixture does not match the normalized model: {path} ({exc})"
        ) from exc


def filter_metadata_schemas(
    metadata: DatabaseMetadata, schemas: Sequence[str] | None
) -> DatabaseMetadata:
    """Return a fixture subset matching an explicit schema selection."""

    if schemas is None:
        return metadata
    selected = set(schemas)
    kept_objects = tuple(
        item for item in metadata.objects if item.schema_name in selected
    )
    kept_ids = {item.physical_id for item in kept_objects}
    kept_issues = tuple(
        issue
        for issue in metadata.issues
        if issue.object_id is None or issue.object_id in kept_ids
    )
    return metadata.model_copy(
        update={
            "schemas": tuple(
                item for item in metadata.schemas if item.name in selected
            ),
            "objects": kept_objects,
            "issues": kept_issues,
        }
    )
