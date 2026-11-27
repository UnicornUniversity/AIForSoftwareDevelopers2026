"""OpenAI-compatible provider client for DeepSeek and Ollama.

The project's provider-neutral ``LLMClient`` contract is preserved: callers submit
LangChain messages and receive text. The SDK is imported lazily so offline code never
initializes a provider. Provider errors are reduced to their class name; messages never
include API keys, headers, or connection strings.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage

from ..config import LLMConfig
from ..errors import ConfigurationError, LLMProviderError

_ROLE_MAP = {
    "system": "system",
    "human": "user",
    "ai": "assistant",
    "tool": "tool",
    "function": "function",
}
_PLACEHOLDER_KEYS = frozenset({"", "change-me"})


def _default_client_factory(
    *, api_key: str, base_url: str, timeout_seconds: float
) -> Any:
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_seconds,
        max_retries=0,
    )


class OpenAICompatibleClient:
    """Chat client for OpenAI-compatible endpoints such as DeepSeek and Ollama."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        provider = config.provider.strip().lower()
        if not config.model.strip():
            raise ConfigurationError("UDA_LLM_MODEL is required for a live provider.")
        if not config.base_url.strip():
            raise ConfigurationError("UDA_LLM_BASE_URL is required for a live provider.")
        api_key = config.api_key.strip()
        if api_key in _PLACEHOLDER_KEYS:
            if provider != "ollama":
                raise ConfigurationError(
                    f"UDA_LLM_API_KEY is required for provider {config.provider!r}."
                )
            # Local OpenAI-compatible servers generally ignore the key; the SDK still
            # requires a non-empty value.
            api_key = "ollama"
        self._provider = provider
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        factory = client_factory or _default_client_factory
        try:
            self._client = factory(
                api_key=api_key,
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - provider initialization is external
            raise ConfigurationError(
                f"Could not initialize the {config.provider!r} LLM client "
                f"({type(exc).__name__})."
            ) from exc

    @property
    def provider_name(self) -> str:
        return self._provider

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        payload = [
            {
                "role": _ROLE_MAP.get(message.type, "user"),
                "content": str(message.content),
            }
            for message in messages
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=payload,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures are external
            raise LLMProviderError(
                "The LLM provider request failed "
                f"({type(exc).__name__}); no automatic retry was attempted."
            ) from exc
        choices = getattr(response, "choices", None) or ()
        if not choices:
            raise LLMProviderError("The LLM provider returned no choices.")
        content = getattr(getattr(choices[0], "message", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("The LLM provider returned an empty response.")
        return content
