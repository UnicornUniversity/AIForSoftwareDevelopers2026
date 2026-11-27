"""Deterministic schema context for natural-language SQL generation.

The context is built from the DDL Repository's normalized metadata, never from table rows.
It lists only the objects the validator will accept, so the generation prompt and the
object allowlist cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..metadata.models import ColumnMetadata, DatabaseMetadata, TableMetadata

DEFAULT_MAX_CONTEXT_CHARS = 24_000
_MAX_DESCRIPTION_CHARS = 240


@dataclass(frozen=True)
class SchemaContext:
    """Compact, prompt-ready description of the queryable schema."""

    text: str
    allowed_objects: frozenset[str]
    default_schema: str
    database: str
    object_count: int
    warnings: tuple[str, ...] = ()


def _short_description(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(value.split())
    if len(text) > _MAX_DESCRIPTION_CHARS:
        text = text[:_MAX_DESCRIPTION_CHARS] + "..."
    return text


def _column_label(column: ColumnMetadata, table: TableMetadata) -> str:
    parts = [column.name, column.data_type]
    if not column.nullable:
        parts.append("NOT NULL")
    if table.primary_key is not None and column.name in table.primary_key.columns:
        parts.append("[PK]")
    for key in table.foreign_keys:
        if column.name not in key.columns:
            continue
        target = f"{key.referred_schema}.{key.referred_table}"
        referred = ", ".join(key.referred_columns)
        parts.append(f"[FK -> {target}.{referred}]")
    return " ".join(parts)


def _object_block(table: TableMetadata) -> str:
    columns = ", ".join(_column_label(column, table) for column in table.columns)
    description = _short_description(table.description)
    suffix = f" — {description}" if description else ""
    header = f"- {table.schema_name}.{table.name} ({table.object_type}){suffix}"
    if not columns:
        return header
    return f"{header}\n  Columns: {columns}"


def build_schema_context(
    metadata: DatabaseMetadata,
    *,
    default_schema: str = "dbo",
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> SchemaContext:
    """Render compact schema text and the matching object allowlist."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    objects = sorted(metadata.objects, key=lambda item: (item.schema_name, item.name))
    allowed = frozenset(
        f"{item.schema_name}.{item.name}".lower() for item in objects
    )
    warnings: list[str] = []

    lines = [
        f"Database: {metadata.identity.database} ({metadata.identity.platform})",
        "Queryable objects (use only these schema-qualified names):",
    ]
    body: list[str] = []
    omitted: list[str] = []
    used = len("\n".join(lines))
    for table in objects:
        block = _object_block(table)
        if used + len(block) + 1 > max_chars:
            omitted.append(f"{table.schema_name}.{table.name}")
            continue
        body.append(block)
        used += len(block) + 1

    lines.extend(body)
    if omitted:
        lines.append("Objects omitted from details due to the context budget:")
        lines.extend(f"- {name}" for name in omitted)
        warnings.append(
            f"Schema context omitted details for {len(omitted)} object(s); "
            "the model cannot reason about their columns."
        )

    if not objects:
        warnings.append("The DDL Repository contains no queryable objects.")

    return SchemaContext(
        text="\n".join(lines),
        allowed_objects=allowed,
        default_schema=default_schema,
        database=metadata.identity.database,
        object_count=len(objects),
        warnings=tuple(warnings),
    )
