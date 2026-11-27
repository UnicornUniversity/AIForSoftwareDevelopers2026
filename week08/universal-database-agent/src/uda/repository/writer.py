"""DDL Repository writer.

The writer persists one complete normalized snapshot as deterministic per-object JSON
artifacts, optional per-object SQL DDL artifacts, and a root ``manifest.json``. It
validates the snapshot in memory before any file is written, writes only changed files,
removes stale artifacts inside its managed directories, and validates the repository again
after writing.

DDL artifacts are produced by the approved SMO extraction path. The writer never
reconstructs SQL from normalized metadata and never labels a synthesized statement as an
original definition.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Literal

from ..adapters.ddl import DdlExtraction, DdlObject, normalize_ddl
from ..adapters.smo import SmoStatus, detect_smo_availability
from ..errors import RepositoryValidationError, RepositoryWriteError
from ..metadata.identity import ensure_physical_ids
from ..metadata.models import DatabaseMetadata, SchemaMetadata, TableMetadata
from .manifest import (
    DDL_SCHEMA_VERSION,
    GENERATOR_NAME,
    MANIFEST_VERSION,
    DdlManifest,
    ManifestArtifact,
    ManifestArtifacts,
    ManifestCounts,
    ManifestDatabase,
    ManifestDdl,
    ManifestDdlObject,
    ManifestExtraction,
    ManifestGenerator,
    ManifestGit,
    ManifestIssuesArtifact,
    ManifestOriginalDdl,
    ManifestScope,
    ManifestSmo,
    ManifestSnapshot,
)
from .naming import (
    DDL_DIRECTORY,
    ISSUES_FILENAME,
    MANIFEST_FILENAME,
    OBJECT_DIRECTORY,
    SCHEMA_DIRECTORY,
    artifact_relative_path,
    ddl_relative_path,
    resolve_within,
)
from .serialization import canonical_bytes, sha256_hex
from .snapshot import compute_snapshot_id
from .validation import validate_metadata, validate_repository

_FALLBACK_GENERATOR_VERSION = "0.1.0"


@dataclass(frozen=True)
class GitState:
    available: bool
    commit: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class RepositoryChange:
    added: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.removed)


@dataclass(frozen=True)
class WriteResult:
    root: Path
    manifest_path: Path
    snapshot_id: str
    run_id: str
    status: str
    issue_count: int
    counts: dict[str, int]
    changes: RepositoryChange
    ddl_status: str = "not_requested"
    ddl_extracted: int = 0
    ddl_object_count: int = 0


@dataclass(frozen=True)
class _PreparedDdl:
    manifest: ManifestDdl
    files: dict[str, tuple[ManifestDdlObject, bytes]]
    ids: dict[str, str]
    hashes: dict[str, str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_run_id() -> str:
    return uuid.uuid4().hex


def default_generator_version() -> str:
    try:
        return package_version("uda")
    except PackageNotFoundError:
        return _FALLBACK_GENERATOR_VERSION


def detect_git_commit(project_root: Path, *, timeout: float = 5.0) -> GitState:
    """Read the current Git commit without a shell; report unavailability explicitly."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitState(
            available=False,
            detail=f"Git commit unavailable ({type(exc).__name__}).",
        )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not commit:
        return GitState(available=False, detail="Git commit unavailable.")
    if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        return GitState(
            available=False,
            detail="Git returned an unrecognized commit identifier.",
        )
    return GitState(available=True, commit=commit)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _counts(metadata: DatabaseMetadata) -> dict[str, int]:
    return {
        "schemas": len(metadata.schemas),
        "tables": metadata.table_count,
        "views": metadata.view_count,
        "columns": metadata.column_count,
        "primary_keys": metadata.primary_key_count,
        "foreign_keys": metadata.foreign_key_count,
        "indexes": metadata.index_count,
    }


