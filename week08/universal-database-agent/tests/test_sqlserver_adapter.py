from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from uda.adapters.sqlserver import SqlServerAdapter
from uda.config import DatabaseConfig
from uda.errors import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterError,
    UnsupportedCapabilityError,
)


class FakeResult:
    def __init__(
        self,
        rows: tuple[Any, ...] = (),
        columns: tuple[str, ...] = (),
    ) -> None:
        self._rows = rows
        self._columns = columns

    def all(self) -> list[Any]:
        return list(self._rows)

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def fetchmany(self, size: int) -> list[Any]:
        return list(self._rows)[:size]


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def execute(self, statement: Any) -> FakeResult:
        text = str(statement).lower()
        self._engine.statements.append(text)
        if "extended_properties" in text:
            return FakeResult(self._engine.description_rows)
        if "computed_columns" in text:
            return FakeResult(self._engine.computed_rows)
        return FakeResult(self._engine.read_rows, self._engine.read_columns)

    def rollback(self) -> None:
        self._engine.rolled_back = True


class FakeEngine:
    def __init__(
        self,
        description_rows: tuple[Any, ...] = (),
        computed_rows: tuple[Any, ...] = (),
        read_rows: tuple[Any, ...] = (),
        read_columns: tuple[str, ...] = (),
    ) -> None:
        self.statements: list[str] = []
        self.description_rows = description_rows
        self.computed_rows = computed_rows
        self.read_rows = read_rows
        self.read_columns = read_columns
        self.disposed = False
        self.rolled_back = False

    def connect(self) -> FakeConnection:
        return FakeConnection(self)

    def dispose(self) -> None:
        self.disposed = True


