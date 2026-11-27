"""Select the configured LLM client."""

from __future__ import annotations

from ..config import AppConfig
from ..errors import ConfigurationError
from .base import LLMClient
from .fake import FakeLLMClient
from .openai_compatible import OpenAICompatibleClient

_OPENAI_COMPATIBLE_PROVIDERS = frozenset({"deepseek", "openai", "ollama"})


def build_llm_client(config: AppConfig) -> LLMClient:
    """Return the provider selected by configuration.

    ``fake`` exists for explicit offline demonstrations and tests. It is never selected by
    a shipped profile.
    """

    provider = config.llm.provider.strip().lower()
    if provider == "fake":
        return FakeLLMClient()
    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        return OpenAICompatibleClient(config.llm)
    raise ConfigurationError(
        f"Unsupported LLM provider {config.llm.provider!r}; use deepseek, ollama, "
        "openai, or fake."
    )
