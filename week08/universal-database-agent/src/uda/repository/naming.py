"""Deterministic, Windows-safe naming for DDL Repository artifacts.

Physical IDs contain ``/`` separators and may contain characters that Windows rejects in
file names. Filenames therefore combine a readable slug with a hash of the full Physical
ID. The hash keeps names unique, including objects that differ only by case (Windows file
systems are case-insensitive).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from ..errors import RepositoryPathError

SCHEMA_DIRECTORY = "schemas"
OBJECT_DIRECTORY = "objects"
DDL_DIRECTORY = "ddl"
ISSUES_FILENAME = "issues.json"
MANIFEST_FILENAME = "manifest.json"

_OBJECT_TYPES = frozenset({"table", "view"})
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CLOCK$",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_MAX_SLUG_LENGTH = 48


def slugify(value: str, *, max_length: int = _MAX_SLUG_LENGTH) -> str:
    """Return a readable filename component that is safe on Windows."""

    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = _INVALID_FILENAME_CHARS.sub("_", cleaned)
    cleaned = _WHITESPACE.sub("_", cleaned)
    cleaned = cleaned.strip(" ._")
    if not cleaned:
        cleaned = "unnamed"
    if cleaned.split(".", 1)[0].upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" ._") or "unnamed"
    return cleaned


def _artifact_stem(physical_id: str) -> str:
    parts = physical_id.split("/")
    if len(parts) < 4 or not all(parts):
        raise RepositoryPathError(
            f"Cannot derive a repository file name from Physical ID: {physical_id!r}"
        )
    digest = hashlib.sha256(physical_id.encode("utf-8")).hexdigest()[:12]
    labels = [slugify(unquote(part)) for part in parts[2:]]
    return f"{'__'.join(labels)}--{digest}"


def artifact_filename(physical_id: str) -> str:
    """Return the deterministic JSON file name for one schema or object Physical ID."""

    return f"{_artifact_stem(physical_id)}.json"


def ddl_filename(physical_id: str) -> str:
    """Return the deterministic SQL file name for one object Physical ID."""

    return f"{_artifact_stem(physical_id)}.sql"


def ddl_relative_path(physical_id: str) -> PurePosixPath:
    """Return the repository-relative path for one object's SQL DDL artifact."""

    return PurePosixPath(DDL_DIRECTORY) / ddl_filename(physical_id)


def artifact_relative_path(kind: str, physical_id: str) -> PurePosixPath:
    """Return the repository-relative path for a schema or table/view artifact."""

    if kind == "schema":
        directory = SCHEMA_DIRECTORY
    elif kind in _OBJECT_TYPES:
        directory = OBJECT_DIRECTORY
    else:
        raise RepositoryPathError(f"Unsupported repository artifact kind: {kind!r}")
    return PurePosixPath(directory) / artifact_filename(physical_id)


def safe_relative_path(value: str | Path) -> PurePosixPath:
    """Validate a repository-relative path and return it in POSIX form."""

    text = str(value).replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute():
        raise RepositoryPathError(f"Repository path must be relative: {value!r}")
    parts = path.parts
    if ".." in parts:
        raise RepositoryPathError(
            f"Repository path escapes the managed root: {value!r}"
        )
    if not parts or any(part in {"", "."} for part in parts):
        raise RepositoryPathError(f"Repository path is not normalized: {value!r}")
    if ":" in parts[0]:
        raise RepositoryPathError(f"Repository path must not contain a drive: {value!r}")
    return path


def resolve_within(root: Path, relative: str | Path) -> Path:
    """Resolve a repository-relative path, refusing anything outside ``root``."""

    root_path = root.resolve()
    relative_path = safe_relative_path(relative)
    candidate = (root_path / Path(*relative_path.parts)).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise RepositoryPathError(
            f"Repository path escapes the managed root: {relative!r}"
        ) from exc
    return candidate
