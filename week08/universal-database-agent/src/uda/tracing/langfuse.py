"""Langfuse tracer. The SDK is imported lazily and only here."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from typing import Any

from ..errors import TracingError
from .redaction import sanitize_attributes


class LangfuseTracer:
    """Send sanitized spans to a Langfuse instance."""

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        if not public_key or not secret_key:
            raise TracingError(
                "Langfuse tracing requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
            )
        try:
            from langfuse import Langfuse
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise TracingError("The langfuse package is not installed.") from exc
        try:
            self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        except Exception as exc:
            raise TracingError(
                "Could not initialize the Langfuse client. Check LANGFUSE_* settings and host."
            ) from exc

    @contextmanager
    def _span(self, name: str, attributes: dict[str, Any]) -> Any:
        with self._client.start_as_current_span(name=name, metadata=attributes):
            yield

    @contextmanager
    def _generation(self, name: str, attributes: dict[str, Any]) -> Any:
        factory = getattr(self._client, "start_as_current_generation", None)
        if factory is None:
            with self._client.start_as_current_span(name=name, metadata=attributes):
                yield
            return
        with factory(
            name=name,
            model=attributes.get("model"),
            metadata=attributes,
        ):
            yield

    def span(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        return self._span(name, sanitize_attributes(attributes))

    def generation(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        return self._generation(name, sanitize_attributes(attributes))

    def score(self, name: str, value: float, **attributes: Any) -> None:
        metadata = sanitize_attributes(attributes)
        recorder = getattr(self._client, "create_score", None) or getattr(
            self._client, "score", None
        )
        if recorder is None:  # pragma: no cover - SDK shape guard
            raise TracingError("This Langfuse SDK does not expose a score API.")
        recorder(name=name, value=value, metadata=metadata)

    def flush(self) -> None:
        self._client.flush()
