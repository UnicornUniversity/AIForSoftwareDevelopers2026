"""Deterministic fake LLM for offline graph tests."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage


class FakeLLMClient:
    """Returns predictable text without any network call."""

    def __init__(self, responses: Sequence[str] | None = None) -> None:
        self._responses = tuple(responses) if responses else ()
        self._calls = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def call_count(self) -> int:
        return self._calls

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        self._calls += 1
        if self._responses:
            index = min(self._calls - 1, len(self._responses) - 1)
            return self._responses[index]
        prompt = str(messages[-1].content).lower() if messages else ""
        if "ambiguous" in prompt:
            return "ambiguous"
        if "sql" in prompt:
            return "SELECT 1 AS value"
        return "intent: answer the user's question"
