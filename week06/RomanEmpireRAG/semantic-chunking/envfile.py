"""Minimal .env reader (standard library).

The repository convention is a committed ``.env.example`` and a gitignored
``.env``. Python has no built-in loader and this project does not want a
``python-dotenv`` dependency just to read four optional variables, so the format
we use is parsed here: ``KEY=VALUE`` lines, ``#`` comments, optional single or
double quotes around the value. Existing environment variables win unless
``override`` is set.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path | str | None = None, override: bool = False) -> dict[str, str]:
    path = Path(path) if path else DEFAULT_PATH
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not key:
            continue
        values[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
