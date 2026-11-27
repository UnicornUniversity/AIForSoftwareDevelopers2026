"""Test-only compatibility helpers for the opt-in read-only credential probe.

The verification implementation now lives in ``uda.adapters.readonly`` so the same safe
logic can power the CLI diagnostic. This module keeps the integration-test constants and
re-exports for the existing suite. The production adapter still has no write capability.
"""

from __future__ import annotations

from uda.adapters.readonly import (
    attempt_rejected_write,
    granted_write_permissions,
    select_probe_table,
    verify_read_only,
)

WRITE_PROBE_SQL = (
    "INSERT INTO dbo.Region (RegionID, RegionDescription) "
    "VALUES (9999, N'uda-write-probe')"
)

__all__ = [
    "WRITE_PROBE_SQL",
    "attempt_rejected_write",
    "granted_write_permissions",
    "select_probe_table",
    "verify_read_only",
]