def prepare_metadata(metadata: DatabaseMetadata) -> DatabaseMetadata:
    """Complete derived IDs and put the snapshot in deterministic order."""

    complete = ensure_physical_ids(metadata)
    schemas = tuple(
        sorted(complete.schemas, key=lambda item: (item.name, item.physical_id))
    )
    objects: list[TableMetadata] = []
    for table in sorted(
        complete.objects,
        key=lambda item: (
            item.schema_name,
            item.object_type,
            item.name,
            item.physical_id,
        ),
    ):
        columns = tuple(
            sorted(table.columns, key=lambda item: (item.ordinal, item.name))
        )
        objects.append(table.model_copy(update={"columns": columns}))
    issues = tuple(
        sorted(
            complete.issues,
            key=lambda item: (item.kind, item.object_id or "", item.detail),
        )
    )
    return complete.model_copy(
        update={"schemas": schemas, "objects": tuple(objects), "issues": issues}
    )


def _artifact_bytes(artifact: SchemaMetadata | TableMetadata) -> bytes:
    return canonical_bytes(artifact.model_dump(mode="json", by_alias=True))


def _prepare_ddl(
    metadata: DatabaseMetadata, extraction: DdlExtraction | None
) -> _PreparedDdl:
    """Turn an extraction result into manifest entries and deterministic SQL files."""

    if extraction is None:
        return _PreparedDdl(
            manifest=ManifestDdl(
                status="not_requested",
                detail="DDL extraction was not requested for this snapshot.",
            ),
            files={},
            ids={},
            hashes={},
        )

    object_map = {item.physical_id: item for item in metadata.objects}
    entries: dict[str, ManifestDdlObject] = {}
    files: dict[str, tuple[ManifestDdlObject, bytes]] = {}
    ids: dict[str, str] = {}
    hashes: dict[str, str] = {}

    for item in sorted(extraction.objects, key=lambda row: row.physical_id):
        table = object_map.get(item.physical_id)
        if table is None:
            raise RepositoryValidationError(
                "DDL extraction returned an object that is not in the snapshot: "
                f"{item.physical_id}"
            )
        if item.kind != table.object_type:
            raise RepositoryValidationError(
                f"DDL result kind {item.kind!r} does not match "
                f"{table.object_type!r} for {item.physical_id}."
            )
        if item.physical_id in entries:
            raise RepositoryValidationError(
                f"Duplicate DDL result for {item.physical_id}."
            )
        entries[item.physical_id] = _manifest_ddl_object(item, files, ids, hashes)

    missing_count = 0
    for table in metadata.objects:
        if table.physical_id in entries:
            continue
        missing_count += 1
        entries[table.physical_id] = ManifestDdlObject(
            physical_id=table.physical_id,
            kind=table.object_type,
            status="unavailable",
            error="DDL provider returned no result for this object.",
        )

    ordered = tuple(sorted(entries.values(), key=lambda item: item.physical_id))
    extracted = sum(1 for item in ordered if item.status == "extracted")
    status: Literal["complete", "partial", "failed", "unavailable", "not_requested"]
    if not ordered:
        status = "complete"
    elif extracted == len(ordered):
        status = "complete"
    elif extracted:
        status = "partial"
    elif extraction.status in {"unavailable"}:
        status = "unavailable"
    else:
        status = "failed"

    detail = extraction.detail
    if missing_count:
        detail += (
            f" {missing_count} object(s) had no DDL result and were recorded as "
            "unavailable."
        )
    return _PreparedDdl(
        manifest=ManifestDdl(
            status=status,
            mechanism=extraction.mechanism,
            version=extraction.version,
            detail=detail,
            objects=ordered,
        ),
        files=files,
        ids=ids,
        hashes=hashes,
    )


def _manifest_ddl_object(
    item: DdlObject,
    files: dict[str, tuple[ManifestDdlObject, bytes]],
    ids: dict[str, str],
    hashes: dict[str, str],
) -> ManifestDdlObject:
    if item.status != "extracted":
        return ManifestDdlObject(
            physical_id=item.physical_id,
            kind=item.kind,
            status=item.status,
            error=item.error,
        )
    normal = normalize_ddl(item.ddl or "")
    if not normal:
        return ManifestDdlObject(
            physical_id=item.physical_id,
            kind=item.kind,
            status="failed",
            error="DDL provider returned an empty definition.",
        )
    content = normal.encode("utf-8")
    relative = str(ddl_relative_path(item.physical_id))
    digest = sha256_hex(content)
    entry = ManifestDdlObject(
        physical_id=item.physical_id,
        kind=item.kind,
        status="extracted",
        provenance=item.provenance,
        is_original_text=item.is_original_text,
        path=relative,
        sha256=digest,
    )
    files[relative] = (entry, content)
    ids[relative] = item.physical_id
    hashes[relative] = digest
    return entry


