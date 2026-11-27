"""Root ``manifest.json`` schema for the DDL Repository (``Q-02``).

The manifest is the repository's index and validity gate. It records snapshot identity,
generator and schema versions, the Git commit that produced the snapshot (or why it is
unavailable), database identity, extraction metadata, counts, and artifact references.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..metadata.models import MetadataModel
from .naming import ISSUES_FILENAME

MANIFEST_VERSION = "1.0"
DDL_SCHEMA_VERSION = "1.0"
GENERATOR_NAME = "uda"

DEFAULT_INCLUDED_OBJECT_TYPES = ("table", "view")
DEFAULT_EXCLUDED_OBJECT_TYPES = (
    "stored_procedure",
    "function",
    "trigger",
    "sequence",
    "synonym",
)


class ManifestSnapshot(MetadataModel):
    id: str
    run_id: str
    created_at: str
    status: Literal["complete", "partial"]


class ManifestGenerator(MetadataModel):
    name: str = GENERATOR_NAME
    version: str


class ManifestGit(MetadataModel):
    available: bool
    commit: str | None = None
    detail: str | None = None


class ManifestDatabase(MetadataModel):
    platform: str
    name: str
    schemas: tuple[str, ...] = ()


class ManifestSmo(MetadataModel):
    available: bool
    version: str | None = None
    mechanism: str | None = None
    detail: str = ""


class ManifestOriginalDdl(MetadataModel):
    available: bool
    reason: str


class ManifestIssuesArtifact(MetadataModel):
    path: str = ISSUES_FILENAME
    sha256: str
    count: int


class ManifestDdlObject(MetadataModel):
    physical_id: str
    kind: Literal["table", "view"]
    status: Literal["extracted", "unavailable", "failed", "unsupported"]
    provenance: str | None = None
    is_original_text: bool = False
    path: str | None = None
    sha256: str | None = None
    error: str | None = None


class ManifestDdl(MetadataModel):
    status: Literal[
        "complete", "partial", "failed", "unavailable", "not_requested"
    ]
    mechanism: str | None = None
    version: str | None = None
    detail: str = ""
    objects: tuple[ManifestDdlObject, ...] = ()


class ManifestExtraction(MetadataModel):
    source: str
    started_at: str
    completed_at: str
    issue_count: int
    issues: ManifestIssuesArtifact
    smo: ManifestSmo
    original_ddl: ManifestOriginalDdl
    ddl: ManifestDdl | None = None


class ManifestCounts(MetadataModel):
    schemas: int = 0
    tables: int = 0
    views: int = 0
    columns: int = 0
    primary_keys: int = 0
    foreign_keys: int = 0
    indexes: int = 0


class ManifestArtifact(MetadataModel):
    physical_id: str
    kind: Literal["schema", "table", "view"]
    path: str
    sha256: str


class ManifestArtifacts(MetadataModel):
    schemas: tuple[ManifestArtifact, ...] = ()
    objects: tuple[ManifestArtifact, ...] = ()


class ManifestExternalReference(MetadataModel):
    source_id: str
    target_id: str


class ManifestScope(MetadataModel):
    included_object_types: tuple[str, ...] = Field(
        default=DEFAULT_INCLUDED_OBJECT_TYPES
    )
    excluded_object_types: tuple[str, ...] = Field(
        default=DEFAULT_EXCLUDED_OBJECT_TYPES
    )


class DdlManifest(MetadataModel):
    manifest_version: str
    repository: Literal["ddl"]
    snapshot: ManifestSnapshot
    generator: ManifestGenerator
    schema_version: str
    git: ManifestGit
    database: ManifestDatabase
    extraction: ManifestExtraction
    counts: ManifestCounts
    artifacts: ManifestArtifacts
    external_references: tuple[ManifestExternalReference, ...] = ()
    scope: ManifestScope = Field(default_factory=ManifestScope)
