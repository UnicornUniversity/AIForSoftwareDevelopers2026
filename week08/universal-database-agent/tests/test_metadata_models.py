from __future__ import annotations

from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    SchemaMetadata,
    TableMetadata,
    make_physical_id,
)
from uda.metadata.normalizer import (
    column_metadata,
    foreign_key_metadata,
    index_metadata,
    normalize_type,
    primary_key_metadata,
)


def test_physical_id_escapes_components() -> None:
    assert make_physical_id("sqlserver", "db", "dbo", "table", "A/B") == (
        "sqlserver/db/dbo/table/A%2FB"
    )


def test_normalize_known_and_unknown_types() -> None:
    assert normalize_type("nvarchar(50)") == "string"
    assert normalize_type("INT") == "integer"
    assert normalize_type("INTEGER") == "integer"
    assert normalize_type("uniqueidentifier") == "uuid"
    assert normalize_type("geography") is None


def test_column_metadata_computed_and_identity() -> None:
    column = column_metadata(
        "sqlserver/db/dbo/table/T",
        {
            "name": "Total",
            "type": "decimal(10, 2)",
            "nullable": False,
            "default": "0",
            "autoincrement": True,
            "computed": {"sqltext": "Price * Qty"},
        },
        3,
    )
    assert column.ordinal == 3
    assert column.normalized_type == "decimal"
    assert column.is_identity is True
    assert column.is_computed is True
    assert column.computed_expression == "Price * Qty"


def test_composite_keys_and_cross_schema_foreign_key() -> None:
    pk = primary_key_metadata(
        "sqlserver/db/dbo/table/OrderLines",
        {"name": "PK_OrderLines", "constrained_columns": ["OrderID", "LineID"]},
    )
    assert pk is not None
    assert pk.columns == ("OrderID", "LineID")
    fk = foreign_key_metadata(
        "sqlserver/db/dbo/table/OrderLines",
        "dbo",
        {
            "name": "FK_OrderLines_Orders",
            "constrained_columns": ["OrderID"],
            "referred_schema": "sales",
            "referred_table": "Orders",
            "referred_columns": ["OrderID"],
        },
        0,
    )
    assert fk.referred_schema == "sales"


def test_index_metadata() -> None:
    index = index_metadata(
        "sqlserver/db/dbo/table/T",
        {"name": "IX_T", "column_names": ["A", "B"], "unique": True},
    )
    assert index.columns == ("A", "B")
    assert index.unique is True


def test_database_metadata_counts_and_json_alias() -> None:
    table = TableMetadata(
        physical_id="sqlserver/db/dbo/table/T",
        schema_name="dbo",
        name="T",
        object_type="table",
        columns=(
            ColumnMetadata(
                physical_id="sqlserver/db/dbo/table/T/column/A",
                name="A",
                ordinal=1,
                data_type="int",
                normalized_type="integer",
            ),
        ),
        primary_key=PrimaryKeyMetadata(name="PK_T", columns=("A",)),
        foreign_keys=(
            ForeignKeyMetadata(
                name="FK_T",
                columns=("A",),
                referred_schema="dbo",
                referred_table="U",
                referred_columns=("A",),
            ),
        ),
        indexes=(IndexMetadata(name="IX_T", columns=("A",)),),
    )
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(database="db"),
        schemas=(SchemaMetadata(physical_id="sqlserver/db/schema/dbo", name="dbo"),),
        objects=(table,),
    )
    assert metadata.table_count == 1
    assert metadata.column_count == 1
    assert metadata.primary_key_count == 1
    assert metadata.foreign_key_count == 1
    assert metadata.index_count == 1
    dumped = metadata.model_dump(mode="json", by_alias=True)
    assert dumped["objects"][0]["schema"] == "dbo"
