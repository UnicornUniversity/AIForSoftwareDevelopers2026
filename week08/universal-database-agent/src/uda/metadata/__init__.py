"""Normalized physical metadata models."""

from .identity import ensure_physical_ids
from .models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from .normalizer import (
    column_metadata,
    dedupe_indexes,
    foreign_key_metadata,
    index_metadata,
    normalize_type,
    primary_key_metadata,
)

__all__ = [
    "ColumnMetadata",
    "DatabaseIdentity",
    "DatabaseMetadata",
    "ExtractionIssue",
    "ForeignKeyMetadata",
    "IndexMetadata",
    "PrimaryKeyMetadata",
    "SchemaMetadata",
    "TableMetadata",
    "child_id",
    "column_metadata",
    "dedupe_indexes",
    "ensure_physical_ids",
    "foreign_key_metadata",
    "index_metadata",
    "make_physical_id",
    "normalize_type",
    "primary_key_metadata",
]
