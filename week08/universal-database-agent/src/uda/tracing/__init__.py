"""Tracing selection."""

from __future__ import annotations

from ..config import AppConfig
from .base import Tracer
from .langfuse import LangfuseTracer
from .noop import NoopTracer


def build_tracer(config: AppConfig) -> Tracer:
    """Return the tracer selected by configuration."""

    if config.observability.tracer == "langfuse":
        settings = config.observability.langfuse
        return LangfuseTracer(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
        )
    return NoopTracer()


__all__ = ["LangfuseTracer", "NoopTracer", "Tracer", "build_tracer"]
