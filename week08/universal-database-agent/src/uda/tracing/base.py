"""Tracing abstraction. Core code depends only on this protocol."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol


class Tracer(Protocol):
    """Minimal tracing surface used by the application."""

    def span(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        """Open a span for a step or transition."""

    def generation(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        """Open a span representing an LLM generation."""

    def score(self, name: str, value: float, **attributes: Any) -> None:
        """Record an evaluation or safety score."""

    def flush(self) -> None:
        """Flush pending trace data."""
