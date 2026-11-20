"""Schema sources, lookup, and deterministic schema versioning.

The fixture provider is the default and runs fully offline. Database-specific
providers live in their own modules and implement the same ``SchemaProvider``
shape. Schema versioning is provider-independent.
"""

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from uda.models import TableSchema


class UnknownTableError(LookupError):
    """Raised when a requested table is absent or ambiguous."""


class FixtureCatalog(BaseModel):
    """The on-disk shape of a local schema fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture_version: int
    tables: tuple[TableSchema, ...]

    @field_validator("tables")
    @classmethod
    def _validate_tables(
        cls, tables: tuple[TableSchema, ...]
    ) -> tuple[TableSchema, ...]:
        if not tables:
            raise ValueError("fixture must contain at least one table")

        seen: set[str] = set()
        duplicates: set[str] = set()
        for table in tables:
            key = table.qualified_name.casefold()
            if key in seen:
                duplicates.add(key)
            seen.add(key)

        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate qualified table names: {joined}")
        return tables


class SchemaProvider(Protocol):
    """One source of table schemas."""

    def load(self, table_name: str) -> TableSchema:
        """Return one table or raise ``UnknownTableError``."""
        ...


def load_fixture_catalog(
    fixture_path: Path | str | None = None,
) -> FixtureCatalog:
    """Load the bundled fixture or a caller-supplied fixture file."""
    if fixture_path is None:
        raw = (
            files("uda.fixtures")
            .joinpath("demo_schema.json")
            .read_text(encoding="utf-8")
        )
    else:
        raw = Path(fixture_path).read_text(encoding="utf-8")
    return FixtureCatalog.model_validate_json(raw)


class FixtureSchemaProvider:
    """Schema provider backed by a local JSON catalog."""

    def __init__(self, fixture_path: Path | str | None = None) -> None:
        self._catalog = load_fixture_catalog(fixture_path)

    @property
    def catalog(self) -> FixtureCatalog:
        """Return the loaded catalog."""
        return self._catalog

    def load(self, table_name: str) -> TableSchema:
        reference = table_name.strip()
        if not reference:
            raise UnknownTableError("table name is empty")

        key = reference.casefold()
        matches = [
            table
            for table in self._catalog.tables
            if table.qualified_name.casefold() == key
        ]
        if not matches:
            matches = [
                table
                for table in self._catalog.tables
                if table.table_name.casefold() == key
            ]

        if not matches:
            raise UnknownTableError(
                f"table {reference!r} is not present in the fixture"
            )
        if len(matches) > 1:
            names = ", ".join(table.qualified_name for table in matches)
            raise UnknownTableError(
                f"table {reference!r} is ambiguous; use one of: {names}"
            )
        return matches[0]


def schema_version(schema: TableSchema) -> str:
    """Return a deterministic SHA-256 fingerprint of one table's metadata."""
    canonical = {
        "schema_name": schema.schema_name,
        "table_name": schema.table_name,
        "columns": [
            {
                "name": column.name,
                "sql_type": column.sql_type,
                "nullable": column.nullable,
                "is_primary_key": column.is_primary_key,
            }
            for column in sorted(schema.columns, key=lambda item: item.name)
        ],
    }
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
