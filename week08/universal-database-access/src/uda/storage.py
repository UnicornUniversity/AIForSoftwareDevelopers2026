"""Write-once persistence for reviewable candidates.

A candidate is written only after it re-validates against the same physical
schema. ``Candidate`` itself permits only the ``pending_review`` status, so
persistence cannot publish or approve anything. An existing target is never
overwritten.
"""

import os
import tempfile
from pathlib import Path

from uda.models import Candidate, TableSchema
from uda.validation import validate_candidate


class CandidateStorageError(ValueError):
    """Raised when a candidate is not safe to persist."""


def save_candidate(
    path: Path | str,
    schema: TableSchema,
    candidate: Candidate,
) -> Path:
    """Validate ``candidate`` and publish it once as UTF-8 JSON.

    Parent directories are created. Returns the written path. Raises
    ``CandidateStorageError`` if the candidate is invalid or the target exists;
    a failed write leaves no partial candidate.
    """
    issues = validate_candidate(schema, candidate)
    if issues:
        codes = ", ".join(issue.code for issue in issues)
        raise CandidateStorageError(f"refusing to save invalid candidate [{codes}]")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = candidate.model_dump_json(indent=2) + "\n"

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)

    try:
        os.link(temp_path, target)
    except FileExistsError as exc:
        raise CandidateStorageError(
            f"candidate already exists: {target}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return target
