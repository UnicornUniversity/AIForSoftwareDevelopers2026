from __future__ import annotations

from typing import Any

import pytest
from _db_probe import attempt_rejected_write


def test_rejected_write_is_attempted_exactly_once() -> None:
    calls: list[str] = []

    def execute(sql: str) -> Any:
        calls.append(sql)
        raise RuntimeError("permission denied")

    message = attempt_rejected_write(execute, "INSERT INTO dbo.Probe VALUES (1)")

    assert calls == ["INSERT INTO dbo.Probe VALUES (1)"]
    assert "rejected by the database credential" in message
    assert "no retry was attempted" in message
    assert "INSERT INTO" not in message


def test_unexpected_write_success_is_a_failure() -> None:
    with pytest.raises(AssertionError, match="unexpectedly succeeded"):
        attempt_rejected_write(lambda sql: None, "INSERT INTO dbo.Probe VALUES (1)")


def test_secret_is_never_echoed() -> None:
    def execute(sql: str) -> Any:
        raise RuntimeError("denied; connection string contains super-secret")

    message = attempt_rejected_write(
        execute, "INSERT INTO dbo.Probe VALUES (1)", secret="super-secret"
    )
    assert "super-secret" not in message
    assert "connection string" not in message
