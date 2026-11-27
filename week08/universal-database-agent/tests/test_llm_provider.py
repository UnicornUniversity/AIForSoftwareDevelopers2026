from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from uda.config import LLMConfig, load_config
from uda.errors import ConfigurationError, LLMProviderError
from uda.llm import build_llm_client
from uda.llm.fake import FakeLLMClient
from uda.llm.openai_compatible import OpenAICompatibleClient


class FakeCompletions:
    def __init__(self, *, content: str | None = "hello", error: Exception | None = None):
        self.content = content
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.content))
            ]
        )


class FakeOpenAIClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def _client(
    completions: FakeCompletions,
    *,
    config: LLMConfig | None = None,
) -> tuple[OpenAICompatibleClient, FakeOpenAIClient]:
    fake = FakeOpenAIClient(completions)
    client = OpenAICompatibleClient(
        config or LLMConfig(provider="deepseek", api_key="test-key"),
        client_factory=lambda **kwargs: fake,
    )
    return client, fake


def test_factory_returns_offline_fake() -> None:
    config = load_config(env={"UDA_LLM_PROVIDER": "fake"})
    assert isinstance(build_llm_client(config), FakeLLMClient)


def test_factory_rejects_unknown_provider() -> None:
    config = load_config(env={"UDA_LLM_PROVIDER": "mystery"})
    with pytest.raises(ConfigurationError, match="Unsupported LLM provider"):
        build_llm_client(config)


@pytest.mark.parametrize("key", ["", "change-me"])
def test_deepseek_requires_a_real_api_key(key: str) -> None:
    with pytest.raises(ConfigurationError, match="UDA_LLM_API_KEY"):
        OpenAICompatibleClient(
            LLMConfig(provider="deepseek", api_key=key),
            client_factory=lambda **kwargs: FakeOpenAIClient(FakeCompletions()),
        )


def test_ollama_allows_an_empty_key() -> None:
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeOpenAIClient:
        captured.update(kwargs)
        return FakeOpenAIClient(FakeCompletions())

    client = OpenAICompatibleClient(
        LLMConfig(provider="ollama", api_key=""),
        client_factory=factory,
    )
    assert client.provider_name == "ollama"
    assert captured["api_key"] == "ollama"


def test_invoke_maps_roles_and_provider_parameters() -> None:
    client, fake = _client(FakeCompletions(content="structured response"))
    result = client.invoke(
        [SystemMessage(content="system"), HumanMessage(content="human")]
    )
    assert result == "structured response"
    kwargs = fake.chat.completions.kwargs
    assert kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "human"},
    ]
    assert kwargs["model"] == "deepseek-chat"
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 1024


def test_provider_errors_are_sanitized_and_not_retried() -> None:
    client, _ = _client(
        FakeCompletions(error=RuntimeError("sk-secret-value leaked"))
    )
    with pytest.raises(LLMProviderError) as excinfo:
        client.invoke([HumanMessage(content="hello")])
    message = str(excinfo.value)
    assert "RuntimeError" in message
    assert "no automatic retry" in message
    assert "sk-secret-value" not in message


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_provider_response_is_rejected(content: str | None) -> None:
    client, _ = _client(FakeCompletions(content=content))
    with pytest.raises(LLMProviderError, match="empty response"):
        client.invoke([HumanMessage(content="hello")])


def test_config_timeout_is_read_from_environment() -> None:
    config = load_config(env={"UDA_LLM_TIMEOUT": "5.5"})
    assert config.llm.timeout_seconds == 5.5


def test_fake_provider_invokes_without_network() -> None:
    fake = FakeLLMClient(responses=["answer"])
    assert fake.invoke([HumanMessage(content="question")]) == "answer"
    assert fake.provider_name == "fake"
