"""Database adapter boundary."""

from .base import ColumnInfo, DatabaseAdapter, ObjectInfo, ReadResult
from .fake import FakeAdapter
from .sqlserver import SqlServerAdapter, build_connection_url, ensure_driver_available

__all__ = [
    "ColumnInfo",
    "DatabaseAdapter",
    "FakeAdapter",
    "ObjectInfo",
    "ReadResult",
    "SqlServerAdapter",
    "build_connection_url",
    "ensure_driver_available",
]
