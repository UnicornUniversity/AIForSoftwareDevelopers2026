"""Proposal Repository: deterministic YAML records and a root manifest.

Phase 3 writes only under ``data/knowledge/proposals/`` (the default) and refuses to write
under the DDL or approved Semantic Repository. Existing proposal files are never overwritten:
an identical record is left unchanged, and a differing record is reported as a conflict.

The writer validates the complete merged repository before writing anything, writes records
first and the manifest last, and re-validates the result.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from ..errors import (
    ProposalRepositoryValidationError,
    ProposalRepositoryWriteError,
    ProposalValidationError,
)
from ..repository.naming import resolve_within
from ..repository.serialization import canonical_bytes, sha256_hex
from ..repository.writer import default_generator_version
from .evidence import StructuralEvidence, load_ddl_repository
from .models import (
    ConceptProposal,
    GenerationMetadata,
    MappingProposal,
    ProposalBatch,
    ProposalModel,
    ProposalRecord,
    RelationshipProposal,
)
from .validation import (
    validate_proposal_batch,
    validate_record_evidence,
)

PROPOSAL_MANIFEST_VERSION = "1.0"
PROPOSALS_REPOSITORY = "proposals"
CONCEPTS_DIRECTORY = "concepts"
MAPPINGS_DIRECTORY = "mappings"
RELATIONSHIPS_DIRECTORY = "relationships"
MANIFEST_FILENAME = "manifest.json"
PROPOSAL_SUFFIX = ".yaml"

_DIRECTORIES = (
    ("concept", CONCEPTS_DIRECTORY, ConceptProposal),
    ("mapping", MAPPINGS_DIRECTORY, MappingProposal),
    ("relationship", RELATIONSHIPS_DIRECTORY, RelationshipProposal),
)
_DIRECTORY_BY_KIND = {kind: directory for kind, directory, _model in _DIRECTORIES}
_MODEL_BY_KIND = {kind: model for kind, _directory, model in _DIRECTORIES}


class ProposalGenerator(ProposalModel):
    name: str = "uda"
    version: str


class ProposalRun(ProposalModel):
    run_id: str
    generated_at: str
    ddl_repository: str
    snapshot_id: str
    prompt_version: str
    prompt_sha256: str
    provider: str
    model: str
    temperature: float
    max_tokens: int
    status: Literal["completed", "conflicts", "no_proposals"]
    warnings: tuple[str, ...] = ()


class ProposalManifestArtifact(ProposalModel):
    proposal_id: str
    kind: Literal["concept", "mapping", "relationship"]
    path: str
    sha256: str


class ProposalManifestCounts(ProposalModel):
    concepts: int = 0
    mappings: int = 0
    relationships: int = 0


class ProposalManifestArtifacts(ProposalModel):
    concepts: tuple[ProposalManifestArtifact, ...] = ()
    mappings: tuple[ProposalManifestArtifact, ...] = ()
    relationships: tuple[ProposalManifestArtifact, ...] = ()


class ProposalManifest(ProposalModel):
    manifest_version: str = PROPOSAL_MANIFEST_VERSION
    repository: Literal["proposals"] = "proposals"
    schema_version: str
    generator: ProposalGenerator
    last_run: ProposalRun
    counts: ProposalManifestCounts
    artifacts: ProposalManifestArtifacts


@dataclass(frozen=True)
class ProposalRepositoryValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    manifest: ProposalManifest | None = None
    empty: bool = False


@dataclass(frozen=True)
class ProposalWriteResult:
    root: Path
    manifest_path: Path
    written: tuple[str, ...]
    unchanged: tuple[str, ...]
    conflicts: tuple[str, ...]
    counts: dict[str, int]
    status: Literal["completed", "conflicts", "no_proposals"]


@dataclass(frozen=True)
class _StoredRecord:
    record: ProposalRecord
    path: Path
    relative_path: str
    content: bytes


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader, node: Any, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ProposalRepositoryValidationError(
                f"Duplicate YAML key in proposal record: {key!r}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _yaml_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        text = yaml.safe_dump(
            dict(payload),
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=100,
        )
    except yaml.YAMLError as exc:  # pragma: no cover - defensive representer guard
        raise ProposalRepositoryWriteError(
            f"Could not serialize a proposal record ({type(exc).__name__})."
        ) from exc
    return text.encode("utf-8")


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ProposalRepositoryValidationError(
            f"Could not read proposal {path.name!r} ({type(exc).__name__})."
        ) from exc
    if not isinstance(raw, dict):
        raise ProposalRepositoryValidationError(
            f"Proposal {path.name!r} must contain a mapping."
        )
    return raw


def _record_kind(record: ProposalRecord) -> Literal["concept", "mapping", "relationship"]:
    return record.kind


def _expected_identity(record: ProposalRecord) -> str:
    if isinstance(record, ConceptProposal):
        return record.semantic_id
    if isinstance(record, MappingProposal):
        return record.mapping_id
    return record.relationship_id


def _record_path(root: Path, record: ProposalRecord) -> tuple[Path, str]:
    relative = f"{_DIRECTORY_BY_KIND[record.kind]}/{record.proposal_id}{PROPOSAL_SUFFIX}"
    try:
        return resolve_within(root, relative), relative
    except Exception as exc:  # noqa: BLE001 - converted to a repository error
        raise ProposalRepositoryWriteError(
            f"Refusing an unsafe proposal path ({type(exc).__name__})."
        ) from exc


def _scan_records(
    root: Path,
) -> tuple[dict[str, _StoredRecord], tuple[str, ...]]:
    records: dict[str, _StoredRecord] = {}
    errors: list[str] = []
    if not root.exists():
        return records, ()
    if not root.is_dir():
        return records, ("Proposal repository root is not a directory.",)
    for kind, directory, model in _DIRECTORIES:
        try:
            directory_path = resolve_within(root, directory)
        except Exception as exc:  # noqa: BLE001 - converted to a validation error
            errors.append(str(exc))
            continue
        if not directory_path.exists():
            continue
        if not directory_path.is_dir():
            errors.append(f"Proposal path is not a directory: {directory}.")
            continue
        for item in sorted(directory_path.iterdir()):
            relative = f"{directory}/{item.name}"
            if not item.is_file():
                errors.append(f"Unexpected entry in proposal repository: {relative}.")
                continue
            if item.suffix != PROPOSAL_SUFFIX:
                errors.append(f"Unexpected file in proposal repository: {relative}.")
                continue
            try:
                raw = _load_yaml_dict(item)
            except ProposalRepositoryValidationError as exc:
                errors.append(str(exc))
                continue
            for required in ("schema_version", "kind", "proposal_id", "status"):
                if required not in raw:
                    errors.append(f"{relative}: missing required field {required!r}.")
            try:
                record = model.model_validate(raw)
            except ValidationError as exc:
                details = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: "
                    f"{error['msg']}"
                    for error in exc.errors()
                )
                errors.append(f"{relative}: invalid proposal record ({details}).")
                continue
            if record.kind != kind:
                errors.append(f"{relative}: record kind does not match its directory.")
            if record.status != "proposed":
                errors.append(f"{relative}: status must be 'proposed'.")
            if raw.get("status") != "proposed":
                errors.append(f"{relative}: status must be explicitly 'proposed'.")
            if record.generation is None:
                errors.append(f"{relative}: missing generation metadata.")
            if record.proposal_id != item.stem:
                errors.append(
                    f"{relative}: proposal_id must match the file name."
                )
            expected = _expected_identity(record)
            if record.proposal_id != expected:
                errors.append(
                    f"{relative}: proposal_id must match its stable identity {expected!r}."
                )
            if record.proposal_id in records:
                errors.append(
                    f"{relative}: duplicate proposal identity {record.proposal_id!r}."
                )
                continue
            try:
                content = item.read_bytes()
            except OSError as exc:
                errors.append(
                    f"{relative}: could not read proposal ({type(exc).__name__})."
                )
                continue
            records[record.proposal_id] = _StoredRecord(
                record=record,
                path=item,
                relative_path=relative,
                content=content,
            )
    return records, tuple(errors)


def _batch_from_records(records: Mapping[str, _StoredRecord]) -> ProposalBatch:
    concepts = tuple(
        sorted(
            (
                stored.record
                for stored in records.values()
                if isinstance(stored.record, ConceptProposal)
            ),
            key=lambda item: item.semantic_id,
        )
    )
    mappings = tuple(
        sorted(
            (
                stored.record
                for stored in records.values()
                if isinstance(stored.record, MappingProposal)
            ),
            key=lambda item: item.mapping_id,
        )
    )
    relationships = tuple(
        sorted(
            (
                stored.record
                for stored in records.values()
                if isinstance(stored.record, RelationshipProposal)
            ),
            key=lambda item: item.relationship_id,
        )
    )
    return ProposalBatch(
        concepts=concepts,
        mappings=mappings,
        relationships=relationships,
    )


def _counts(records: Mapping[str, _StoredRecord]) -> dict[str, int]:
    counts = {"concepts": 0, "mappings": 0, "relationships": 0}
    for stored in records.values():
        counts[f"{stored.record.kind}s"] += 1
    return counts


def _manifest_artifacts(
    records: Mapping[str, _StoredRecord],
) -> ProposalManifestArtifacts:
    concepts: list[ProposalManifestArtifact] = []
    mappings: list[ProposalManifestArtifact] = []
    relationships: list[ProposalManifestArtifact] = []
    for stored in records.values():
        artifact = ProposalManifestArtifact(
            proposal_id=stored.record.proposal_id,
            kind=stored.record.kind,
            path=stored.relative_path,
            sha256=sha256_hex(stored.content),
        )
        if isinstance(stored.record, ConceptProposal):
            concepts.append(artifact)
        elif isinstance(stored.record, MappingProposal):
            mappings.append(artifact)
        else:
            relationships.append(artifact)
    return ProposalManifestArtifacts(
        concepts=tuple(sorted(concepts, key=lambda item: item.path)),
        mappings=tuple(sorted(mappings, key=lambda item: item.path)),
        relationships=tuple(sorted(relationships, key=lambda item: item.path)),
    )


def _artifact_map(
    artifacts: ProposalManifestArtifacts,
) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for artifact in (
        *artifacts.concepts,
        *artifacts.mappings,
        *artifacts.relationships,
    ):
        result[(artifact.kind, artifact.proposal_id)] = (
            artifact.path,
            artifact.sha256,
        )
    return result


def _expected_artifact_map(
    records: Mapping[str, _StoredRecord],
) -> dict[tuple[str, str], tuple[str, str]]:
    return {
        (stored.record.kind, stored.record.proposal_id): (
            stored.relative_path,
            sha256_hex(stored.content),
        )
        for stored in records.values()
    }


def _read_manifest(root: Path) -> ProposalManifest | None:
    try:
        manifest_path = resolve_within(root, MANIFEST_FILENAME)
    except Exception as exc:  # noqa: BLE001 - converted to a validation error
        raise ProposalRepositoryValidationError(str(exc)) from exc
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProposalRepositoryValidationError(
            f"Proposal manifest is not valid JSON ({type(exc).__name__})."
        ) from exc
    try:
        manifest = ProposalManifest.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: "
            f"{error['msg']}"
            for error in exc.errors()
        )
        raise ProposalRepositoryValidationError(
            f"Proposal manifest is invalid ({details})."
        ) from exc
    if manifest.manifest_version != PROPOSAL_MANIFEST_VERSION:
        raise ProposalRepositoryValidationError(
            f"Unsupported proposal manifest version {manifest.manifest_version!r}."
        )
    if manifest.repository != PROPOSALS_REPOSITORY:
        raise ProposalRepositoryValidationError(
            f"Unexpected proposal manifest repository {manifest.repository!r}."
        )
    if manifest.schema_version != "1.0":
        raise ProposalRepositoryValidationError(
            f"Unsupported proposal schema version {manifest.schema_version!r}."
        )
    return manifest


def validate_proposal_repository(
    root: Path, *, ddl_repository: Path | None = None
) -> ProposalRepositoryValidation:
    """Validate a proposal repository, optionally against its DDL evidence."""

    if not root.exists():
        return ProposalRepositoryValidation(valid=True, empty=True)
    if not root.is_dir():
        return ProposalRepositoryValidation(
            valid=False, errors=("Proposal repository root is not a directory.",)
        )
    records, scan_errors = _scan_records(root)
    errors: list[str] = list(scan_errors)
    manifest: ProposalManifest | None = None
    try:
        manifest = _read_manifest(root)
    except ProposalRepositoryValidationError as exc:
        errors.append(str(exc))
    if manifest is None:
        if records:
            errors.append("Proposal repository manifest is missing.")
    else:
        expected_counts = ProposalManifestCounts(**_counts(records))
        if manifest.counts != expected_counts:
            errors.append(
                "Manifest counts do not match the proposal records currently on disk."
            )
        expected_map = _expected_artifact_map(records)
        actual_map = _artifact_map(manifest.artifacts)
        if expected_map != actual_map:
            errors.append(
                "Manifest artifacts do not match the proposal records or their hashes."
            )
        all_artifacts = (
            *manifest.artifacts.concepts,
            *manifest.artifacts.mappings,
            *manifest.artifacts.relationships,
        )
        artifact_keys = [
            (artifact.kind, artifact.proposal_id) for artifact in all_artifacts
        ]
        if len(artifact_keys) != len(set(artifact_keys)):
            errors.append("Manifest contains duplicate artifact entries.")
        artifact_paths = [artifact.path for artifact in all_artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            errors.append("Manifest contains duplicate artifact paths.")
        for artifact in all_artifacts:
            try:
                path = resolve_within(root, artifact.path)
            except Exception as exc:  # noqa: BLE001 - converted to a validation error
                errors.append(str(exc))
                continue
            if not path.is_file():
                errors.append(f"Manifest artifact is missing: {artifact.path}.")
                continue
            try:
                data = path.read_bytes()
            except OSError as exc:
                errors.append(
                    f"Manifest artifact could not be read: {artifact.path} "
                    f"({type(exc).__name__})."
                )
                continue
            if sha256_hex(data) != artifact.sha256:
                errors.append(f"Manifest artifact hash mismatch: {artifact.path}.")

    batch = _batch_from_records(records)
    errors.extend(validate_proposal_batch(batch))
    if ddl_repository is not None:
        try:
            evidence: StructuralEvidence = load_ddl_repository(ddl_repository)
        except Exception as exc:  # noqa: BLE001 - converted to a validation error
            errors.append(f"Could not load DDL evidence: {exc}")
        else:
            errors.extend(
                validate_record_evidence(
                    (stored.record for stored in records.values()), evidence
                )
            )

    return ProposalRepositoryValidation(
        valid=not errors,
        errors=tuple(errors),
        counts=_counts(records),
        manifest=manifest,
        empty=not records,
    )


class ProposalRepositoryWriter:
    """Validate and persist proposal records without overwriting existing files."""

    def __init__(
        self,
        root: Path,
        *,
        project_root: Path | None = None,
        generator_name: str = "uda",
        generator_version: str | None = None,
        clock: Any = None,
        run_id_factory: Any = None,
    ) -> None:
        self.root = root
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.generator_name = generator_name
        self.generator_version = generator_version or default_generator_version()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)

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
            raise ProposalRepositoryWriteError(
                "Discovery proposals must be written under "
                "data/knowledge/proposals/."
            ) from exc
        if not relative.parts or relative.parts[0] != "proposals":
            raise ProposalRepositoryWriteError(
                "Discovery proposals must be written under "
                "data/knowledge/proposals/; refusing to write to "
                f"{self.root}."
            )

    @staticmethod
    def _write_new(path: Path, content: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ProposalRepositoryWriteError(
                    f"Refusing to overwrite existing proposal {path.name!r}."
                ) from exc
            finally:
                temporary.unlink(missing_ok=True)
        except ProposalRepositoryWriteError:
            raise
        except OSError as exc:
            raise ProposalRepositoryWriteError(
                f"Could not write proposal {path.name!r} ({type(exc).__name__})."
            ) from exc

    @staticmethod
    def _write_if_changed(path: Path, content: bytes) -> bool:
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
            raise ProposalRepositoryWriteError(
                f"Could not write proposal repository manifest "
                f"({type(exc).__name__})."
            ) from exc

    def write(
        self,
        batch: ProposalBatch,
        *,
        ddl_repository: str,
        snapshot_id: str,
        prompt_version: str,
        prompt_sha256: str,
        provider: str,
        model: str,
        temperature: float,
        max_tokens: int,
        warnings: Iterable[str] = (),
    ) -> ProposalWriteResult:
        """Persist a fully validated batch; never overwrite a differing record."""

        self._guard_root()
        batch_errors = validate_proposal_batch(batch)
        if batch_errors:
            raise ProposalValidationError(batch_errors)
        manifest_path = self.root / MANIFEST_FILENAME
        if batch.is_empty:
            return ProposalWriteResult(
                root=self.root,
                manifest_path=manifest_path,
                written=(),
                unchanged=(),
                conflicts=(),
                counts=batch.counts,
                status="no_proposals",
            )

        existing, scan_errors = _scan_records(self.root)
        if scan_errors:
            raise ProposalRepositoryValidationError(
                "Existing proposal repository is invalid and was not modified: "
                + "; ".join(scan_errors)
            )

        generation = GenerationMetadata(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            snapshot_id=snapshot_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        prepared_batch = batch.model_copy(
            update={
                "concepts": tuple(
                    item.model_copy(update={"generation": generation})
                    for item in batch.concepts
                ),
                "mappings": tuple(
                    item.model_copy(update={"generation": generation})
                    for item in batch.mappings
                ),
                "relationships": tuple(
                    item.model_copy(update={"generation": generation})
                    for item in batch.relationships
                ),
            }
        )

        planned: dict[str, _StoredRecord] = {}
        unchanged: list[str] = []
        conflicts: list[str] = []
        new_records: list[ProposalRecord] = [
            *prepared_batch.concepts,
            *prepared_batch.mappings,
            *prepared_batch.relationships,
        ]
        for record in new_records:
            content = _yaml_bytes(record.model_dump(mode="json"))
            current = existing.get(record.proposal_id)
            if current is not None:
                if current.content == content:
                    unchanged.append(record.proposal_id)
                else:
                    conflicts.append(record.proposal_id)
                continue
            path, relative = _record_path(self.root, record)
            planned[record.proposal_id] = _StoredRecord(
                record=record,
                path=path,
                relative_path=relative,
                content=content,
            )

        merged = dict(existing)
        merged.update(planned)
        merged_batch = _batch_from_records(merged)
        merged_errors = validate_proposal_batch(merged_batch)
        if merged_errors:
            raise ProposalRepositoryValidationError(
                "The merged proposal repository would be invalid and was not "
                "modified: " + "; ".join(merged_errors)
            )

        for proposal_id in sorted(planned):
            stored = planned[proposal_id]
            self._write_new(stored.path, stored.content)

        run_warnings = list(
            dict.fromkeys([*warnings, *prepared_batch.warnings])
        )
        if conflicts:
            run_warnings.append(
                f"{len(conflicts)} existing proposal record(s) differed and were not "
                "overwritten."
            )
        status: Literal["completed", "conflicts"] = (
            "conflicts" if conflicts else "completed"
        )
        manifest = ProposalManifest(
            schema_version=prepared_batch.schema_version,
            generator=ProposalGenerator(
                name=self.generator_name, version=self.generator_version
            ),
            last_run=ProposalRun(
                run_id=self._run_id_factory(),
                generated_at=_format_timestamp(self._clock()),
                ddl_repository=ddl_repository,
                snapshot_id=snapshot_id,
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                status=status,
                warnings=tuple(run_warnings),
            ),
            counts=ProposalManifestCounts(**_counts(merged)),
            artifacts=_manifest_artifacts(merged),
        )
        self._write_if_changed(
            manifest_path,
            canonical_bytes(manifest.model_dump(mode="json", by_alias=True)),
        )

        validation = validate_proposal_repository(self.root)
        if not validation.valid:
            raise ProposalRepositoryWriteError(
                "The written proposal repository failed validation: "
                + "; ".join(validation.errors)
            )
        return ProposalWriteResult(
            root=self.root,
            manifest_path=manifest_path,
            written=tuple(sorted(planned)),
            unchanged=tuple(sorted(unchanged)),
            conflicts=tuple(sorted(conflicts)),
            counts=_counts(merged),
            status=status,
        )
