"""Database adapter contract.

Platform-specific extraction and execution live behind this boundary (D-04). Phase 1 ships
only a fake implementation; the SQL Server adapter arrives in Phase 2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..metadata.models import DatabaseMetadata


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    default: str | None = None
    is_identity: bool = False


@dataclass(frozen=True)
class ObjectInfo:
    physical_id: str
    schema: str
    name: str
    object_type: str


@dataclass(frozen=True)
class ReadResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    truncated: bool = False


class DatabaseAdapter(Protocol):
    """Capabilities required of every database adapter."""

    @property
    def dialect(self) -> str:
        """SQLGlot dialect key for this platform."""

    def connect(self) -> None:
        """Open a read-only session."""

    def list_schemas(self) -> Sequence[str]:
        """Return visible schema names in deterministic order."""

    def list_objects(self, schema: str | None = None) -> Sequence[ObjectInfo]:
        """Return tables and views in deterministic order."""

    def describe_object(self, physical_id: str) -> Sequence[ColumnInfo]:
        """Return column and key metadata for one object."""

    def extract_ddl(self, physical_id: str) -> str:
        """Return the original DDL for one object."""

    def execute_read(self, sql: str, *, timeout_seconds: int, row_limit: int) -> ReadResult:
        """Execute a validated read-only statement within limits."""

    def introspect(self, schemas: Sequence[str] | None = None) -> DatabaseMetadata:
        """Return normalized physical metadata for the selected schemas."""

    def close(self) -> None:
        """Close the session."""
