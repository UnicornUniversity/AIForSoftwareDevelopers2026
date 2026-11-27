"""Deterministic snapshot identity.

The snapshot ID hashes the substantive repository content: database identity, generator
and schema versions, artifact paths and hashes, extraction issues, external references,
and the recorded extraction scope. Timestamps, run identity, and Git commit are
deliberately excluded, so two runs over unchanged structure produce the same ID.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .manifest import ManifestArtifact, ManifestDdl, ManifestExternalReference
from .serialization import canonical_bytes, sha256_hex


def ddl_snapshot_payload(ddl: ManifestDdl) -> dict[str, object]:
    """Return the deterministic, environment-independent DDL portion of the snapshot."""

    return {
        "status": ddl.status,
        "mechanism": ddl.mechanism,
        "version": ddl.version,
        "objects": sorted(
            (
                {
                    "physical_id": item.physical_id,
                    "kind": item.kind,
                    "status": item.status,
                    "provenance": item.provenance,
                    "is_original_text": item.is_original_text,
                    "path": item.path,
                    "sha256": item.sha256,
                }
                for item in ddl.objects
            ),
            key=lambda row: str(row["physical_id"]),
        ),
    }


def compute_snapshot_id(
    *,
    platform: str,
    database: str,
    schema_version: str,
    generator_name: str,
    generator_version: str,
    included_object_types: Sequence[str],
    excluded_object_types: Sequence[str],
    artifacts: Iterable[ManifestArtifact],
    issues_sha256: str,
    issues_count: int,
    external_references: Iterable[ManifestExternalReference],
    ddl: ManifestDdl | None = None,
) -> str:
    artifact_rows = sorted(
        (
            {
                "physical_id": item.physical_id,
                "kind": item.kind,
                "path": item.path,
                "sha256": item.sha256,
            }
            for item in artifacts
        ),
        key=lambda row: (str(row["kind"]), str(row["path"])),
    )
    reference_rows = sorted(
        (
            {"source_id": item.source_id, "target_id": item.target_id}
            for item in external_references
        ),
        key=lambda row: (str(row["source_id"]), str(row["target_id"])),
    )
    payload = {
        "platform": platform,
        "database": database,
        "schema_version": schema_version,
        "generator": {"name": generator_name, "version": generator_version},
        "scope": {
            "included_object_types": list(included_object_types),
            "excluded_object_types": list(excluded_object_types),
        },
        "artifacts": artifact_rows,
        "issues": {"sha256": issues_sha256, "count": issues_count},
        "external_references": reference_rows,
    }
    if ddl is not None and ddl.status != "not_requested":
        payload["ddl"] = ddl_snapshot_payload(ddl)
    return f"sha256:{sha256_hex(canonical_bytes(payload))}"
