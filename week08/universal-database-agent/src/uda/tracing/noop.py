"""No-op tracer used by default and in offline tests."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any


class NoopTracer:
    def span(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        return nullcontext()

    def generation(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        return nullcontext()

    def score(self, name: str, value: float, **attributes: Any) -> None:
        return None

    def flush(self) -> None:
        return None
