"""Mapping from SQLAlchemy Inspector dictionaries to normalized metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from .models import (
    ColumnMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    child_id,
)

_TYPE_MAP = {
    "bigint": "integer",
    "binary": "binary",
    "bit": "boolean",
    "char": "string",
    "date": "date",
    "datetime": "datetime",
    "datetime2": "datetime",
    "datetimeoffset": "datetime",
    "decimal": "decimal",
    "float": "float",
    "image": "binary",
    "int": "integer",
    "integer": "integer",
    "money": "decimal",
    "nchar": "string",
    "ntext": "string",
    "numeric": "decimal",
    "nvarchar": "string",
    "real": "float",
    "rowversion": "binary",
    "smalldatetime": "datetime",
    "smallint": "integer",
    "smallmoney": "decimal",
    "text": "string",
    "time": "time",
    "timestamp": "binary",
    "tinyint": "integer",
    "uniqueidentifier": "uuid",
    "varbinary": "binary",
    "varchar": "string",
    "xml": "xml",
}


def normalize_type(data_type: str) -> str | None:
    """Return a compact normalized type name, or ``None`` when unmapped."""

    base = data_type.strip().split("(", 1)[0].strip().lower()
    return _TYPE_MAP.get(base)


def column_metadata(
    object_id: str,
    data: Mapping[str, Any],
    ordinal: int,
) -> ColumnMetadata:
    name = str(data.get("name", ""))
    data_type = str(data.get("type", ""))
    computed = data.get("computed")
    is_computed = bool(computed)
    computed_expression: str | None = None
    if isinstance(computed, Mapping):
        expression = computed.get("sqltext")
        computed_expression = str(expression) if expression is not None else None
    default = data.get("default")
    return ColumnMetadata(
        physical_id=child_id(object_id, "column", name),
        name=name,
        ordinal=ordinal,
        data_type=data_type,
        normalized_type=normalize_type(data_type),
        nullable=bool(data.get("nullable", True)),
        default=str(default) if default is not None else None,
        is_identity=bool(data.get("autoincrement", False)),
        is_computed=is_computed,
        computed_expression=computed_expression,
    )


def object_identity_prefix(object_id: str) -> tuple[str, str] | None:
    """Return the escaped (platform, database) prefix of an object Physical ID."""

    parts = object_id.split("/")
    if len(parts) != 5 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def referred_object_physical_id(object_id: str, schema: str, table: str) -> str | None:
    """Build the Physical ID of a foreign key's target table."""

    prefix = object_identity_prefix(object_id)
    if prefix is None or not schema or not table:
        return None
    platform, database = prefix
    return "/".join([platform, database, quote(schema, safe=""), "table", quote(table, safe="")])


def primary_key_physical_id(object_id: str, name: str | None) -> str:
    return child_id(object_id, "primary_key", name or "primary_key")


def foreign_key_physical_id(object_id: str, name: str | None, index: int) -> str:
    return child_id(object_id, "foreign_key", name or f"fk_{index + 1}")


def index_physical_id(
    object_id: str, name: str | None, columns: Sequence[str]
) -> str:
    return child_id(object_id, "index", name or ",".join(columns) or "index")


def primary_key_metadata(
    object_id: str, data: Mapping[str, Any] | None
) -> PrimaryKeyMetadata | None:
    if not data:
        return None
    columns = tuple(str(item) for item in data.get("constrained_columns", ()))
    if not columns:
        return None
    name = data.get("name")
    return PrimaryKeyMetadata(
        name=str(name) if name else None,
        columns=columns,
        physical_id=primary_key_physical_id(object_id, str(name) if name else None),
        column_ids=tuple(child_id(object_id, "column", column) for column in columns),
    )


def foreign_key_metadata(
    object_id: str,
    schema: str,
    data: Mapping[str, Any],
    index: int,
) -> ForeignKeyMetadata:
    name = data.get("name")
    columns = tuple(str(item) for item in data.get("constrained_columns", ()))
    referred_schema = str(data.get("referred_schema") or schema)
    referred_table = str(data.get("referred_table", ""))
    referred_columns = tuple(str(item) for item in data.get("referred_columns", ()))
    target_id = referred_object_physical_id(object_id, referred_schema, referred_table)
    return ForeignKeyMetadata(
        name=str(name) if name else f"fk_{index + 1}",
        columns=columns,
        referred_schema=referred_schema,
        referred_table=referred_table,
        referred_columns=referred_columns,
        physical_id=foreign_key_physical_id(
            object_id, str(name) if name else None, index
        ),
        column_ids=tuple(child_id(object_id, "column", column) for column in columns),
        referred_object_id=target_id,
        referred_column_ids=(
            tuple(child_id(target_id, "column", column) for column in referred_columns)
            if target_id is not None
            else ()
        ),
    )


def index_metadata(
    object_id: str,
    data: Mapping[str, Any],
    source: str = "index",
) -> IndexMetadata:
    name = data.get("name")
    columns = tuple(
        str(item) for item in data.get("column_names", ()) if item is not None
    )
    return IndexMetadata(
        name=str(name) if name else None,
        columns=columns,
        unique=bool(data.get("unique", False)),
        source=source,
        physical_id=index_physical_id(object_id, str(name) if name else None, columns),
        column_ids=tuple(child_id(object_id, "column", column) for column in columns),
    )


def dedupe_indexes(items: Sequence[IndexMetadata]) -> tuple[IndexMetadata, ...]:
    seen: set[tuple[str | None, tuple[str, ...], bool, str]] = set()
    result: list[IndexMetadata] = []
    for item in items:
        key = (item.name, item.columns, item.unique, item.source)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)
