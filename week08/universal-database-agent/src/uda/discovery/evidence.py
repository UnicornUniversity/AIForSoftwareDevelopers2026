"""Load the Phase 2 DDL Repository as structured discovery evidence.

Discovery reads only repository files. It never connects to the database and never writes
to the source database. Missing DDL or partial metadata is surfaced explicitly as a warning
rather than silently treated as complete.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from ..errors import DiscoveryInputError
from ..metadata.models import (
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    SchemaMetadata,
    TableMetadata,
)
from ..repository.manifest import DdlManifest
from ..repository.naming import resolve_within
from ..repository.serialization import sha256_hex
from ..repository.validation import validate_repository
from .models import DdlProvenance, SourceKind


@dataclass(frozen=True)
class DdlEvidence:
    """One extracted per-object SQL definition and its provenance."""

    physical_id: str
    provenance: DdlProvenance
    is_original_text: bool
    text: str
    path: str
    sha256: str


@dataclass(frozen=True)
class StructuralEvidence:
    """Validated physical facts available to prompt assembly and proposal validation."""

    root: Path
    manifest: DdlManifest
    metadata: DatabaseMetadata
    ddl: Mapping[str, DdlEvidence]
    warnings: tuple[str, ...]
    object_ids: frozenset[str]
    column_ids: frozenset[str]
    primary_key_ids: frozenset[str]
    foreign_key_ids: frozenset[str]
    index_ids: frozenset[str]
    ddl_object_ids: frozenset[str]

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot.id

    @property
    def database(self) -> DatabaseIdentity:
        return self.metadata.identity

    @property
    def object_count(self) -> int:
        return len(self.metadata.objects)

    @property
    def table_count(self) -> int:
        return self.metadata.table_count

    @property
    def view_count(self) -> int:
        return self.metadata.view_count

    @property
    def ddl_status(self) -> str:
        section = self.manifest.extraction.ddl
        return section.status if section is not None else "not_requested"

    def known_ids(self, kind: SourceKind) -> frozenset[str]:
        """Return the valid Physical IDs for one source-reference kind."""

        return {
            "object": self.object_ids,
            "column": self.column_ids,
            "primary_key": self.primary_key_ids,
            "foreign_key": self.foreign_key_ids,
            "index": self.index_ids,
            "ddl": self.ddl_object_ids,
        }[kind]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryInputError(
            f"Could not read DDL Repository artifact {path.name!r} "
            f"({type(exc).__name__})."
        ) from exc


def _read_verified_bytes(root: Path, relative: str, expected: str) -> bytes:
    try:
        path = resolve_within(root, relative)
        data = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise DiscoveryInputError(
            f"Could not read DDL Repository artifact {relative!r} "
            f"({type(exc).__name__})."
        ) from exc
    if sha256_hex(data) != expected:
        raise DiscoveryInputError(
            f"DDL Repository artifact {relative!r} does not match its manifest hash."
        )
    return data


def _load_objects(
    root: Path, manifest: DdlManifest
) -> tuple[tuple[SchemaMetadata, ...], tuple[TableMetadata, ...]]:
    schemas: list[SchemaMetadata] = []
    objects: list[TableMetadata] = []
    try:
        for entry in sorted(manifest.artifacts.schemas, key=lambda item: item.path):
            raw = json.loads(
                _read_verified_bytes(root, entry.path, entry.sha256).decode("utf-8")
            )
            schema = SchemaMetadata.model_validate(raw)
            if schema.physical_id != entry.physical_id:
                raise DiscoveryInputError(
                    f"Schema artifact {entry.path!r} does not match its manifest ID."
                )
            schemas.append(schema)
        for entry in sorted(manifest.artifacts.objects, key=lambda item: item.path):
            raw = json.loads(
                _read_verified_bytes(root, entry.path, entry.sha256).decode("utf-8")
            )
            table = TableMetadata.model_validate(raw)
            if table.physical_id != entry.physical_id:
                raise DiscoveryInputError(
                    f"Object artifact {entry.path!r} does not match its manifest ID."
                )
            if table.object_type != entry.kind:
                raise DiscoveryInputError(
                    f"Object artifact {entry.path!r} has the wrong object type."
                )
            objects.append(table)
    except (ValidationError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryInputError(
            f"DDL Repository metadata does not match the metadata model "
            f"({type(exc).__name__})."
        ) from exc
    return tuple(schemas), tuple(objects)


def _load_issues(root: Path, manifest: DdlManifest) -> tuple[ExtractionIssue, ...]:
    relative = manifest.extraction.issues.path
    data = _read_verified_bytes(
        root, relative, manifest.extraction.issues.sha256
    )
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryInputError(
            f"Issues artifact is not valid JSON ({type(exc).__name__})."
        ) from exc
    if not isinstance(raw, list):
        raise DiscoveryInputError("Issues artifact must contain a JSON array.")
    try:
        return tuple(ExtractionIssue.model_validate(item) for item in raw)
    except ValidationError as exc:
        raise DiscoveryInputError(
            f"Issues artifact does not match the metadata model "
            f"({type(exc).__name__})."
        ) from exc


def _load_ddl(
    root: Path, manifest: DdlManifest, warnings: list[str]
) -> dict[str, DdlEvidence]:
    section = manifest.extraction.ddl
    if section is None:
        warnings.append(
            "DDL extraction is not recorded in the manifest (legacy repository)."
        )
        return {}
    if section.status != "complete":
        warnings.append(
            f"DDL extraction status is {section.status}; some objects have no SQL "
            "definition in discovery evidence."
        )
    ddl: dict[str, DdlEvidence] = {}
    for entry in sorted(section.objects, key=lambda item: item.physical_id):
        if entry.status != "extracted":
            continue
        if not entry.path or not entry.sha256 or not entry.provenance:
            raise DiscoveryInputError(
                f"Extracted DDL entry {entry.physical_id} has no path, hash, or "
                "provenance."
            )
        provenance = entry.provenance
        if provenance not in {"smo_scripter", "server_module_definition"}:
            raise DiscoveryInputError(
                f"DDL entry {entry.physical_id} has unknown provenance "
                f"{provenance!r}."
            )
        typed_provenance = cast(DdlProvenance, provenance)
        expected_original = typed_provenance == "server_module_definition"
        if entry.is_original_text != expected_original:
            raise DiscoveryInputError(
                f"DDL entry {entry.physical_id} misrepresents its provenance: "
                f"{provenance!r} with is_original_text={entry.is_original_text!r}."
            )
        data = _read_verified_bytes(root, entry.path, entry.sha256)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DiscoveryInputError(
                f"DDL artifact {entry.path!r} is not UTF-8 text."
            ) from exc
        ddl[entry.physical_id] = DdlEvidence(
            physical_id=entry.physical_id,
            provenance=typed_provenance,
            is_original_text=entry.is_original_text,
            text=text,
            path=entry.path,
            sha256=entry.sha256,
        )
    return ddl


def load_ddl_repository(root: Path) -> StructuralEvidence:
    """Validate and load one DDL Repository snapshot as discovery evidence."""

    validation = validate_repository(root)
    if not validation.valid:
        raise DiscoveryInputError(
            "DDL Repository is invalid: " + "; ".join(validation.errors)
        )
    manifest = validation.manifest
    if manifest is None:  # defensive; validate_repository sets it for valid repositories
        raise DiscoveryInputError("DDL Repository manifest is missing.")

    schemas, objects = _load_objects(root, manifest)
    issues = _load_issues(root, manifest)
    warnings: list[str] = []
    if manifest.snapshot.status != "complete" or issues:
        warnings.append(
            f"DDL Repository snapshot is {manifest.snapshot.status} with "
            f"{len(issues)} extraction issue(s); discovery must treat missing metadata "
            "as unknown, not as absence."
        )
    ddl = _load_ddl(root, manifest, warnings)

    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(
            platform=manifest.database.platform, database=manifest.database.name
        ),
        schemas=tuple(sorted(schemas, key=lambda item: item.name)),
        objects=tuple(sorted(objects, key=lambda item: item.physical_id)),
        issues=tuple(
            sorted(issues, key=lambda item: (item.kind, item.object_id or "", item.detail))
        ),
    )

    object_ids = frozenset(item.physical_id for item in metadata.objects)
    column_ids = frozenset(
        column.physical_id for item in metadata.objects for column in item.columns
    )
    primary_key_ids = frozenset(
        item.primary_key.physical_id
        for item in metadata.objects
        if item.primary_key is not None and item.primary_key.physical_id is not None
    )
    foreign_key_ids = frozenset(
        key.physical_id
        for item in metadata.objects
        for key in item.foreign_keys
        if key.physical_id is not None
    )
    index_ids = frozenset(
        index.physical_id
        for item in metadata.objects
        for index in item.indexes
        if index.physical_id is not None
    )

    if not metadata.objects:
        warnings.append(
            "The DDL Repository contains no tables or views; discovery cannot produce "
            "structural proposals."
        )

    return StructuralEvidence(
        root=root,
        manifest=manifest,
        metadata=metadata,
        ddl=ddl,
        warnings=tuple(warnings),
        object_ids=object_ids,
        column_ids=column_ids,
        primary_key_ids=primary_key_ids,
        foreign_key_ids=foreign_key_ids,
        index_ids=index_ids,
        ddl_object_ids=frozenset(ddl),
    )
