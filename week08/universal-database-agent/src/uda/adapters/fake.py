"""Deterministic fake adapter for offline contract tests."""

from __future__ import annotations

from collections.abc import Sequence

from ..errors import AdapterError
from ..metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from .base import ColumnInfo, ObjectInfo, ReadResult


class FakeAdapter:
    """In-memory adapter with a tiny canned Northwind-like schema.

    The fake does not model row limits or truncation; Phase 2 adapters must implement both.
    An unknown schema filter returns an empty tuple, meaning "no matching objects" for the
    fake, not "objects are invisible".
    """

    def __init__(self) -> None:
        self._connected = False
        self._objects = (
            ObjectInfo(
                physical_id="sqlserver/Northwind/dbo/table/Customers",
                schema="dbo",
                name="Customers",
                object_type="table",
            ),
            ObjectInfo(
                physical_id="sqlserver/Northwind/dbo/table/Orders",
                schema="dbo",
                name="Orders",
                object_type="table",
            ),
        )

    @property
    def dialect(self) -> str:
        return "tsql"

    def connect(self) -> None:
        self._connected = True

    def _require_session(self) -> None:
        if not self._connected:
            raise AdapterError("Adapter is not connected.")

    def list_schemas(self) -> Sequence[str]:
        self._require_session()
        return ("dbo",)

    def list_objects(self, schema: str | None = None) -> Sequence[ObjectInfo]:
        self._require_session()
        if schema is None:
            return self._objects
        return tuple(item for item in self._objects if item.schema == schema)

    def describe_object(self, physical_id: str) -> Sequence[ColumnInfo]:
        self._require_session()
        if physical_id.endswith("/Customers"):
            return (
                ColumnInfo("CustomerID", 1, "nvarchar", False),
                ColumnInfo("CompanyName", 2, "nvarchar", False),
            )
        if physical_id.endswith("/Orders"):
            return (
                ColumnInfo("OrderID", 1, "int", False),
                ColumnInfo("CustomerID", 2, "nvarchar", False),
            )
        raise AdapterError(f"Unknown object: {physical_id}")

    def extract_ddl(self, physical_id: str) -> str:
        self._require_session()
        if physical_id.endswith("/Customers"):
            return "CREATE TABLE dbo.Customers (CustomerID nvarchar(5) NOT NULL);"
        if physical_id.endswith("/Orders"):
            return "CREATE TABLE dbo.Orders (OrderID int NOT NULL);"
        raise AdapterError(f"Unsupported object: {physical_id}")

    def execute_read(self, sql: str, *, timeout_seconds: int, row_limit: int) -> ReadResult:
        self._require_session()
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AdapterError("The fake adapter only accepts SELECT statements.")
        return ReadResult(columns=("value",), rows=((1,),), truncated=False)

    def introspect(self, schemas: Sequence[str] | None = None) -> DatabaseMetadata:
        self._require_session()
        identity = DatabaseIdentity(platform="sqlserver", database="Northwind")
        if schemas is not None and "dbo" not in schemas:
            return DatabaseMetadata(identity=identity)

        customers_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Customers")
        orders_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Orders")
        customers = TableMetadata(
            physical_id=customers_id,
            schema_name="dbo",
            name="Customers",
            object_type="table",
            columns=(
                ColumnMetadata(
                    physical_id=child_id(customers_id, "column", "CustomerID"),
                    name="CustomerID",
                    ordinal=1,
                    data_type="nvarchar(5)",
                    normalized_type="string",
                    nullable=False,
                ),
                ColumnMetadata(
                    physical_id=child_id(customers_id, "column", "CompanyName"),
                    name="CompanyName",
                    ordinal=2,
                    data_type="nvarchar(40)",
                    normalized_type="string",
                    nullable=False,
                ),
            ),
            primary_key=PrimaryKeyMetadata(
                name="PK_Customers", columns=("CustomerID",)
            ),
            indexes=(
                IndexMetadata(
                    name="IX_Customers_CompanyName",
                    columns=("CompanyName",),
                    unique=False,
                ),
            ),
        )
        orders = TableMetadata(
            physical_id=orders_id,
            schema_name="dbo",
            name="Orders",
            object_type="table",
            columns=(
                ColumnMetadata(
                    physical_id=child_id(orders_id, "column", "OrderID"),
                    name="OrderID",
                    ordinal=1,
                    data_type="int",
                    normalized_type="integer",
                    nullable=False,
                    is_identity=True,
                ),
                ColumnMetadata(
                    physical_id=child_id(orders_id, "column", "CustomerID"),
                    name="CustomerID",
                    ordinal=2,
                    data_type="nvarchar(5)",
                    normalized_type="string",
                    nullable=False,
                ),
            ),
            primary_key=PrimaryKeyMetadata(name="PK_Orders", columns=("OrderID",)),
            foreign_keys=(
                ForeignKeyMetadata(
                    name="FK_Orders_Customers",
                    columns=("CustomerID",),
                    referred_schema="dbo",
                    referred_table="Customers",
                    referred_columns=("CustomerID",),
                ),
            ),
        )
        return DatabaseMetadata(
            identity=identity,
            schemas=(
                SchemaMetadata(
                    physical_id=make_physical_id(
                        "sqlserver", "Northwind", "schema", "dbo"
                    ),
                    name="dbo",
                ),
            ),
            objects=(customers, orders),
        )

    def close(self) -> None:
        self._connected = False
