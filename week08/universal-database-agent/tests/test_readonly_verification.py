from __future__ import annotations

from typing import Any

from uda.adapters.readonly import (
    select_probe_table,
    verify_read_only,
)

PERMISSIONS = {
    "create_table": 0,
    "alter_any_schema": 0,
    "database_control": 0,
    "object_insert": 0,
    "object_update": 0,
    "object_delete": 0,
    "object_alter": 0,
    "object_control": 0,
}


class FakeMappings:
    def __init__(self, row: dict[str, int]) -> None:
        self._row = row

    def one(self) -> dict[str, int]:
        return self._row


class FakeResult:
    def __init__(self, *, scalar: Any = None, row: dict[str, int] | None = None) -> None:
        self._scalar = scalar
        self._row = row

    def scalar(self) -> Any:
        return self._scalar

    def mappings(self) -> FakeMappings:
        return FakeMappings(self._row or {})


class FakeTransaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class FakeConnection:
    def __init__(
        self,
        *,
        permissions: dict[str, int] | None = None,
        probe_table: str | None = "[dbo].[Categories]",
        read_error: Exception | None = None,
        permission_error: Exception | None = None,
        write_denied: bool = True,
        write_error: Exception | None = None,
    ) -> None:
        self.permissions = dict(PERMISSIONS if permissions is None else permissions)
        self.probe_table = probe_table
        self.read_error = read_error
        self.permission_error = permission_error
        self.write_denied = write_denied
        self.write_error = write_error or RuntimeError("permission denied")
        self.executed: list[str] = []
        self.transaction: FakeTransaction | None = None

    def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.executed.append(sql)
        if "sys.tables" in sql:
            return FakeResult(scalar=self.probe_table)
        if "HAS_PERMS_BY_NAME" in sql:
            if self.permission_error is not None:
                raise self.permission_error
            return FakeResult(row=self.permissions)
        if sql.strip().upper().startswith("SELECT 1"):
            if self.read_error is not None:
                raise self.read_error
            return FakeResult(scalar=1)
        if self.write_denied:
            raise self.write_error
        return FakeResult()

    def rollback(self) -> None:
        return None

    def begin(self) -> FakeTransaction:
        self.transaction = FakeTransaction()
        return self.transaction


def test_verified_read_only_uses_permission_probe_only() -> None:
    connection = FakeConnection()
    verification = verify_read_only(connection)

    assert verification.status == "verified_read_only"
    assert verification.write_probe_attempted is False
    assert verification.granted_permissions == ()
    assert not any("INSERT INTO" in sql for sql in connection.executed)


def test_write_permission_fails_without_attempting_a_write() -> None:
    permissions = dict(PERMISSIONS, object_insert=1, database_control=1)
    connection = FakeConnection(permissions=permissions)
    verification = verify_read_only(
        connection, write_probe_sql="INSERT INTO dbo.Region VALUES (1)"
    )

    assert verification.status == "failed_not_read_only"
    assert "object_insert" in verification.granted_permissions
    assert "database_control" in verification.granted_permissions
    assert verification.write_probe_attempted is False
    assert not any("INSERT INTO" in sql for sql in connection.executed)


def test_single_write_probe_is_rejected_and_rolled_back() -> None:
    connection = FakeConnection()
    verification = verify_read_only(
        connection,
        table_name="[dbo].[Region]",
        write_probe_sql="INSERT INTO dbo.Region VALUES (9999)",
    )

    assert verification.status == "verified_read_only"
    assert verification.write_probe_attempted is True
    assert verification.write_probe_rejected is True
    probes = [sql for sql in connection.executed if "INSERT INTO" in sql]
    assert len(probes) == 1
    assert connection.transaction is not None
    assert connection.transaction.rolled_back is True


def test_unexpected_write_success_fails_and_rolls_back() -> None:
    connection = FakeConnection(write_denied=False)
    verification = verify_read_only(
        connection,
        table_name="[dbo].[Region]",
        write_probe_sql="INSERT INTO dbo.Region VALUES (9999)",
    )

    assert verification.status == "failed_not_read_only"
    assert verification.write_probe_attempted is True
    assert verification.write_probe_rejected is False
    assert connection.transaction is not None
    assert connection.transaction.rolled_back is True


def test_read_failure_is_unavailable() -> None:
    verification = verify_read_only(
        FakeConnection(read_error=RuntimeError("cannot read"))
    )
    assert verification.status == "unavailable"
    assert "Permitted read" in verification.detail


def test_permission_probe_failure_is_unavailable() -> None:
    verification = verify_read_only(
        FakeConnection(permission_error=RuntimeError("permission denied"))
    )
    assert verification.status == "unavailable"
    assert "Effective-permission probe failed" in verification.detail


def test_no_probe_table_is_not_performed() -> None:
    verification = verify_read_only(FakeConnection(probe_table=None))
    assert verification.status == "not_performed"
    assert "No user table" in verification.detail


def test_probe_table_is_selected_from_sys_tables() -> None:
    connection = FakeConnection(probe_table="[sales].[Orders]")
    assert select_probe_table(connection) == "[sales].[Orders]"


def test_write_error_secret_is_not_exposed() -> None:
    connection = FakeConnection(
        write_error=RuntimeError("denied for password super-secret")
    )
    verification = verify_read_only(
        connection,
        table_name="[dbo].[Region]",
        write_probe_sql="INSERT INTO dbo.Region VALUES (9999)",
        secret="super-secret",
    )
    assert "super-secret" not in verification.detail
