"""Optional read-only SQL Server metadata inspection.

The pure mappers are offline-testable. The inspector wrapper uses SQLAlchemy's
``Inspector``, which issues catalog queries only; this module never builds or
executes user-supplied SQL. Use a read-only database login.
"""

import os
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote_plus

from uda.models import Column, TableSchema
from uda.schema import UnknownTableError

DEFAULT_SCHEMA = "dbo"
DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"
DEFAULT_ENCRYPT = "yes"
DEFAULT_TRUST_SERVER_CERTIFICATE = "yes"


class SqlServerError(RuntimeError):
    """Base error for optional SQL Server metadata inspection."""


class SqlServerConfigurationError(SqlServerError):
    """Raised when inspection is not configured or cannot start."""


class SqlServerInspectionError(SqlServerError):
    """Raised when catalog metadata cannot be read."""


def table_schema_from_columns(
    schema_name: str,
    table_name: str,
    columns: Iterable[Mapping[str, Any]],
    primary_key_columns: Iterable[str] | None = None,
) -> TableSchema:
    """Map SQLAlchemy-style column mappings to a ``TableSchema``.

    Each mapping provides ``name``, ``type``, and optionally ``nullable``.
    A missing or ``None`` nullability is treated as nullable. Primary-key names
    are matched case-insensitively; ``None`` means the flag is unknown.
    """
    primary_keys = (
        None
        if primary_key_columns is None
        else {name.casefold() for name in primary_key_columns}
    )
    mapped = tuple(
        Column(
            name=str(entry["name"]),
            sql_type=str(entry["type"]),
            nullable=entry.get("nullable") is not False,
            is_primary_key=(
                None
                if primary_keys is None
                else str(entry["name"]).casefold() in primary_keys
            ),
        )
        for entry in columns
    )
    return TableSchema(schema_name=schema_name, table_name=table_name, columns=mapped)


def _primary_key_columns(
    inspector: Any,
    table_name: str,
    schema_name: str,
) -> tuple[str, ...] | None:
    """Return primary-key column names, or ``None`` when metadata is unavailable."""
    getter = getattr(inspector, "get_pk_constraint", None)
    if getter is None:
        return None

    try:
        constraint = getter(table_name, schema=schema_name)
    except Exception:
        return None

    if not isinstance(constraint, Mapping):
        return None
    columns = constraint.get("constrained_columns")
    if columns is None:
        return None
    return tuple(str(name) for name in columns)


def table_schema_from_inspector(
    inspector: Any,
    table_name: str,
    schema_name: str = DEFAULT_SCHEMA,
) -> TableSchema:
    """Read one table from an object exposing SQLAlchemy's inspector API."""
    try:
        columns = inspector.get_columns(table_name, schema=schema_name)
    except Exception as exc:
        if exc.__class__.__name__ == "NoSuchTableError":
            raise UnknownTableError(
                f"table {schema_name}.{table_name} was not found"
            ) from exc
        # Exception text can contain connection details, so only the class is shown.
        raise SqlServerInspectionError(
            f"could not read metadata for {schema_name}.{table_name} "
            f"({exc.__class__.__name__})"
        ) from exc

    primary_key_columns = _primary_key_columns(inspector, table_name, schema_name)
    return table_schema_from_columns(
        schema_name,
        table_name,
        columns,
        primary_key_columns,
    )


def inspect_table(
    engine: Any,
    table_name: str,
    schema_name: str = DEFAULT_SCHEMA,
) -> TableSchema:
    """Inspect one SQL Server table through SQLAlchemy (metadata only)."""
    try:
        from sqlalchemy import inspect
    except ImportError as exc:
        raise SqlServerConfigurationError(
            "SQLAlchemy is not installed; run `uv sync --extra sqlserver`"
        ) from exc

    return table_schema_from_inspector(inspect(engine), table_name, schema_name)


def _required(name: str, *, strip: bool = True) -> str:
    raw = os.environ.get(name, "")
    value = raw.strip() if strip else raw
    if not value.strip():
        raise SqlServerConfigurationError(
            f"{name} is not set; fill the SQL Server settings in .env or use "
            "the demo fixture"
        )
    return value


def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def connection_url_from_env() -> str:
    """Build an SQLAlchemy URL from the ``UDA_DB_*`` environment variables.

    The URL embeds the password for the SQLAlchemy/pyodbc handshake. It is never
    logged or included in errors.
    """
    server = _required("UDA_DB_SERVER")
    database = _required("UDA_DB_DATABASE")
    user = _required("UDA_DB_USER")
    password = _required("UDA_DB_PASSWORD", strip=False)

    driver = os.environ.get("UDA_DB_DRIVER", "").strip() or DEFAULT_DRIVER
    encrypt = os.environ.get("UDA_DB_ENCRYPT", "").strip() or DEFAULT_ENCRYPT
    trust = (
        os.environ.get("UDA_DB_TRUST_SERVER_CERTIFICATE", "").strip()
        or DEFAULT_TRUST_SERVER_CERTIFICATE
    )

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={_odbc_value(server)}",
        f"DATABASE={_odbc_value(database)}",
        f"UID={_odbc_value(user)}",
        f"PWD={_odbc_value(password)}",
        f"Encrypt={encrypt}",
        f"TrustServerCertificate={trust}",
    ]
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(";".join(parts))


def engine_from_env() -> Any:
    """Create a SQLAlchemy engine from the ``UDA_DB_*`` settings."""
    url = connection_url_from_env()

    try:
        from sqlalchemy import create_engine
    except ImportError as exc:
        raise SqlServerConfigurationError(
            "SQLAlchemy is not installed; run `uv sync --extra sqlserver`"
        ) from exc

    try:
        return create_engine(url)
    except Exception as exc:
        raise SqlServerConfigurationError(
            f"could not create a SQL Server engine ({exc.__class__.__name__})"
        ) from exc


def parse_table_reference(reference: str) -> tuple[str, str]:
    """Split ``table`` or ``schema.table`` into ``(schema, table)``."""
    schema_name, separator, table_name = reference.partition(".")
    if not separator:
        schema_name, table_name = DEFAULT_SCHEMA, reference

    schema_name = schema_name.strip()
    table_name = table_name.strip()
    if not schema_name or not table_name:
        raise SqlServerConfigurationError(
            f"invalid table reference {reference!r}; expected table or schema.table"
        )
    return schema_name, table_name


class SqlServerSchemaProvider:
    """Schema provider backed by read-only SQL Server catalog inspection."""

    def __init__(self, inspector: Any | None = None) -> None:
        self._inspector = inspector

    def load(self, table_name: str) -> TableSchema:
        schema_name, name = parse_table_reference(table_name)
        inspector = self._inspector

        if inspector is None:
            try:
                from sqlalchemy import inspect
            except ImportError as exc:
                raise SqlServerConfigurationError(
                    "SQLAlchemy is not installed; run `uv sync --extra sqlserver`"
                ) from exc

            inspector = inspect(engine_from_env())

        return table_schema_from_inspector(inspector, name, schema_name)
