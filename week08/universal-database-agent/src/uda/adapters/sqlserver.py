"""SQL Server adapter: connectivity, schema introspection, and bounded reads.

Metadata extraction is Phase 2 scope. ``execute_read`` is the Phase 7 execution boundary:
it enforces a statement timeout and a row cap, never retries, and relies on the read-only
credential as the independent write backstop.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import unquote

import pyodbc
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.inspection import inspect as sa_inspect

from ..config import DatabaseConfig
from ..errors import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterError,
    AdapterMetadataError,
    AdapterPermissionError,
    UnsupportedCapabilityError,
)
from ..metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    ForeignKeyMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
    make_physical_id,
)
from ..metadata.normalizer import (
    column_metadata,
    dedupe_indexes,
    foreign_key_metadata,
    index_metadata,
    primary_key_metadata,
)
from .base import ColumnInfo, ObjectInfo, ReadResult

_SYSTEM_SCHEMAS = frozenset({"sys", "information_schema"})


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def available_drivers() -> tuple[str, ...]:
    return tuple(pyodbc.drivers())


def ensure_driver_available(
    driver: str, drivers: Sequence[str] | None = None
) -> None:
    installed = tuple(drivers) if drivers is not None else available_drivers()
    if driver not in installed:
        listing = ", ".join(installed) if installed else "none detected"
        raise AdapterConfigurationError(
            f"ODBC driver '{driver}' is not installed. Available drivers: {listing}."
        )


def build_connection_url(config: DatabaseConfig) -> URL:
    """Build a SQLAlchemy URL without ever rendering the password in diagnostics."""

    config.validate_connection_settings()
    query = {
        "driver": config.driver,
        "Encrypt": _yes_no(config.encrypt),
        "TrustServerCertificate": _yes_no(config.trust_server_certificate),
    }
    if config.trusted_connection:
        query["Trusted_Connection"] = "yes"
        return URL.create(
            "mssql+pyodbc",
            host=config.host,
            port=config.port,
            database=config.name,
            query=query,
        )
    return URL.create(
        "mssql+pyodbc",
        username=config.username,
        password=config.password,
        host=config.host,
        port=config.port,
        database=config.name,
        query=query,
    )


def split_physical_id(physical_id: str) -> tuple[str, str, str, str, str]:
    """Split a table/view Physical ID into platform, database, schema, type, name."""

    parts = physical_id.split("/")
    if len(parts) != 5:
        raise AdapterError(f"Invalid physical identifier: {physical_id}")
    platform, database, schema, object_type, name = (unquote(part) for part in parts)
    if platform != "sqlserver":
        raise AdapterError("Physical identifier does not belong to a SQL Server adapter.")
    if object_type not in {"table", "view"}:
        raise AdapterError(f"Unsupported object type in physical identifier: {object_type}")
    return platform, database, schema, object_type, name


class SqlServerAdapter:
    """SQLAlchemy-backed SQL Server adapter for connectivity and introspection."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        engine_factory: Callable[[URL], Engine] | None = None,
        inspector_factory: Callable[[Engine], Any] | None = None,
        driver_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self._config = config
        self._engine: Engine | None = None
        self._connected = False
        self._engine_factory = engine_factory
        self._inspector_factory = inspector_factory or sa_inspect
        self._driver_provider = driver_provider or available_drivers

    @property
    def dialect(self) -> str:
        return "tsql"

    def connect(self) -> None:
        if self._connected:
            return
        self._config.validate_connection_settings()
        ensure_driver_available(self._config.driver, self._driver_provider())
        url = build_connection_url(self._config)
        engine: Engine | None = None
        try:
            if self._engine_factory is not None:
                engine = self._engine_factory(url)
            else:
                engine = create_engine(
                    url,
                    pool_pre_ping=True,
                    connect_args={"timeout": self._config.connection_timeout_seconds},
                )
            if hasattr(engine, "dispatch"):
                self._apply_query_timeout(engine)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            if engine is not None:
                engine.dispose()
            raise _connection_error(exc) from exc
        self._engine = engine
        self._connected = True

    def _apply_query_timeout(self, engine: Engine) -> None:
        seconds = self._config.query_timeout_seconds

        def _before_cursor_execute(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            dbapi_connection = getattr(cursor, "connection", None)
            if dbapi_connection is not None and hasattr(dbapi_connection, "timeout"):
                dbapi_connection.timeout = seconds

        event.listen(engine, "before_cursor_execute", _before_cursor_execute)

    def _require_engine(self) -> Engine:
        if not self._connected or self._engine is None:
            raise AdapterError("Adapter is not connected.")
        return self._engine

    def _inspector(self, engine: Engine) -> Any:
        return self._inspector_factory(engine)

    def list_schemas(self) -> Sequence[str]:
        engine = self._require_engine()
        try:
            return tuple(sorted(self._inspector(engine).get_schema_names()))
        except SQLAlchemyError as exc:
            raise _metadata_error("list schemas", exc) from exc

    def list_objects(self, schema: str | None = None) -> Sequence[ObjectInfo]:
        engine = self._require_engine()
        schemas = (schema,) if schema is not None else self.list_schemas()
        inspector = self._inspector(engine)
        objects: list[ObjectInfo] = []
        try:
            for schema_name in schemas:
                for object_type, names in (
                    ("table", inspector.get_table_names(schema=schema_name)),
                    ("view", inspector.get_view_names(schema=schema_name)),
                ):
                    for name in names:
                        objects.append(
                            ObjectInfo(
                                physical_id=make_physical_id(
                                    "sqlserver",
                                    self._config.name,
                                    schema_name,
                                    object_type,
                                    name,
                                ),
                                schema=schema_name,
                                name=name,
                                object_type=object_type,
                            )
                        )
        except SQLAlchemyError as exc:
            raise _metadata_error("list objects", exc) from exc
        return tuple(sorted(objects, key=lambda item: (item.schema, item.object_type, item.name)))

    def describe_object(self, physical_id: str) -> Sequence[ColumnInfo]:
        engine = self._require_engine()
        platform, database, schema, _object_type, name = split_physical_id(physical_id)
        if platform != "sqlserver" or database != self._config.name:
            raise AdapterError("Physical identifier does not match the selected database.")
        try:
            rows = self._inspector(engine).get_columns(name, schema=schema)
        except SQLAlchemyError as exc:
            raise _metadata_error(f"describe object {physical_id}", exc) from exc
        return tuple(
            ColumnInfo(
                name=str(item.get("name", "")),
                ordinal=index + 1,
                data_type=str(item.get("type", "")),
                nullable=bool(item.get("nullable", True)),
                default=str(item["default"]) if item.get("default") is not None else None,
                is_identity=bool(item.get("autoincrement", False)),
            )
            for index, item in enumerate(rows)
        )

    def extract_ddl(self, physical_id: str) -> str:
        raise UnsupportedCapabilityError(
            "Original DDL extraction is not implemented in Phase 2. It requires an approved "
            "SMO or equivalent DDL-extraction decision."
        )

    def execute_read(self, sql: str, *, timeout_seconds: int, row_limit: int) -> ReadResult:
        """Execute one validated statement within a timeout and row cap.

        The caller is responsible for parse-level validation. This method adds independent
        execution controls: the login is read-only, the statement has a timeout, results are
        capped, and a failed execution is never retried.
        """

        engine = self._require_engine()
        if timeout_seconds <= 0:
            raise AdapterError("timeout_seconds must be positive.")
        if row_limit <= 0:
            raise AdapterError("row_limit must be positive.")
        try:
            with engine.connect() as connection:
                dbapi_connection = getattr(
                    getattr(connection, "connection", None), "dbapi_connection", None
                )
                if dbapi_connection is not None and hasattr(dbapi_connection, "timeout"):
                    dbapi_connection.timeout = int(timeout_seconds)
                result = connection.execute(text(sql))
                columns = tuple(str(key) for key in result.keys())
                fetched = result.fetchmany(row_limit + 1)
                connection.rollback()
        except SQLAlchemyError as exc:
            raise AdapterError(
                f"Read query failed ({type(exc).__name__}); no retry was attempted."
            ) from exc
        rows = tuple(tuple(row) for row in fetched[:row_limit])
        return ReadResult(
            columns=columns,
            rows=rows,
            truncated=len(fetched) > row_limit,
        )

    def introspect(self, schemas: Sequence[str] | None = None) -> DatabaseMetadata:
        engine = self._require_engine()
        inspector = self._inspector(engine)
        issues: list[ExtractionIssue] = []
        selected = tuple(schemas) if schemas is not None else self.list_schemas()

        descriptions, description_issues = self._fetch_descriptions(engine)
        issues.extend(description_issues)
        computed, computed_issues = self._fetch_computed_columns(engine)
        issues.extend(computed_issues)

        schema_models: list[SchemaMetadata] = []
        table_models: list[TableMetadata] = []
        for schema_name in selected:
            schema_models.append(
                SchemaMetadata(
                    physical_id=make_physical_id(
                        "sqlserver", self._config.name, "schema", schema_name
                    ),
                    name=schema_name,
                    is_system=schema_name.lower() in _SYSTEM_SCHEMAS,
                )
            )
            try:
                table_names = inspector.get_table_names(schema=schema_name)
                view_names = inspector.get_view_names(schema=schema_name)
            except SQLAlchemyError as exc:
                issues.append(_extraction_issue("unavailable", None, "list objects", exc))
                continue
            for object_type, names in (("table", table_names), ("view", view_names)):
                for name in names:
                    object_id = make_physical_id(
                        "sqlserver", self._config.name, schema_name, object_type, name
                    )
                    try:
                        table_models.append(
                            self._build_object(
                                inspector,
                                object_id,
                                schema_name,
                                str(name),
                                object_type,
                                descriptions,
                                computed,
                                issues,
                            )
                        )
                    except SQLAlchemyError as exc:
                        issues.append(
                            _extraction_issue(
                                "unavailable", object_id, "extract object metadata", exc
                            )
                        )

        return DatabaseMetadata(
            identity=DatabaseIdentity(platform="sqlserver", database=self._config.name),
            schemas=tuple(schema_models),
            objects=tuple(table_models),
            issues=tuple(issues),
        )

    def _build_object(
        self,
        inspector: Any,
        object_id: str,
        schema: str,
        name: str,
        object_type: str,
        descriptions: dict[tuple[str, str], str],
        computed: dict[tuple[str, str, str], str],
        issues: list[ExtractionIssue],
    ) -> TableMetadata:
        column_rows = inspector.get_columns(name, schema=schema)
        columns: list[ColumnMetadata] = []
        for ordinal, item in enumerate(column_rows, start=1):
            column = column_metadata(object_id, item, ordinal)
            expression = computed.get((schema, name, column.name))
            if expression is not None:
                column = column.model_copy(
                    update={"is_computed": True, "computed_expression": expression}
                )
            if column.normalized_type is None:
                issues.append(
                    ExtractionIssue(
                        kind="unsupported_type",
                        object_id=column.physical_id,
                        detail=f"Unmapped SQL Server type: {column.data_type}",
                    )
                )
            columns.append(column)

        primary_key = None
        foreign_keys: tuple[ForeignKeyMetadata, ...] = ()
        indexes: tuple[IndexMetadata, ...] = ()
        if object_type == "table":
            try:
                primary_key = primary_key_metadata(
                    object_id, inspector.get_pk_constraint(name, schema=schema)
                )
            except SQLAlchemyError as exc:
                issues.append(
                    _extraction_issue("unavailable", object_id, "read primary key", exc)
                )
            try:
                foreign_keys = tuple(
                    foreign_key_metadata(object_id, schema, item, index)
                    for index, item in enumerate(
                        inspector.get_foreign_keys(name, schema=schema)
                    )
                )
            except SQLAlchemyError as exc:
                issues.append(
                    _extraction_issue("unavailable", object_id, "read foreign keys", exc)
                )
            try:
                index_items = [
                    index_metadata(object_id, item)
                    for item in inspector.get_indexes(name, schema=schema)
                ]
                indexes = dedupe_indexes(index_items)
            except SQLAlchemyError as exc:
                issues.append(
                    _extraction_issue("unavailable", object_id, "read indexes", exc)
                )
            try:
                unique_items = [
                    index_metadata(object_id, item, source="unique_constraint")
                    for item in inspector.get_unique_constraints(name, schema=schema)
                ]
                indexes = dedupe_indexes([*indexes, *unique_items])
            except NotImplementedError:
                # The mssql Inspector does not implement unique constraints; inspect
                # unique indexes through get_indexes instead. Documented limitation.
                pass
            except SQLAlchemyError as exc:
                issues.append(
                    _extraction_issue(
                        "unavailable", object_id, "read unique constraints", exc
                    )
                )

        return TableMetadata(
            physical_id=object_id,
            schema_name=schema,
            name=name,
            object_type="table" if object_type == "table" else "view",
            columns=tuple(columns),
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            indexes=indexes,
            description=descriptions.get((schema, name)),
        )

    def _fetch_descriptions(
        self, engine: Engine
    ) -> tuple[dict[tuple[str, str], str], list[ExtractionIssue]]:
        sql = """
            SELECT s.name AS schema_name, o.name AS object_name,
                   CAST(ep.value AS nvarchar(4000)) AS description
            FROM sys.extended_properties ep
            JOIN sys.objects o ON ep.major_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE ep.minor_id = 0 AND ep.name = 'MS_Description'
        """
        try:
            with engine.connect() as connection:
                rows = connection.execute(text(sql)).all()
        except SQLAlchemyError as exc:
            return {}, [_extraction_issue("unavailable", None, "read descriptions", exc)]
        return {
            (str(row.schema_name), str(row.object_name)): str(row.description)
            for row in rows
            if row.description is not None
        }, []

    def _fetch_computed_columns(
        self, engine: Engine
    ) -> tuple[dict[tuple[str, str, str], str], list[ExtractionIssue]]:
        sql = """
            SELECT s.name AS schema_name, t.name AS table_name,
                   c.name AS column_name, cc.definition AS definition
            FROM sys.computed_columns cc
            JOIN sys.columns c
              ON cc.object_id = c.object_id AND cc.column_id = c.column_id
            JOIN sys.tables t ON cc.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
        """
        try:
            with engine.connect() as connection:
                rows = connection.execute(text(sql)).all()
        except SQLAlchemyError as exc:
            return {}, [_extraction_issue("unavailable", None, "read computed columns", exc)]
        return {
            (str(row.schema_name), str(row.table_name), str(row.column_name)): str(
                row.definition
            )
            for row in rows
            if row.definition is not None
        }, []

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._connected = False


def _connection_error(exc: Exception) -> AdapterError:
    message = str(exc).lower()
    if isinstance(exc, AdapterError):
        return exc
    if "18456" in message or "28000" in message or "login failed" in message:
        reason = "authentication failed"
    elif "4060" in message or "cannot open database" in message:
        reason = "database not found"
    elif "timed out" in message or "timeout expired" in message:
        reason = "connection timed out"
    elif "name or service" in message or "host" in message and "not found" in message:
        reason = "host could not be reached"
    else:
        reason = "connection failed"
    return AdapterConnectionError(
        f"Could not connect to SQL Server ({reason}). Check host, port, database, driver, "
        "encryption settings, and credentials."
    )


def _metadata_error(action: str, exc: SQLAlchemyError) -> AdapterError:
    message = str(exc).lower()
    if "permission" in message or "denied" in message or "authorization" in message:
        return AdapterPermissionError(
            f"Could not {action}; the login lacks the required metadata permission."
        )
    return AdapterMetadataError(
        f"Could not {action}; check database availability and metadata permissions."
    )


def _extraction_issue(
    kind: str, object_id: str | None, action: str, exc: Exception
) -> ExtractionIssue:
    message = str(exc).lower()
    issue_kind = (
        "permission"
        if "permission" in message or "denied" in message or "authorization" in message
        else kind
    )
    return ExtractionIssue(
        kind=issue_kind,  # type: ignore[arg-type]
        object_id=object_id,
        detail=f"{action} unavailable ({type(exc).__name__})",
    )