class FakeInspector:
    def __init__(self, fail_tables: set[str] | None = None) -> None:
        self.fail_tables = fail_tables or set()

    def get_schema_names(self) -> list[str]:
        return ["dbo"]

    def get_table_names(self, schema: str | None = None) -> list[str]:
        return ["Customers", "Orders"] if schema == "dbo" else []

    def get_view_names(self, schema: str | None = None) -> list[str]:
        return ["CustomerSummary"] if schema == "dbo" else []

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
        if table_name in self.fail_tables:
            raise OperationalError("SELECT", {}, Exception("permission denied"))
        if table_name == "Customers":
            return [
                {"name": "CustomerID", "type": "nvarchar(5)", "nullable": False},
                {"name": "CompanyName", "type": "nvarchar(40)", "nullable": False},
            ]
        if table_name == "Orders":
            return [
                {"name": "OrderID", "type": "int", "nullable": False, "autoincrement": True},
                {"name": "CustomerID", "type": "nvarchar(5)", "nullable": False},
                {"name": "Total", "type": "decimal(10, 2)", "nullable": True},
            ]
        if table_name == "CustomerSummary":
            return [
                {"name": "CustomerID", "type": "nvarchar(5)", "nullable": False},
                {"name": "CompanyName", "type": "nvarchar(40)", "nullable": False},
            ]
        return []

    def get_pk_constraint(self, table_name: str, schema: str | None = None) -> dict[str, Any]:
        if table_name == "Customers":
            return {"name": "PK_Customers", "constrained_columns": ["CustomerID"]}
        return {"name": "PK_Orders", "constrained_columns": ["OrderID"]}

    def get_foreign_keys(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
        if table_name == "Orders":
            return [
                {
                    "name": "FK_Orders_Customers",
                    "constrained_columns": ["CustomerID"],
                    "referred_schema": "dbo",
                    "referred_table": "Customers",
                    "referred_columns": ["CustomerID"],
                }
            ]
        return []

    def get_indexes(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
        if table_name == "Customers":
            return [
                {
                    "name": "IX_Customers_Company",
                    "column_names": ["CompanyName"],
                    "unique": False,
                }
            ]
        return []

    def get_unique_constraints(
        self, table_name: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        if table_name == "Customers":
            return [{"name": "UQ_Customers_Company", "column_names": ["CompanyName"]}]
        return []


def make_config() -> DatabaseConfig:
    return DatabaseConfig(
        host="localhost",
        name="Northwind",
        username="reader",
        password="super-secret",
        trusted_connection=False,
    )


def make_adapter(
    engine: FakeEngine | None = None,
    inspector: FakeInspector | None = None,
    *,
    driver_provider: Any = None,
) -> SqlServerAdapter:
    config = make_config()
    fake_engine = engine or FakeEngine(
        description_rows=(
            SimpleNamespace(
                schema_name="dbo", object_name="Customers", description="Customer master"
            ),
        ),
        computed_rows=(
            SimpleNamespace(
                schema_name="dbo",
                table_name="Orders",
                column_name="Total",
                definition="Quantity * UnitPrice",
            ),
        ),
    )
    fake_inspector = inspector or FakeInspector()
    return SqlServerAdapter(
        config,
        engine_factory=lambda url: fake_engine,
        inspector_factory=lambda engine: fake_inspector,
        driver_provider=driver_provider
        or (lambda: ("ODBC Driver 18 for SQL Server",)),
    )


def test_connect_and_close_lifecycle() -> None:
    engine = FakeEngine()
    adapter = make_adapter(engine)
    adapter.connect()
    adapter.connect()
    assert any("select 1" in statement for statement in engine.statements)
    adapter.close()
    adapter.close()
    assert engine.disposed is True


def test_driver_missing_is_configuration_error() -> None:
    adapter = make_adapter(driver_provider=lambda: ("SQL Server",))
    with pytest.raises(AdapterConfigurationError, match="not installed"):
        adapter.connect()


def test_connection_error_is_sanitized() -> None:
    config = make_config()

    def failing_engine(url: Any) -> Any:
        raise OperationalError("stmt", {}, Exception("Login failed (18456) for reader"))

    adapter = SqlServerAdapter(
        config,
        engine_factory=failing_engine,
        inspector_factory=lambda engine: FakeInspector(),
        driver_provider=lambda: (config.driver,),
    )
    with pytest.raises(AdapterConnectionError) as excinfo:
        adapter.connect()
    message = str(excinfo.value)
    assert "authentication failed" in message
    assert "super-secret" not in message


def test_list_schemas_and_objects() -> None:
    adapter = make_adapter()
    adapter.connect()
    assert adapter.list_schemas() == ("dbo",)
    objects = adapter.list_objects()
    assert [item.name for item in objects] == ["Customers", "Orders", "CustomerSummary"]


def test_describe_object_returns_columns() -> None:
    adapter = make_adapter()
    adapter.connect()
    columns = adapter.describe_object("sqlserver/Northwind/dbo/table/Customers")
    assert [column.name for column in columns] == ["CustomerID", "CompanyName"]
    assert columns[0].nullable is False


def test_introspect_normalizes_metadata() -> None:
    adapter = make_adapter()
    adapter.connect()
    metadata = adapter.introspect()
    assert metadata.identity.database == "Northwind"
    assert metadata.table_count == 2
    assert metadata.view_count == 1
    assert metadata.column_count == 7
    assert metadata.primary_key_count == 2
    assert metadata.foreign_key_count == 1
    customers = next(item for item in metadata.objects if item.name == "Customers")
    assert customers.primary_key is not None
    assert customers.primary_key.columns == ("CustomerID",)
    assert customers.description == "Customer master"
    orders = next(item for item in metadata.objects if item.name == "Orders")
    total = next(column for column in orders.columns if column.name == "Total")
    assert total.normalized_type == "decimal"
    assert total.computed_expression == "Quantity * UnitPrice"
    assert orders.foreign_keys[0].referred_table == "Customers"


def test_introspect_records_permission_issue() -> None:
    adapter = make_adapter(inspector=FakeInspector(fail_tables={"Orders"}))
    adapter.connect()
    metadata = adapter.introspect()
    assert any(issue.kind == "permission" for issue in metadata.issues)
    assert any(item.name == "Customers" for item in metadata.objects)


def test_introspect_records_unsupported_type() -> None:
    class GeographyInspector(FakeInspector):
        def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
            if table_name == "Customers":
                return [{"name": "Location", "type": "geography", "nullable": True}]
            return super().get_columns(table_name, schema)

    adapter = make_adapter(inspector=GeographyInspector())
    adapter.connect()
    metadata = adapter.introspect()
    assert any(issue.kind == "unsupported_type" for issue in metadata.issues)


def test_extract_ddl_is_explicitly_unsupported() -> None:
    adapter = make_adapter()
    adapter.connect()
    with pytest.raises(UnsupportedCapabilityError):
        adapter.extract_ddl("sqlserver/Northwind/dbo/table/Customers")


def test_execute_read_returns_rows_and_reports_truncation() -> None:
    engine = FakeEngine(
        read_rows=((1, "A"), (2, "B"), (3, "C")),
        read_columns=("OrderID", "CustomerID"),
    )
    adapter = make_adapter(engine=engine)
    adapter.connect()

    result = adapter.execute_read(
        "SELECT OrderID, CustomerID FROM dbo.Orders",
        timeout_seconds=5,
        row_limit=2,
    )

    assert result.columns == ("OrderID", "CustomerID")
    assert result.rows == ((1, "A"), (2, "B"))
    assert result.truncated is True
    assert engine.rolled_back is True


def test_execute_read_rejects_non_positive_limits() -> None:
    adapter = make_adapter()
    adapter.connect()
    with pytest.raises(AdapterError):
        adapter.execute_read("SELECT 1", timeout_seconds=0, row_limit=10)
    with pytest.raises(AdapterError):
        adapter.execute_read("SELECT 1", timeout_seconds=10, row_limit=0)
