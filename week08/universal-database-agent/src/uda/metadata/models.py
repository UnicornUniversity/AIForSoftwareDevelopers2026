"""Compact normalized physical database metadata.

This is a physical foundation for later Semantic Repository phases. It deliberately contains
no concepts, ontology, or semantic mappings.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MetadataModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def make_physical_id(
    platform: str,
    database: str,
    *parts: str,
) -> str:
    """Build a stable, escaped physical identifier (D-10)."""

    return "/".join(quote(str(part), safe="") for part in (platform, database, *parts))


def child_id(parent_id: str, *parts: str) -> str:
    return "/".join([parent_id, *(quote(str(part), safe="") for part in parts)])


class DatabaseIdentity(MetadataModel):
    platform: str = "sqlserver"
    database: str


class SchemaMetadata(MetadataModel):
    physical_id: str
    name: str
    is_system: bool = False


class ColumnMetadata(MetadataModel):
    physical_id: str
    name: str
    ordinal: int
    data_type: str
    normalized_type: str | None = None
    nullable: bool = True
    default: str | None = None
    is_identity: bool = False
    is_computed: bool = False
    computed_expression: str | None = None


class PrimaryKeyMetadata(MetadataModel):
    name: str | None = None
    columns: tuple[str, ...]
    physical_id: str | None = None
    column_ids: tuple[str, ...] = ()


class ForeignKeyMetadata(MetadataModel):
    name: str | None = None
    columns: tuple[str, ...]
    referred_schema: str
    referred_table: str
    referred_columns: tuple[str, ...]
    physical_id: str | None = None
    column_ids: tuple[str, ...] = ()
    referred_object_id: str | None = None
    referred_column_ids: tuple[str, ...] = ()


class IndexMetadata(MetadataModel):
    name: str | None = None
    columns: tuple[str, ...]
    unique: bool = False
    source: str = "index"
    physical_id: str | None = None
    column_ids: tuple[str, ...] = ()


class TableMetadata(MetadataModel):
    physical_id: str
    schema_name: str = Field(
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    name: str
    object_type: Literal["table", "view"]
    columns: tuple[ColumnMetadata, ...] = ()
    primary_key: PrimaryKeyMetadata | None = None
    foreign_keys: tuple[ForeignKeyMetadata, ...] = ()
    indexes: tuple[IndexMetadata, ...] = ()
    description: str | None = None


class ExtractionIssue(MetadataModel):
    kind: Literal[
        "permission",
        "unsupported",
        "not_applicable",
        "unavailable",
        "unsupported_type",
    ]
    object_id: str | None = None
    detail: str


class DatabaseMetadata(MetadataModel):
    identity: DatabaseIdentity
    schemas: tuple[SchemaMetadata, ...] = ()
    objects: tuple[TableMetadata, ...] = ()
    issues: tuple[ExtractionIssue, ...] = ()

    @property
    def table_count(self) -> int:
        return sum(1 for item in self.objects if item.object_type == "table")

    @property
    def view_count(self) -> int:
        return sum(1 for item in self.objects if item.object_type == "view")

    @property
    def column_count(self) -> int:
        return sum(len(item.columns) for item in self.objects)

    @property
    def primary_key_count(self) -> int:
        return sum(1 for item in self.objects if item.primary_key is not None)

    @property
    def foreign_key_count(self) -> int:
        return sum(len(item.foreign_keys) for item in self.objects)

    @property
    def index_count(self) -> int:
        return sum(len(item.indexes) for item in self.objects)
