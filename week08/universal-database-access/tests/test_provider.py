import pytest

from uda.provider import ProviderConfigurationError, build_deepseek_model


def test_missing_api_key_is_a_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError, match="--response-file"):
        build_deepseek_model()


def test_configured_model_reads_environment(monkeypatch) -> None:
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setenv("UDA_MODEL", "deepseek-chat")
    monkeypatch.setenv("UDA_BASE_URL", "https://example.invalid")

    model = build_deepseek_model()

    assert model.model_name == "deepseek-chat"
