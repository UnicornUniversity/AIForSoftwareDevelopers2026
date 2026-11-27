"""Deterministic JSON serialization and hashing for repository artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON with stable key order, indentation, and a trailing newline."""

    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
