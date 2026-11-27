from __future__ import annotations

from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ForeignKeyMetadata,
    PrimaryKeyMetadata,
    TableMetadata,
    make_physical_id,
)
from uda.query.context import build_schema_context


def make_metadata() -> DatabaseMetadata:
    customers_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Customers")
    orders_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Orders")
    customers = TableMetadata(
        physical_id=customers_id,
        schema_name="dbo",
        name="Customers",
        object_type="table",
        description="Companies that buy products.",
        columns=(
            ColumnMetadata(
                physical_id=f"{customers_id}/column/CustomerID",
                name="CustomerID",
                ordinal=1,
                data_type="nvarchar",
                nullable=False,
            ),
            ColumnMetadata(
                physical_id=f"{customers_id}/column/CompanyName",
                name="CompanyName",
                ordinal=2,
                data_type="nvarchar",
                nullable=False,
            ),
        ),
        primary_key=PrimaryKeyMetadata(
            name="PK_Customers",
            columns=("CustomerID",),
            physical_id=f"{customers_id}/primary_key/PK_Customers",
        ),
    )
    orders = TableMetadata(
        physical_id=orders_id,
        schema_name="dbo",
        name="Orders",
        object_type="table",
        columns=(
            ColumnMetadata(
                physical_id=f"{orders_id}/column/OrderID",
                name="OrderID",
                ordinal=1,
                data_type="int",
                nullable=False,
            ),
            ColumnMetadata(
                physical_id=f"{orders_id}/column/CustomerID",
                name="CustomerID",
                ordinal=2,
                data_type="nvarchar",
                nullable=False,
            ),
        ),
        foreign_keys=(
            ForeignKeyMetadata(
                name="FK_Orders_Customers",
                columns=("CustomerID",),
                referred_schema="dbo",
                referred_table="Customers",
                referred_columns=("CustomerID",),
                physical_id=f"{orders_id}/foreign_key/FK_Orders_Customers",
            ),
        ),
    )
    return DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        objects=(orders, customers),
    )


def test_context_lists_objects_columns_and_keys() -> None:
    context = build_schema_context(make_metadata())

    assert context.allowed_objects == frozenset({"dbo.customers", "dbo.orders"})
    assert "dbo.Customers (table)" in context.text
    assert "Companies that buy products." in context.text
    assert "CustomerID nvarchar NOT NULL [PK]" in context.text
    assert "[FK -> dbo.Customers.CustomerID]" in context.text
    assert context.warnings == ()


def test_context_truncation_is_reported() -> None:
    context = build_schema_context(make_metadata(), max_chars=140)

    assert context.warnings
    assert "omitted details" in context.warnings[0]
    assert "Objects omitted from details" in context.text


def test_empty_schema_is_reported() -> None:
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind")
    )
    context = build_schema_context(metadata)

    assert context.object_count == 0
    assert context.allowed_objects == frozenset()
    assert "no queryable objects" in context.warnings[0]
