"""LLM client contract used by the graph."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import BaseMessage


class LLMClient(Protocol):
    """A minimal provider-neutral chat interface."""

    @property
    def provider_name(self) -> str:
        """Provider identifier for tracing and diagnostics."""

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        """Return the model's text response."""
