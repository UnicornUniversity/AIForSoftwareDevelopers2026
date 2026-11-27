"""Physical ID completion for normalized metadata.

Adapters and recorded fixtures may supply object and column Physical IDs without the
derived key/index/reference IDs. The DDL Repository requires every persisted object to
carry a stable ID, so this module fills only the missing derived fields and never
replaces an ID that is already present.
"""

from __future__ import annotations

from .models import (
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    TableMetadata,
    child_id,
)
from .normalizer import (
    foreign_key_physical_id,
    index_physical_id,
    primary_key_physical_id,
    referred_object_physical_id,
)


def _column_ids(object_id: str, columns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(child_id(object_id, "column", column) for column in columns)


def _complete_primary_key(
    object_id: str, primary_key: PrimaryKeyMetadata
) -> PrimaryKeyMetadata:
    updates: dict[str, object] = {}
    if primary_key.physical_id is None:
        updates["physical_id"] = primary_key_physical_id(object_id, primary_key.name)
    if not primary_key.column_ids:
        updates["column_ids"] = _column_ids(object_id, primary_key.columns)
    return primary_key.model_copy(update=updates) if updates else primary_key


def _complete_foreign_key(
    object_id: str, foreign_key: ForeignKeyMetadata, index: int
) -> ForeignKeyMetadata:
    updates: dict[str, object] = {}
    if foreign_key.physical_id is None:
        updates["physical_id"] = foreign_key_physical_id(
            object_id, foreign_key.name, index
        )
    if not foreign_key.column_ids:
        updates["column_ids"] = _column_ids(object_id, foreign_key.columns)
    target_id = foreign_key.referred_object_id or referred_object_physical_id(
        object_id, foreign_key.referred_schema, foreign_key.referred_table
    )
    if target_id != foreign_key.referred_object_id:
        updates["referred_object_id"] = target_id
    if not foreign_key.referred_column_ids and target_id is not None:
        updates["referred_column_ids"] = _column_ids(
            target_id, foreign_key.referred_columns
        )
    return foreign_key.model_copy(update=updates) if updates else foreign_key


def _complete_index(object_id: str, index: IndexMetadata) -> IndexMetadata:
    updates: dict[str, object] = {}
    if index.physical_id is None:
        updates["physical_id"] = index_physical_id(object_id, index.name, index.columns)
    if not index.column_ids:
        updates["column_ids"] = _column_ids(object_id, index.columns)
    return index.model_copy(update=updates) if updates else index


def _complete_object(table: TableMetadata) -> TableMetadata:
    objects: dict[str, object] = {}
    if table.primary_key is not None:
        objects["primary_key"] = _complete_primary_key(
            table.physical_id, table.primary_key
        )
    if table.foreign_keys:
        objects["foreign_keys"] = tuple(
            _complete_foreign_key(table.physical_id, item, index)
            for index, item in enumerate(table.foreign_keys)
        )
    if table.indexes:
        objects["indexes"] = tuple(
            _complete_index(table.physical_id, item) for item in table.indexes
        )
    return table.model_copy(update=objects) if objects else table


def ensure_physical_ids(metadata: DatabaseMetadata) -> DatabaseMetadata:
    """Return metadata with every derived key/index/reference ID populated."""

    objects = tuple(_complete_object(item) for item in metadata.objects)
    if objects == metadata.objects:
        return metadata
    return metadata.model_copy(update={"objects": objects})
