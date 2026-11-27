"""Immutable candidate storage for object-level discovery.

Candidates live under ``data/knowledge/discovery-runs/`` and are never canonical
proposals. One request/execution identity owns one directory:

    requests/objects/<execution_key>/
        request.json      request identity, prompt and model provenance
        status.json       terminal execution status for this key
        result.json       validated candidate payload (written once)
        response.sha256   hash of the raw model response (no raw text is stored)

Run summaries live under ``runs/<run_id>/run.json``. Existing result records are never
overwritten. A reuse lookup returns a stored successful result so unchanged inputs do not
call the model again; an existing terminal failure is reported rather than silently retried.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..errors import (
    CandidateRepositoryValidationError,
    CandidateRepositoryWriteError,
)
from ..repository.naming import resolve_within
from ..repository.serialization import canonical_bytes, sha256_hex
from .object_models import (
    ObjectCandidate,
    ObjectRequestRecord,
    ObjectRunRecord,
    ObjectStatusRecord,
)

_DISCOVERY_RUNS_DIRECTORY = "discovery-runs"
_REQUEST_ROOT = "requests/objects"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_EXECUTION_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CandidateLookup:
    """An existing terminal record for one execution key."""

    status: str
    candidate: ObjectCandidate | None = None
    status_record: ObjectStatusRecord | None = None


def format_timestamp(value: datetime) -> str:
    """Format a timestamp in the repository's canonical UTC form."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateRepositoryValidationError(
            f"Candidate artifact {path.name!r} is not valid JSON "
            f"({type(exc).__name__})."
        ) from exc


def _validate_record(path: Path, model: Any) -> Any:
    try:
        return model.model_validate(_read_json(path))
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: "
            f"{error['msg']}"
            for error in exc.errors()
        )
        raise CandidateRepositoryValidationError(
            f"Candidate artifact {path.name!r} is invalid ({details})."
        ) from exc


class CandidateStore:
    """Safe, append-only storage for object-level discovery candidates."""

    def __init__(
        self,
        root: Path,
        *,
        project_root: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self._guard_root()

    def _guard_root(self) -> None:
        resolved = self.root.resolve()
        project = self.project_root.resolve()
        try:
            resolved.relative_to(project)
        except ValueError:
            return
        knowledge = (project / "data" / "knowledge").resolve()
        try:
            relative = resolved.relative_to(knowledge)
        except ValueError as exc:
            raise CandidateRepositoryWriteError(
                "Discovery candidates must be written under "
                "data/knowledge/discovery-runs/."
            ) from exc
        if not relative.parts or relative.parts[0] != _DISCOVERY_RUNS_DIRECTORY:
            raise CandidateRepositoryWriteError(
                "Discovery candidates must be written under "
                "data/knowledge/discovery-runs/; refusing to write to "
                f"{self.root}."
            )

    def _request_dir(self, execution_key: str) -> Path:
        if not _EXECUTION_KEY_PATTERN.fullmatch(execution_key):
            raise CandidateRepositoryValidationError(
                "Invalid object-level execution key."
            )
        return resolve_within(self.root, f"{_REQUEST_ROOT}/{execution_key}")

    @staticmethod
    def _write_new(path: Path, content: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                os.link(temporary, path)
            except FileExistsError as exc:
                raise CandidateRepositoryWriteError(
                    f"Refusing to overwrite existing candidate artifact "
                    f"{path.name!r}."
                ) from exc
            finally:
                temporary.unlink(missing_ok=True)
        except CandidateRepositoryWriteError:
            raise
        except OSError as exc:
            raise CandidateRepositoryWriteError(
                f"Could not write candidate artifact {path.name!r} "
                f"({type(exc).__name__})."
            ) from exc

    @classmethod
    def _write_once(cls, path: Path, content: bytes) -> bool:
        if path.is_file():
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise CandidateRepositoryValidationError(
                    f"Could not read candidate artifact {path.name!r} "
                    f"({type(exc).__name__})."
                ) from exc
            if existing == content:
                return False
            raise CandidateRepositoryWriteError(
                f"Refusing to overwrite differing candidate artifact "
                f"{path.name!r}."
            )
        cls._write_new(path, content)
        return True

    def lookup(self, execution_key: str) -> CandidateLookup | None:
        """Return an existing terminal result for one execution key, if any."""

        directory = self._request_dir(execution_key)
        if not directory.is_dir():
            return None
        result_path = directory / "result.json"
        if result_path.is_file():
            candidate = _validate_record(result_path, ObjectCandidate)
            if candidate.execution_key != execution_key:
                raise CandidateRepositoryValidationError(
                    "Stored candidate execution key does not match its directory."
                )
            return CandidateLookup(status="succeeded", candidate=candidate)
        status_path = directory / "status.json"
        if status_path.is_file():
            record = _validate_record(status_path, ObjectStatusRecord)
            if record.execution_key != execution_key:
                raise CandidateRepositoryValidationError(
                    "Stored status execution key does not match its directory."
                )
            if record.status == "succeeded":
                raise CandidateRepositoryValidationError(
                    "Stored status reports success but no candidate result exists."
                )
            return CandidateLookup(status=record.status, status_record=record)
        return None

    def write_request(self, record: ObjectRequestRecord) -> bool:
        path = self._request_dir(record.execution_key) / "request.json"
        return self._write_once(
            path, canonical_bytes(record.model_dump(mode="json", by_alias=True))
        )

    def write_result(self, candidate: ObjectCandidate) -> bool:
        path = self._request_dir(candidate.execution_key) / "result.json"
        return self._write_once(
            path, canonical_bytes(candidate.model_dump(mode="json", by_alias=True))
        )

    def write_status(self, record: ObjectStatusRecord) -> bool:
        path = self._request_dir(record.execution_key) / "status.json"
        return self._write_once(
            path, canonical_bytes(record.model_dump(mode="json", by_alias=True))
        )

    def write_response_hash(self, execution_key: str, raw_response: str) -> bool:
        path = self._request_dir(execution_key) / "response.sha256"
        digest = sha256_hex(raw_response.encode("utf-8"))
        return self._write_once(path, (digest + "\n").encode("ascii"))

    def write_run(self, record: ObjectRunRecord) -> Path:
        if not _RUN_ID_PATTERN.fullmatch(record.run_id):
            raise CandidateRepositoryWriteError("Invalid discovery run ID.")
        path = resolve_within(self.root, f"runs/{record.run_id}/run.json")
        self._write_new(
            path, canonical_bytes(record.model_dump(mode="json", by_alias=True))
        )
        return path
