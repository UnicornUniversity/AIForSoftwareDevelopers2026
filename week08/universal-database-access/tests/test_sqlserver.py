from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from uda.schema import UnknownTableError
from uda.sqlserver import (
    SqlServerConfigurationError,
    SqlServerInspectionError,
    SqlServerSchemaProvider,
    connection_url_from_env,
    engine_from_env,
    parse_table_reference,
    table_schema_from_columns,
    table_schema_from_inspector,
)

DB_ENV = {
    "UDA_DB_SERVER": "localhost",
    "UDA_DB_DATABASE": "demo",
    "UDA_DB_USER": "reader",
    "UDA_DB_PASSWORD": "test-password",
}
OPTIONAL_DB_ENV = (
    "UDA_DB_DRIVER",
    "UDA_DB_ENCRYPT",
    "UDA_DB_TRUST_SERVER_CERTIFICATE",
)


def _set_db_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name in [*DB_ENV, *OPTIONAL_DB_ENV]:
        monkeypatch.delenv(name, raising=False)
    for name, value in {**DB_ENV, **overrides}.items():
        monkeypatch.setenv(name, value)


def _connection_string(url: str) -> str:
    return parse_qs(urlparse(url).query)["odbc_connect"][0]


class _Type:
    def __str__(self) -> str:
        return "NVARCHAR(50)"


