"""Optional DeepSeek chat-model wiring.

DeepSeek exposes an OpenAI-compatible API, so LangChain's OpenAI client is used
with a custom base URL. The SDK is an optional extra: offline installs and tests
never import it.
"""

import os

from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class ProviderConfigurationError(RuntimeError):
    """Raised when the optional real provider cannot be configured."""


def build_deepseek_model() -> BaseChatModel:
    """Build a DeepSeek chat model from environment variables.

    Reads ``DEEPSEEK_API_KEY`` (required), ``UDA_MODEL``, and ``UDA_BASE_URL``.
    The key is passed straight to the client and never logged.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ProviderConfigurationError(
            "DEEPSEEK_API_KEY is not set; use --response-file for an offline run"
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ProviderConfigurationError(
            "langchain-openai is not installed; run `uv sync --extra llm`"
        ) from exc

    model = os.environ.get("UDA_MODEL", "").strip() or DEFAULT_MODEL
    base_url = os.environ.get("UDA_BASE_URL", "").strip() or DEFAULT_BASE_URL

    return ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