def _original_ddl_state(prepared: ManifestDdl) -> ManifestOriginalDdl:
    extracted = sum(1 for item in prepared.objects if item.status == "extracted")
    total = len(prepared.objects)
    if prepared.status == "complete":
        reason = (
            f"All {total} table/view definitions have SQL artifacts. Views use the "
            "stored server module definition; table definitions are generated by SMO "
            "from live metadata. Neither is a byte-for-byte historical source file."
        )
        return ManifestOriginalDdl(available=True, reason=reason)
    if prepared.status == "partial":
        reason = (
            f"{extracted} of {total} table/view definitions have SQL artifacts; see "
            "extraction.ddl for per-object status."
        )
        return ManifestOriginalDdl(available=True, reason=reason)
    reason = (
        "No per-object SQL DDL artifacts were produced: "
        + (prepared.detail or f"DDL status {prepared.status}.")
    )
    return ManifestOriginalDdl(available=False, reason=reason)


def _read_previous_snapshot(root: Path) -> dict[str, dict[str, str]]:
    """Map previous physical ID to {path: sha256} for JSON and DDL artifacts."""

    previous: dict[str, dict[str, str]] = {}
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = DdlManifest.model_validate(raw)
            for entry in (*manifest.artifacts.schemas, *manifest.artifacts.objects):
                previous.setdefault(entry.physical_id, {})[entry.path] = entry.sha256
            ddl = manifest.extraction.ddl
            if ddl is not None:
                for ddl_entry in ddl.objects:
                    if ddl_entry.path is not None and ddl_entry.sha256 is not None:
                        previous.setdefault(ddl_entry.physical_id, {})[
                            ddl_entry.path
                        ] = ddl_entry.sha256
            return previous
        except (OSError, ValueError, TypeError):
            previous = {}
    for directory, suffix in (
        (SCHEMA_DIRECTORY, ".json"),
        (OBJECT_DIRECTORY, ".json"),
        (DDL_DIRECTORY, ".sql"),
    ):
        directory_path = root / directory
        if not directory_path.is_dir():
            continue
        for item in sorted(directory_path.iterdir()):
            if item.is_file() and item.suffix == suffix:
                try:
                    previous[f"{directory}/{item.name}"] = {
                        f"{directory}/{item.name}": sha256_hex(item.read_bytes())
                    }
                except OSError:
                    continue
    return previous


