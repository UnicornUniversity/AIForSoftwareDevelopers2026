"""Structured logging for console and rotating file output.

Log calls may attach arbitrary context with ``extra={"context": {...}}``; the
formatter renders it as ``key=value`` pairs so a log line stays greppable in a
classroom when something goes wrong mid-demonstration.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .config import logs_dir

__all__ = ["ContextFormatter", "configure_logging", "get_log_file"]

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_CONFIGURED = False
_HANDLER_ATTR = "_drone_vision_lab_handler"


def get_log_file() -> Path:
    return logs_dir() / "drone-vision-lab.log"


class ContextFormatter(logging.Formatter):
    """Appends ``extra={"context": {...}}`` fields to the message."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = getattr(record, "context", None)
        if context:
            rendered = " ".join(f"{key}={value!r}" for key, value in sorted(context.items()))
            return f"{base} | {rendered}"
        return base


def _is_ours(handler: logging.Handler) -> bool:
    return getattr(handler, _HANDLER_ATTR, False)


def _resolve_level(level: int | None) -> int:
    """Use the explicit level, else ``DRONE_VISION_LAB_LOG_LEVEL``, else INFO."""
    if level is not None:
        return level
    raw = os.environ.get("DRONE_VISION_LAB_LOG_LEVEL", "").strip()
    if not raw:
        return logging.INFO
    if raw.isdigit():
        return int(raw)
    named = getattr(logging, raw.upper(), None)
    return named if isinstance(named, int) else logging.INFO


def configure_logging(level: int | None = None, log_dir: Path | None = None) -> Path:
    """Install console and rotating file handlers once, and return the log path.

    Calling this twice does not duplicate handlers; it only adjusts levels.
    ``DRONE_VISION_LAB_LOG_LEVEL`` (``DEBUG``, ``INFO``, …) selects the level
    when the caller passes none.
    """
    global _CONFIGURED
    level = _resolve_level(level)
    target_dir = log_dir or logs_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / "drone-vision-lab.log"

    root = logging.getLogger()
    root.setLevel(level)

    if _CONFIGURED:
        for handler in root.handlers:
            if _is_ours(handler):
                handler.setLevel(level)
        return log_path

    formatter = ContextFormatter(_LOG_FORMAT)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    setattr(console, _HANDLER_ATTR, True)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_ATTR, True)
    root.addHandler(file_handler)

    _CONFIGURED = True
    logging.getLogger(__name__).debug(
        "Logging configured", extra={"context": {"log_file": str(log_path)}}
    )
    return log_path
