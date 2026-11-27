"""Validation of in-memory snapshots and written DDL Repositories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ..metadata.models import (
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from ..metadata.normalizer import (
    foreign_key_physical_id,
    index_physical_id,
    primary_key_physical_id,
    referred_object_physical_id,
)
from .manifest import DdlManifest, ManifestArtifact, ManifestExternalReference
from .naming import (
    DDL_DIRECTORY,
    ISSUES_FILENAME,
    MANIFEST_FILENAME,
    OBJECT_DIRECTORY,
    SCHEMA_DIRECTORY,
    ddl_relative_path,
    resolve_within,
)
from .serialization import sha256_hex
from .snapshot import compute_snapshot_id


@dataclass(frozen=True)
class ReferenceCheck:
    """Result of validating Physical IDs and object references."""

    external: tuple[ManifestExternalReference, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryValidation:
    """Result of validating a written DDL Repository."""

    valid: bool
    errors: tuple[str, ...] = ()
    manifest: DdlManifest | None = None
    status: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


def _expected_object_id(
    identity: DatabaseIdentity, schema: str, object_type: str, name: str
) -> str:
    return make_physical_id(
        identity.platform, identity.database, schema, object_type, name
    )


def _expected_schema_id(identity: DatabaseIdentity, name: str) -> str:
    return make_physical_id(identity.platform, identity.database, "schema", name)


def _check_columns(table: TableMetadata, errors: list[str]) -> set[str]:
    names: set[str] = set()
    ordinals: set[int] = set()
    for column in table.columns:
        if column.name in names:
            errors.append(
                f"Duplicate column {column.name!r} in object {table.physical_id}."
            )
        names.add(column.name)
        if column.ordinal in ordinals:
            errors.append(
                f"Duplicate column ordinal {column.ordinal} in object "
                f"{table.physical_id}."
            )
        ordinals.add(column.ordinal)
        if column.ordinal < 1:
            errors.append(
                f"Column {column.physical_id} has invalid ordinal {column.ordinal}."
            )
        expected = child_id(table.physical_id, "column", column.name)
        if column.physical_id != expected:
            errors.append(
                f"Column {column.name!r} has unstable Physical ID "
                f"{column.physical_id!r}; expected {expected!r}."
            )
    return names


def _check_primary_key(
    table: TableMetadata, column_names: set[str], errors: list[str]
) -> None:
    primary_key = table.primary_key
    if primary_key is None:
        return
    expected_id = primary_key_physical_id(table.physical_id, primary_key.name)
    if primary_key.physical_id != expected_id:
        errors.append(
            f"Primary key on {table.physical_id} has Physical ID "
            f"{primary_key.physical_id!r}; expected {expected_id!r}."
        )
    if not primary_key.columns:
        errors.append(f"Primary key on {table.physical_id} has no columns.")
    for name in primary_key.columns:
        if name not in column_names:
            errors.append(
                f"Primary key on {table.physical_id} references unknown column "
                f"{name!r}."
            )
    expected_column_ids = tuple(
        child_id(table.physical_id, "column", name) for name in primary_key.columns
    )
    if primary_key.column_ids != expected_column_ids:
        errors.append(
            f"Primary key on {table.physical_id} does not persist stable column IDs."
        )


def _check_foreign_keys(
    table: TableMetadata,
    column_names: set[str],
    schema_names: set[str],
    tables: dict[tuple[str, str], TableMetadata],
    errors: list[str],
    external: list[ManifestExternalReference],
) -> None:
    seen_ids: set[str] = set()
    for index, foreign_key in enumerate(table.foreign_keys):
        expected_id = foreign_key_physical_id(
            table.physical_id, foreign_key.name, index
        )
        if foreign_key.physical_id != expected_id:
            errors.append(
                f"Foreign key on {table.physical_id} has Physical ID "
                f"{foreign_key.physical_id!r}; expected {expected_id!r}."
            )
        if foreign_key.physical_id in seen_ids:
            errors.append(
                f"Duplicate foreign key Physical ID {foreign_key.physical_id!r} "
                f"on {table.physical_id}."
            )
        seen_ids.add(str(foreign_key.physical_id))
        if not foreign_key.columns:
            errors.append(f"Foreign key on {table.physical_id} has no columns.")
        for name in foreign_key.columns:
            if name not in column_names:
                errors.append(
                    f"Foreign key on {table.physical_id} references unknown local "
                    f"column {name!r}."
                )
        expected_column_ids = tuple(
            child_id(table.physical_id, "column", name)
            for name in foreign_key.columns
        )
        if foreign_key.column_ids != expected_column_ids:
            errors.append(
                f"Foreign key {foreign_key.physical_id} does not persist stable "
                "local column IDs."
            )
        if not foreign_key.referred_table or not foreign_key.referred_schema:
            errors.append(
                f"Foreign key {foreign_key.physical_id} has an incomplete target."
            )
            continue
        if len(foreign_key.referred_columns) != len(foreign_key.columns):
            errors.append(
                f"Foreign key {foreign_key.physical_id} has mismatched local and "
                "referred column counts."
            )
        expected_target = referred_object_physical_id(
            table.physical_id,
            foreign_key.referred_schema,
            foreign_key.referred_table,
        )
        if foreign_key.referred_object_id != expected_target:
            errors.append(
                f"Foreign key {foreign_key.physical_id} has target ID "
                f"{foreign_key.referred_object_id!r}; expected {expected_target!r}."
            )
        expected_referred_column_ids = (
            tuple(
                child_id(expected_target, "column", name)
                for name in foreign_key.referred_columns
            )
            if expected_target is not None
            else ()
        )
        if foreign_key.referred_column_ids != expected_referred_column_ids:
            errors.append(
                f"Foreign key {foreign_key.physical_id} does not persist stable "
                "referred column IDs."
            )
        if foreign_key.referred_schema not in schema_names:
            if expected_target is not None and foreign_key.physical_id is not None:
                external.append(
                    ManifestExternalReference(
                        source_id=foreign_key.physical_id,
                        target_id=expected_target,
                    )
                )
            continue
        target = tables.get(
            (foreign_key.referred_schema, foreign_key.referred_table)
        )
        if target is None:
            errors.append(
                f"Foreign key {foreign_key.physical_id} references "
                f"{foreign_key.referred_schema}.{foreign_key.referred_table}, "
                "which is missing from the snapshot."
            )
            continue
        target_columns = {column.name for column in target.columns}
        for name in foreign_key.referred_columns:
            if name not in target_columns:
                errors.append(
                    f"Foreign key {foreign_key.physical_id} references unknown "
                    f"column {foreign_key.referred_table}.{name}."
                )


def _check_indexes(
    table: TableMetadata, column_names: set[str], errors: list[str]
) -> None:
    seen_ids: set[str] = set()
    for index in table.indexes:
        expected_id = index_physical_id(table.physical_id, index.name, index.columns)
        if index.physical_id != expected_id:
            errors.append(
                f"Index on {table.physical_id} has Physical ID "
                f"{index.physical_id!r}; expected {expected_id!r}."
            )
        if index.physical_id in seen_ids:
            errors.append(
                f"Duplicate index Physical ID {index.physical_id!r} on "
                f"{table.physical_id}."
            )
        seen_ids.add(str(index.physical_id))
        for name in index.columns:
            if name not in column_names:
                errors.append(
                    f"Index {index.physical_id} references unknown column {name!r}."
                )
        expected_column_ids = tuple(
            child_id(table.physical_id, "column", name) for name in index.columns
        )
        if index.column_ids != expected_column_ids:
            errors.append(
                f"Index {index.physical_id} does not persist stable column IDs."
            )


def validate_metadata(metadata: DatabaseMetadata) -> ReferenceCheck:
    """Validate Physical IDs and references for one complete snapshot."""

    errors: list[str] = []
    external: list[ManifestExternalReference] = []
    identity = metadata.identity
    if not identity.platform:
        errors.append("Database identity has no platform.")
    if not identity.database:
        errors.append("Database identity has no database name.")

    schema_names: set[str] = set()
    schema_ids: set[str] = set()
    for schema in metadata.schemas:
        expected = _expected_schema_id(identity, schema.name)
        if schema.physical_id != expected:
            errors.append(
                f"Schema {schema.name!r} has Physical ID {schema.physical_id!r}; "
                f"expected {expected!r}."
            )
        if schema.name in schema_names:
            errors.append(f"Duplicate schema name {schema.name!r}.")
        schema_names.add(schema.name)
        if schema.physical_id in schema_ids:
            errors.append(f"Duplicate schema Physical ID {schema.physical_id!r}.")
        schema_ids.add(schema.physical_id)

    object_ids: set[str] = set()
    tables: dict[tuple[str, str], TableMetadata] = {
        (table.schema_name, table.name): table
        for table in metadata.objects
        if table.object_type == "table"
    }
    for table in metadata.objects:
        expected = _expected_object_id(
            identity, table.schema_name, table.object_type, table.name
        )
        if table.physical_id != expected:
            errors.append(
                f"Object {table.name!r} has Physical ID {table.physical_id!r}; "
                f"expected {expected!r}."
            )
        if table.physical_id in object_ids:
            errors.append(f"Duplicate object Physical ID {table.physical_id!r}.")
        object_ids.add(table.physical_id)
        if table.schema_name not in schema_names:
            errors.append(
                f"Object {table.physical_id} belongs to schema "
                f"{table.schema_name!r}, which is missing from the snapshot."
            )
        column_names = _check_columns(table, errors)
        _check_primary_key(table, column_names, errors)
        if table.object_type == "table":
            _check_foreign_keys(
                table,
                column_names,
                schema_names,
                tables,
                errors,
                external,
            )
        _check_indexes(table, column_names, errors)

    deduped = sorted(
        {(item.source_id, item.target_id) for item in external},
    )
    return ReferenceCheck(
        external=tuple(
            ManifestExternalReference(source_id=source, target_id=target)
            for source, target in deduped
        ),
        errors=tuple(sorted(set(errors))),
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_counts(
    metadata: DatabaseMetadata,
) -> dict[str, int]:
    return {
        "schemas": len(metadata.schemas),
        "tables": metadata.table_count,
        "views": metadata.view_count,
        "columns": metadata.column_count,
        "primary_keys": metadata.primary_key_count,
        "foreign_keys": metadata.foreign_key_count,
        "indexes": metadata.index_count,
    }


def _validate_ddl(
    manifest: DdlManifest,
    root: Path,
    tables: dict[str, TableMetadata],
    errors: list[str],
) -> set[Path]:
    """Validate DDL entries, files, and status consistency; return referenced paths."""

    referenced: set[Path] = set()
    ddl = manifest.extraction.ddl
    if ddl is None:
        return referenced
    if ddl.status == "not_requested":
        if ddl.objects:
            errors.append(
                "DDL section is not_requested but contains object entries."
            )
        return referenced

    seen: set[str] = set()
    extracted = 0
    for entry in ddl.objects:
        if entry.physical_id in seen:
            errors.append(f"Duplicate DDL entry for {entry.physical_id}.")
            continue
        seen.add(entry.physical_id)
        table = tables.get(entry.physical_id)
        if table is None:
            errors.append(
                f"DDL entry references an object that is not in the repository: "
                f"{entry.physical_id}"
            )
            continue
        if entry.kind != table.object_type:
            errors.append(
                f"DDL entry kind {entry.kind!r} does not match object type "
                f"{table.object_type!r} for {entry.physical_id}."
            )
        if entry.status == "extracted":
            extracted += 1
            if not entry.path or not entry.sha256:
                errors.append(
                    f"Extracted DDL entry has no path or hash: {entry.physical_id}"
                )
                continue
            expected_path = str(ddl_relative_path(entry.physical_id))
            if entry.path != expected_path:
                errors.append(
                    f"DDL artifact path {entry.path!r} does not match the expected "
                    f"name {expected_path!r}."
                )
            try:
                path = resolve_within(root, entry.path)
            except Exception as exc:  # noqa: BLE001 - converted to a validation error
                errors.append(str(exc))
                continue
            referenced.add(path)
            if not path.is_file():
                errors.append(f"DDL artifact is missing: {entry.path}")
            else:
                data = path.read_bytes()
                if sha256_hex(data) != entry.sha256:
                    errors.append(f"DDL artifact hash mismatch: {entry.path}")
                if path.suffix != ".sql":
                    errors.append(f"DDL artifact must use .sql: {entry.path}")
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"DDL artifact is not UTF-8 text: {entry.path}")
                else:
                    if not text.strip():
                        errors.append(f"DDL artifact is empty: {entry.path}")
            if not entry.provenance:
                errors.append(
                    f"Extracted DDL entry has no provenance: {entry.physical_id}"
                )
        else:
            if entry.path is not None or entry.sha256 is not None:
                errors.append(
                    f"Non-extracted DDL entry must not reference a file: "
                    f"{entry.physical_id}"
                )
            if entry.provenance is not None or entry.is_original_text:
                errors.append(
                    f"Non-extracted DDL entry must not claim provenance or original "
                    f"text: {entry.physical_id}"
                )

    missing = sorted(set(tables) - seen)
    if missing:
        errors.append(
            f"DDL manifest is missing {len(missing)} table/view object(s)."
        )
    total = len(tables)
    if ddl.status == "complete" and extracted != total:
        errors.append(
            f"DDL status is complete but {extracted} of {total} objects are extracted."
        )
    if ddl.status == "partial" and not (0 < extracted < total):
        errors.append(
            f"DDL status is partial but {extracted} of {total} objects are extracted."
        )
    if ddl.status in {"failed", "unavailable"} and extracted != 0:
        errors.append(
            f"DDL status is {ddl.status} but {extracted} object(s) were extracted."
        )
    if manifest.extraction.original_ddl.available != (extracted > 0):
        errors.append(
            "extraction.original_ddl.available does not match the DDL artifacts."
        )
    return referenced


def validate_repository(root: Path) -> RepositoryValidation:
    """Validate an existing DDL Repository against its manifest and artifacts."""

    errors: list[str] = []
    try:
        manifest_path = resolve_within(root, MANIFEST_FILENAME)
    except Exception as exc:  # noqa: BLE001 - converted to a validation result
        return RepositoryValidation(valid=False, errors=(str(exc),))
    if not manifest_path.is_file():
        return RepositoryValidation(
            valid=False, errors=(f"Manifest not found: {manifest_path}",)
        )
    try:
        manifest = DdlManifest.model_validate(_read_json(manifest_path))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        return RepositoryValidation(
            valid=False, errors=(f"Manifest is not valid: {exc}",)
        )

    if manifest.manifest_version != "1.0":
        errors.append(
            f"Unsupported manifest version {manifest.manifest_version!r}."
        )
    if manifest.schema_version != "1.0":
        errors.append(f"Unsupported schema version {manifest.schema_version!r}.")

    entries = (*manifest.artifacts.schemas, *manifest.artifacts.objects)
    entries_by_path: dict[str, ManifestArtifact] = {}
    schemas: list[SchemaMetadata] = []
    objects: list[TableMetadata] = []
    referenced_paths: set[Path] = set()

    for entry in entries:
        if entry.path in entries_by_path:
            errors.append(f"Duplicate artifact path in manifest: {entry.path!r}.")
            continue
        entries_by_path[entry.path] = entry
        try:
            path = resolve_within(root, entry.path)
        except Exception as exc:  # noqa: BLE001 - converted to a validation error
            errors.append(str(exc))
            continue
        referenced_paths.add(path)
        if not path.is_file():
            errors.append(f"Artifact is missing: {entry.path}")
            continue
        data = path.read_bytes()
        digest = sha256_hex(data)
        if digest != entry.sha256:
            errors.append(f"Artifact hash mismatch: {entry.path}")
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"Artifact is not valid JSON: {entry.path} ({exc})")
            continue
        try:
            if entry.kind == "schema":
                schema = SchemaMetadata.model_validate(raw)
                if schema.physical_id != entry.physical_id:
                    errors.append(
                        f"Artifact {entry.path} has a different Physical ID."
                    )
                schemas.append(schema)
            else:
                table = TableMetadata.model_validate(raw)
                if table.physical_id != entry.physical_id:
                    errors.append(
                        f"Artifact {entry.path} has a different Physical ID."
                    )
                if table.object_type != entry.kind:
                    errors.append(
                        f"Artifact {entry.path} has object type "
                        f"{table.object_type!r}, manifest says {entry.kind!r}."
                    )
                objects.append(table)
        except ValidationError as exc:
            errors.append(f"Artifact does not match the metadata model: {entry.path} ({exc})")

    try:
        issues_path = resolve_within(root, manifest.extraction.issues.path)
    except Exception as exc:  # noqa: BLE001 - converted to a validation error
        issues_path = None
        errors.append(str(exc))
    if manifest.extraction.issues.path != ISSUES_FILENAME:
        errors.append(
            f"Issues artifact path must be {ISSUES_FILENAME!r}, got "
            f"{manifest.extraction.issues.path!r}."
        )
    issues: list[ExtractionIssue] = []
    if issues_path is not None:
        referenced_paths.add(issues_path)
        if not issues_path.is_file():
            errors.append(f"Issues artifact is missing: {manifest.extraction.issues.path}")
        else:
            data = issues_path.read_bytes()
            if sha256_hex(data) != manifest.extraction.issues.sha256:
                errors.append("Issues artifact hash mismatch.")
            try:
                raw_issues = json.loads(data.decode("utf-8"))
                if not isinstance(raw_issues, list):
                    errors.append("Issues artifact must contain a JSON array.")
                else:
                    issues = [ExtractionIssue.model_validate(item) for item in raw_issues]
            except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
                errors.append(f"Issues artifact is not valid: {exc}")

    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(
            platform=manifest.database.platform, database=manifest.database.name
        ),
        schemas=tuple(schemas),
        objects=tuple(objects),
        issues=tuple(issues),
    )
    check = validate_metadata(metadata)
    errors.extend(check.errors)
    referenced_paths |= _validate_ddl(
        manifest,
        root,
        {item.physical_id: item for item in objects},
        errors,
    )

    expected_counts = _expected_counts(metadata)
    actual_counts = manifest.counts.model_dump()
    for key, expected in expected_counts.items():
        if actual_counts.get(key) != expected:
            errors.append(
                f"Manifest count {key!r} is {actual_counts.get(key)!r}; "
                f"actual content has {expected}."
            )

    schema_names = tuple(sorted(schema.name for schema in metadata.schemas))
    if tuple(manifest.database.schemas) != schema_names:
        errors.append("Manifest schema list does not match repository artifacts.")

    manifest_references = tuple(
        sorted(
            (item.source_id, item.target_id)
            for item in manifest.external_references
        )
    )
    actual_references = tuple(
        (item.source_id, item.target_id) for item in check.external
    )
    if manifest_references != actual_references:
        errors.append("Manifest external references do not match repository content.")

    if manifest.extraction.issue_count != len(metadata.issues):
        errors.append("Manifest issue count does not match issues artifact.")
    if manifest.extraction.issues.count != len(metadata.issues):
        errors.append("Issues artifact count does not match issues artifact content.")
    if manifest.snapshot.status == "complete" and metadata.issues:
        errors.append(
            "Snapshot is marked complete but extraction issues are present."
        )

    expected_snapshot_id = compute_snapshot_id(
        platform=manifest.database.platform,
        database=manifest.database.name,
        schema_version=manifest.schema_version,
        generator_name=manifest.generator.name,
        generator_version=manifest.generator.version,
        included_object_types=manifest.scope.included_object_types,
        excluded_object_types=manifest.scope.excluded_object_types,
        artifacts=entries,
        issues_sha256=manifest.extraction.issues.sha256,
        issues_count=manifest.extraction.issues.count,
        external_references=check.external,
        ddl=manifest.extraction.ddl,
    )
    if manifest.snapshot.id != expected_snapshot_id:
        errors.append("Snapshot identity does not match repository content.")

    for directory in (SCHEMA_DIRECTORY, OBJECT_DIRECTORY, DDL_DIRECTORY):
        directory_path = root.resolve() / directory
        if not directory_path.exists():
            continue
        if not directory_path.is_dir():
            errors.append(f"Repository path is not a directory: {directory}")
            continue
        for item in sorted(directory_path.iterdir()):
            if item not in referenced_paths:
                errors.append(f"Unreferenced artifact in repository: {directory}/{item.name}")

    return RepositoryValidation(
        valid=not errors,
        errors=tuple(errors),
        manifest=manifest,
        status=manifest.snapshot.status,
        counts=expected_counts,
    )