class DdlRepositoryWriter:
    """Write and validate a DDL Repository snapshot."""

    def __init__(
        self,
        root: Path,
        *,
        project_root: Path | None = None,
        generator_name: str = GENERATOR_NAME,
        generator_version: str | None = None,
        schema_version: str = DDL_SCHEMA_VERSION,
        clock: Callable[[], datetime] = utc_now,
        run_id_factory: Callable[[], str] = new_run_id,
        git_provider: Callable[[], GitState] | None = None,
        smo_provider: Callable[[], SmoStatus] = detect_smo_availability,
    ) -> None:
        self.root = root
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.generator_name = generator_name
        self.generator_version = generator_version or default_generator_version()
        self.schema_version = schema_version
        self._clock = clock
        self._run_id_factory = run_id_factory
        self._git_provider = git_provider or (
            lambda: detect_git_commit(self.project_root)
        )
        self._smo_provider = smo_provider

    def write(
        self,
        metadata: DatabaseMetadata,
        *,
        source: str = "unknown",
        smo: SmoStatus | None = None,
        ddl: DdlExtraction | None = None,
    ) -> WriteResult:
        started = self._clock()
        prepared = prepare_metadata(metadata)
        check = validate_metadata(prepared)
        if check.errors:
            raise RepositoryValidationError(
                "Snapshot is invalid and was not written: "
                + "; ".join(check.errors)
            )
        prepared_ddl = _prepare_ddl(prepared, ddl)

        planned_json: dict[str, tuple[ManifestArtifact, bytes]] = {}
        planned_files: dict[str, bytes] = {}
        planned_ids: dict[str, str] = {}
        planned_hashes: dict[str, str] = {}

        def plan_json(
            artifact: SchemaMetadata | TableMetadata,
            kind: Literal["schema", "table", "view"],
            physical_id: str,
        ) -> None:
            relative = artifact_relative_path(kind, physical_id)
            content = _artifact_bytes(artifact)
            digest = sha256_hex(content)
            path = str(relative)
            planned_json[path] = (
                ManifestArtifact(
                    physical_id=physical_id,
                    kind=kind,
                    path=path,
                    sha256=digest,
                ),
                content,
            )
            planned_files[path] = content
            planned_ids[path] = physical_id
            planned_hashes[path] = digest

        for schema in prepared.schemas:
            plan_json(schema, "schema", schema.physical_id)
        for table in prepared.objects:
            plan_json(table, table.object_type, table.physical_id)

        for path, (ddl_entry, content) in prepared_ddl.files.items():
            planned_files[path] = content
            planned_ids[path] = ddl_entry.physical_id
            planned_hashes[path] = ddl_entry.sha256 or sha256_hex(content)

        issues_content = canonical_bytes(
            [
                issue.model_dump(mode="json", by_alias=True)
                for issue in prepared.issues
            ]
        )
        issues_sha = sha256_hex(issues_content)
        entries = tuple(
            sorted(
                (item[0] for item in planned_json.values()),
                key=lambda item: (item.kind, item.path),
            )
        )
        schema_entries = tuple(item for item in entries if item.kind == "schema")
        object_entries = tuple(item for item in entries if item.kind != "schema")

        changes = self._detect_changes(planned_ids, planned_hashes)
        snapshot_id = compute_snapshot_id(
            platform=prepared.identity.platform,
            database=prepared.identity.database,
            schema_version=self.schema_version,
            generator_name=self.generator_name,
            generator_version=self.generator_version,
            included_object_types=ManifestScope().included_object_types,
            excluded_object_types=ManifestScope().excluded_object_types,
            artifacts=entries,
            issues_sha256=issues_sha,
            issues_count=len(prepared.issues),
            external_references=check.external,
            ddl=prepared_ddl.manifest,
        )
        run_id = self._run_id_factory()
        status: Literal["complete", "partial"] = (
            "partial" if prepared.issues else "complete"
        )
        smo_status = smo if smo is not None else self._smo_provider()
        git_state = self._git_provider()

        try:
            self._ensure_root()
            self._write_planned(planned_files)
            self._write_if_changed(
                resolve_within(self.root, ISSUES_FILENAME), issues_content
            )
            self._remove_stale(planned_files)
            completed = self._clock()
            manifest = DdlManifest(
                manifest_version=MANIFEST_VERSION,
                repository="ddl",
                snapshot=ManifestSnapshot(
                    id=snapshot_id,
                    run_id=run_id,
                    created_at=_format_timestamp(started),
                    status=status,
                ),
                generator=ManifestGenerator(
                    name=self.generator_name, version=self.generator_version
                ),
                schema_version=self.schema_version,
                git=ManifestGit(
                    available=git_state.available,
                    commit=git_state.commit,
                    detail=git_state.detail,
                ),
                database=ManifestDatabase(
                    platform=prepared.identity.platform,
                    name=prepared.identity.database,
                    schemas=tuple(sorted(item.name for item in prepared.schemas)),
                ),
                extraction=ManifestExtraction(
                    source=source,
                    started_at=_format_timestamp(started),
                    completed_at=_format_timestamp(completed),
                    issue_count=len(prepared.issues),
                    issues=ManifestIssuesArtifact(
                        path=ISSUES_FILENAME,
                        sha256=issues_sha,
                        count=len(prepared.issues),
                    ),
                    smo=ManifestSmo(
                        available=smo_status.available,
                        version=smo_status.version,
                        mechanism=smo_status.mechanism,
                        detail=smo_status.detail,
                    ),
                    original_ddl=_original_ddl_state(prepared_ddl.manifest),
                    ddl=prepared_ddl.manifest,
                ),
                counts=ManifestCounts(**_counts(prepared)),
                artifacts=ManifestArtifacts(
                    schemas=schema_entries, objects=object_entries
                ),
                external_references=check.external,
            )
            self._write_if_changed(
                resolve_within(self.root, MANIFEST_FILENAME),
                canonical_bytes(manifest.model_dump(mode="json", by_alias=True)),
            )
        except RepositoryWriteError:
            raise
        except OSError as exc:
            raise RepositoryWriteError(
                f"Could not write the DDL Repository ({type(exc).__name__})."
            ) from exc

        validation = validate_repository(self.root)
        if not validation.valid:
            raise RepositoryWriteError(
                "The written DDL Repository failed validation: "
                + "; ".join(validation.errors)
            )
        ddl_extracted = sum(
            1
            for item in prepared_ddl.manifest.objects
            if item.status == "extracted"
        )
        return WriteResult(
            root=self.root,
            manifest_path=self.root / MANIFEST_FILENAME,
            snapshot_id=snapshot_id,
            run_id=run_id,
            status=status,
            issue_count=len(prepared.issues),
            counts=_counts(prepared),
            changes=changes,
            ddl_status=prepared_ddl.manifest.status,
            ddl_extracted=ddl_extracted,
            ddl_object_count=len(prepared_ddl.manifest.objects),
        )

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RepositoryWriteError(
                f"Could not create the DDL Repository root ({type(exc).__name__})."
            ) from exc
        if not self.root.is_dir():
            raise RepositoryWriteError(
                "The DDL Repository root is not a directory."
            )

    def _write_planned(self, planned: dict[str, bytes]) -> None:
        for relative in sorted(planned):
            self._write_if_changed(
                resolve_within(self.root, relative), planned[relative]
            )

    def _write_if_changed(self, path: Path, content: bytes) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise RepositoryWriteError(
                "Refusing to write outside the DDL Repository root."
            ) from exc
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.read_bytes() == content:
                return False
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                os.replace(temporary, path)
            except OSError:
                temporary.unlink(missing_ok=True)
                raise
            return True
        except OSError as exc:
            raise RepositoryWriteError(
                f"Could not write repository artifact {path.name!r} "
                f"({type(exc).__name__})."
            ) from exc

    def _remove_stale(self, planned: dict[str, bytes]) -> None:
        planned_paths = set(planned)
        for directory, suffix in (
            (SCHEMA_DIRECTORY, ".json"),
            (OBJECT_DIRECTORY, ".json"),
            (DDL_DIRECTORY, ".sql"),
        ):
            directory_path = resolve_within(self.root, directory)
            if not directory_path.is_dir():
                continue
            for item in sorted(directory_path.iterdir()):
                relative = f"{directory}/{item.name}"
                if (
                    item.is_file()
                    and item.suffix == suffix
                    and relative not in planned_paths
                ):
                    try:
                        item.unlink()
                    except OSError as exc:
                        raise RepositoryWriteError(
                            f"Could not remove stale artifact {relative!r} "
                            f"({type(exc).__name__})."
                        ) from exc

    def _detect_changes(
        self, planned_ids: dict[str, str], planned_hashes: dict[str, str]
    ) -> RepositoryChange:
        previous = _read_previous_snapshot(self.root)
        current: dict[str, dict[str, str]] = {}
        for path, physical_id in planned_ids.items():
            current.setdefault(physical_id, {})[path] = planned_hashes.get(path, "")
        added = tuple(sorted(set(current) - set(previous)))
        removed = tuple(sorted(set(previous) - set(current)))
        changed = tuple(
            sorted(
                physical_id
                for physical_id in set(current) & set(previous)
                if current[physical_id] != previous[physical_id]
            )
        )
        return RepositoryChange(added=added, changed=changed, removed=removed)
