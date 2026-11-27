"""DDL Repository: deterministic artifacts, manifest, writing, and validation."""

from .manifest import (
    DDL_SCHEMA_VERSION,
    GENERATOR_NAME,
    MANIFEST_VERSION,
    DdlManifest,
)
from .naming import (
    ISSUES_FILENAME,
    MANIFEST_FILENAME,
    artifact_filename,
    artifact_relative_path,
    resolve_within,
    safe_relative_path,
    slugify,
)
from .validation import (
    ReferenceCheck,
    RepositoryValidation,
    validate_metadata,
    validate_repository,
)
from .writer import (
    DdlRepositoryWriter,
    GitState,
    RepositoryChange,
    WriteResult,
    detect_git_commit,
    prepare_metadata,
)

__all__ = [
    "DDL_SCHEMA_VERSION",
    "DdlManifest",
    "DdlRepositoryWriter",
    "GENERATOR_NAME",
    "GitState",
    "ISSUES_FILENAME",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "ReferenceCheck",
    "RepositoryChange",
    "RepositoryValidation",
    "WriteResult",
    "artifact_filename",
    "artifact_relative_path",
    "detect_git_commit",
    "prepare_metadata",
    "resolve_within",
    "safe_relative_path",
    "slugify",
    "validate_metadata",
    "validate_repository",
]