class _Inspector:
    def __init__(self, columns: list[dict[str, Any]]) -> None:
        self._columns = columns
        self.calls: list[tuple[str | None, str]] = []

    def get_columns(
        self, table_name: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((schema, table_name))
        return self._columns


class _BrokenInspector:
    def get_columns(
        self, table_name: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        raise RuntimeError("server=secret-host;password=hidden")


class _PkInspector(_Inspector):
    def __init__(
        self,
        columns: list[dict[str, Any]],
        primary_keys: list[str],
    ) -> None:
        super().__init__(columns)
        self._primary_keys = primary_keys

    def get_pk_constraint(
        self, table_name: str, schema: str | None = None
    ) -> dict[str, Any]:
        return {
            "constrained_columns": self._primary_keys,
            "name": "PK_test",
        }


class _PkBrokenInspector(_Inspector):
    def get_pk_constraint(
        self, table_name: str, schema: str | None = None
    ) -> dict[str, Any]:
        raise RuntimeError("primary-key metadata unavailable")


class NoSuchTableError(Exception):
    """Named to match SQLAlchemy's exception across the optional dependency."""


class _MissingInspector:
    def get_columns(
        self, table_name: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        raise NoSuchTableError("missing table")


def test_columns_map_to_table_schema() -> None:
    schema = table_schema_from_columns(
        "dbo",
        "Customer",
        [
            {"name": "customer_id", "type": "int", "nullable": False},
            {"name": "full_name", "type": _Type()},
        ],
    )

    assert schema.qualified_name == "dbo.Customer"
    assert schema.columns[0].name == "customer_id"
    assert schema.columns[0].data_type == "int"
    assert schema.columns[0].nullable is False
    assert schema.columns[1].data_type == "NVARCHAR(50)"
    assert schema.columns[1].nullable is True


def test_empty_columns_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one column"):
        table_schema_from_columns("dbo", "Empty", [])


def test_inspector_is_called_with_schema_and_table() -> None:
    inspector = _Inspector([{"name": "id", "type": "int", "nullable": False}])

    schema = table_schema_from_inspector(inspector, "Customer", "sales")

    assert schema.qualified_name == "sales.Customer"
    assert inspector.calls == [("sales", "Customer")]


def test_inspection_error_does_not_leak_exception_text() -> None:
    with pytest.raises(SqlServerInspectionError) as caught:
        table_schema_from_inspector(_BrokenInspector(), "Customer")

    message = str(caught.value)
    assert "dbo.Customer" in message
    assert "RuntimeError" in message
    assert "secret-host" not in message
    assert "hidden" not in message


def test_parse_table_reference_defaults_to_dbo() -> None:
    assert parse_table_reference("Customer") == ("dbo", "Customer")
    assert parse_table_reference("sales.Orders") == ("sales", "Orders")


def test_parse_table_reference_rejects_empty_parts() -> None:
    with pytest.raises(SqlServerConfigurationError, match="invalid table reference"):
        parse_table_reference(".Customer")


def test_connection_url_uses_components_and_defaults(monkeypatch) -> None:
    _set_db_env(monkeypatch)

    url = connection_url_from_env()
    connection = _connection_string(url)

    assert url.startswith("mssql+pyodbc:///?odbc_connect=")
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in connection
    assert "SERVER={localhost}" in connection
    assert "DATABASE={demo}" in connection
    assert "UID={reader}" in connection
    assert "PWD={test-password}" in connection
    assert "Encrypt=yes" in connection
    assert "TrustServerCertificate=yes" in connection


def test_connection_url_escapes_password_delimiters(monkeypatch) -> None:
    _set_db_env(monkeypatch, UDA_DB_PASSWORD="pa;ss}word")

    connection = _connection_string(connection_url_from_env())

    assert "PWD={pa;ss}}word}" in connection


def test_connection_url_honours_overrides(monkeypatch) -> None:
    _set_db_env(
        monkeypatch,
        UDA_DB_SERVER=r"localhost\SQLEXPRESS",
        UDA_DB_DRIVER="ODBC Driver 17 for SQL Server",
        UDA_DB_ENCRYPT="no",
        UDA_DB_TRUST_SERVER_CERTIFICATE="no",
    )

    connection = _connection_string(connection_url_from_env())

    assert r"SERVER={localhost\SQLEXPRESS}" in connection
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in connection
    assert "Encrypt=no" in connection
    assert "TrustServerCertificate=no" in connection


def test_password_whitespace_is_preserved(monkeypatch) -> None:
    _set_db_env(monkeypatch, UDA_DB_PASSWORD=" pass ")

    connection = _connection_string(connection_url_from_env())

    assert "PWD={ pass }" in connection


@pytest.mark.parametrize(
    "missing",
    ["UDA_DB_SERVER", "UDA_DB_DATABASE", "UDA_DB_USER", "UDA_DB_PASSWORD"],
)
def test_missing_component_is_reported(monkeypatch, missing: str) -> None:
    _set_db_env(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(SqlServerConfigurationError, match=missing):
        connection_url_from_env()


def test_engine_requires_environment_settings(monkeypatch) -> None:
    for name in [*DB_ENV, *OPTIONAL_DB_ENV]:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SqlServerConfigurationError, match="UDA_DB_SERVER"):
        engine_from_env()


def test_primary_key_columns_are_flagged_case_insensitively() -> None:
    schema = table_schema_from_columns(
        "dbo",
        "Customer",
        [
            {"name": "customer_id", "type": "int", "nullable": False},
            {"name": "email", "type": "nvarchar(320)", "nullable": True},
        ],
        primary_key_columns=["CUSTOMER_ID"],
    )

    assert schema.columns[0].is_primary_key is True
    assert schema.columns[1].is_primary_key is False


def test_primary_key_is_unknown_without_metadata() -> None:
    schema = table_schema_from_columns(
        "dbo",
        "Customer",
        [{"name": "customer_id", "type": "int", "nullable": False}],
    )

    assert schema.columns[0].is_primary_key is None


def test_inspector_primary_key_metadata_is_used() -> None:
    inspector = _PkInspector(
        [
            {"name": "customer_id", "type": "int", "nullable": False},
            {"name": "email", "type": "nvarchar(320)", "nullable": True},
        ],
        ["customer_id"],
    )

    schema = table_schema_from_inspector(inspector, "Customer")

    assert [column.is_primary_key for column in schema.columns] == [True, False]


def test_primary_key_failure_is_non_fatal() -> None:
    inspector = _PkBrokenInspector(
        [{"name": "customer_id", "type": "int", "nullable": False}]
    )

    schema = table_schema_from_inspector(inspector, "Customer")

    assert schema.columns[0].is_primary_key is None


def test_sqlserver_provider_uses_injected_inspector() -> None:
    inspector = _PkInspector(
        [{"name": "customer_id", "type": "int", "nullable": False}],
        ["customer_id"],
    )

    schema = SqlServerSchemaProvider(inspector=inspector).load("dbo.Customer")

    assert schema.qualified_name == "dbo.Customer"
    assert schema.columns[0].is_primary_key is True


def test_missing_sqlserver_table_maps_to_unknown_table_error() -> None:
    provider = SqlServerSchemaProvider(inspector=_MissingInspector())

    with pytest.raises(UnknownTableError, match="dbo.Missing"):
        provider.load("dbo.Missing")
