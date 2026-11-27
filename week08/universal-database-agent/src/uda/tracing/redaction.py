"""Deny-by-default trace sanitization.

Only explicitly allowlisted attributes are submitted. Values that look like credentials,
connection strings, or obvious email addresses are redacted, and long free-text values are
truncated.

``result_ref`` is an opaque synthetic identifier, not arbitrary user-provided text. The
filters here are heuristic and cannot guarantee detection of every personal or confidential
value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

ALLOWED_TRACE_ATTRIBUTES = frozenset(
    {
        "answer_present",
        "column_count",
        "error_class",
        "input_tokens",
        "latency_ms",
        "max_tokens",
        "model",
        "node",
        "output_tokens",
        "prompt_version",
        "provider",
        "question_length",
        "result_ref",
        "retry_count",
        "row_count",
        "run_id",
        "score",
        "session_id",
        "statement_class",
        "temperature",
        "total_tokens",
        "trace_id",
        "transition",
        "truncated",
        "validation_outcome",
    }
)

_SENSITIVE_KEY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "bearer_token",
        "connection_string",
        "credential",
        "credentials",
        "dsn",
        "id_token",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "token",
    }
)

_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_credential",
    "_password",
    "_secret",
    "_token",
)

_SENSITIVE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)(password|pwd)\s*=\s*[^;\s]+"),
    re.compile(r"(?i)server\s*=.*;"),
    re.compile(r"(?i)(postgres(ql)?|mysql|mssql\+pyodbc)://\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

_MAX_VALUE_LENGTH = 500
_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def sanitize_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Return only allowlisted, non-sensitive, scalar attributes."""

    sanitized: dict[str, Any] = {}
    for key, value in attributes.items():
        if key not in ALLOWED_TRACE_ATTRIBUTES:
            continue
        if _is_sensitive_key(key):
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            sanitized[key] = cleaned
    return sanitized


def _clean_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.search(value):
                return _REDACTED
        if len(value) > _MAX_VALUE_LENGTH:
            return value[:_MAX_VALUE_LENGTH] + "...[truncated]"
        return value
    return None
