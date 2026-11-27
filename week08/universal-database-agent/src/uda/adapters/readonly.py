"""Non-mutating read-only credential verification.

The verifier performs a permitted read, evaluates effective write permissions with
``HAS_PERMS_BY_NAME``, and fails before any write when write permission is detected. An
optional single write probe is attempted only after the permission check proves the write
is denied; it runs inside an uncommitted transaction, is rolled back, and is never retried.
Production callers do not supply a write probe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text

ReadOnlyStatus = Literal[
    "verified_read_only",
    "failed_not_read_only",
    "not_performed",
    "unavailable",
]

_PROBE_TABLE_SQL = """
    SELECT TOP (1)
        QUOTENAME(SCHEMA_NAME(t.schema_id)) + '.' + QUOTENAME(t.name)
    FROM sys.tables AS t
    WHERE t.is_ms_shipped = 0
    ORDER BY t.schema_id, t.name
"""

_PERMISSION_SQL = """
    SELECT
        COALESCE(HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE'), -1)
            AS create_table,
        COALESCE(HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'ALTER ANY SCHEMA'), -1)
            AS alter_any_schema,
        COALESCE(HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL'), -1)
            AS database_control,
        COALESCE(HAS_PERMS_BY_NAME(:table_name, 'OBJECT', 'INSERT'), -1)
            AS object_insert,
        COALESCE(HAS_PERMS_BY_NAME(:table_name, 'OBJECT', 'UPDATE'), -1)
            AS object_update,
        COALESCE(HAS_PERMS_BY_NAME(:table_name, 'OBJECT', 'DELETE'), -1)
            AS object_delete,
        COALESCE(HAS_PERMS_BY_NAME(:table_name, 'OBJECT', 'ALTER'), -1)
            AS object_alter,
        COALESCE(HAS_PERMS_BY_NAME(:table_name, 'OBJECT', 'CONTROL'), -1)
            AS object_control
"""


@dataclass(frozen=True)
class ReadOnlyVerification:
    status: ReadOnlyStatus
    detail: str
    granted_permissions: tuple[str, ...] = ()
    write_probe_attempted: bool = False
    write_probe_rejected: bool = False


def select_probe_table(connection: Any) -> str | None:
    """Return one user-table securable for an object-level permission check."""

    value = connection.execute(text(_PROBE_TABLE_SQL)).scalar()
    return str(value) if value else None


def granted_write_permissions(
    connection: Any, *, table_name: str = "dbo.Region"
) -> tuple[str, ...]:
    """Return granted write permissions; NULL means unknown and is treated as granted."""

    row = connection.execute(
        text(_PERMISSION_SQL), {"table_name": table_name}
    ).mappings().one()
    return tuple(name for name, value in row.items() if int(value) != 0)


def attempt_rejected_write(
    execute: Callable[[str], Any], sql: str, *, secret: str = ""
) -> str:
    """Execute one write probe, expecting rejection; never retry and never echo secrets."""

    try:
        execute(sql)
    except Exception as exc:
        message = (
            "Write attempt rejected by the database credential "
            f"({type(exc).__name__}); no retry was attempted."
        )
        if secret and secret in message:
            return (
                "Write attempt rejected by the database credential; "
                "no retry was attempted."
            )
        return message
    raise AssertionError(
        "The write probe unexpectedly succeeded. The transaction must be rolled back; "
        "write rejection is NOT VERIFIED."
    )


def verify_read_only(
    connection: Any,
    *,
    table_name: str | None = None,
    write_probe_sql: str | None = None,
    secret: str = "",
) -> ReadOnlyVerification:
    """Classify the effective permission set of a database connection.

    A write probe is attempted at most once, only after the non-mutating permission check
    shows that the write is denied. The caller must supply a transaction-capable
    SQLAlchemy connection.
    """

    try:
        connection.execute(text("SELECT 1")).scalar()
    except Exception as exc:
        return ReadOnlyVerification(
            status="unavailable",
            detail=f"Permitted read check failed ({type(exc).__name__}).",
        )

    if table_name is None:
        try:
            table_name = select_probe_table(connection)
        except Exception as exc:
            return ReadOnlyVerification(
                status="unavailable",
                detail=f"Probe-table selection failed ({type(exc).__name__}).",
            )
    if table_name is None:
        return ReadOnlyVerification(
            status="not_performed",
            detail="No user table is available for an object-level permission probe.",
        )

    try:
        granted = granted_write_permissions(connection, table_name=table_name)
    except Exception as exc:
        return ReadOnlyVerification(
            status="unavailable",
            detail=f"Effective-permission probe failed ({type(exc).__name__}).",
        )
    if granted:
        return ReadOnlyVerification(
            status="failed_not_read_only",
            detail=(
                "The configured login has write permissions on "
                f"{table_name}: {', '.join(granted)}. No write was attempted."
            ),
            granted_permissions=granted,
        )

    if write_probe_sql is None:
        return ReadOnlyVerification(
            status="verified_read_only",
            detail=(
                "The effective-permission probe found no write permission on "
                f"{table_name}; no write probe was requested."
            ),
        )

    try:
        connection.rollback()
        transaction = connection.begin()
    except Exception as exc:
        return ReadOnlyVerification(
            status="unavailable",
            detail=f"Could not open the write-probe transaction ({type(exc).__name__}).",
        )
    try:
        try:
            connection.execute(text(write_probe_sql))
        except Exception as exc:
            return ReadOnlyVerification(
                status="verified_read_only",
                detail=(
                    "No write permission was detected, and the single write probe was "
                    f"rejected ({type(exc).__name__}); it was not retried."
                ),
                write_probe_attempted=True,
                write_probe_rejected=True,
            )
        return ReadOnlyVerification(
            status="failed_not_read_only",
            detail=(
                "The write probe unexpectedly succeeded and was rolled back. "
                "Write rejection is NOT VERIFIED."
            ),
            write_probe_attempted=True,
            write_probe_rejected=False,
        )
    finally:
        try:
            transaction.rollback()
        except Exception:
            pass
