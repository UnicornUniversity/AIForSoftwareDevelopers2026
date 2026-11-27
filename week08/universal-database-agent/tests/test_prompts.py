from __future__ import annotations

from pathlib import Path

import pytest

from uda.errors import ConfigurationError
from uda.prompts import PromptRegistry


def write_registry(tmp_path: Path, body: str | None = None) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(
        body
        if body is not None
        else (
            "version: 1\n"
            "prompts:\n"
            "  interpret:\n"
            "    version: '1'\n"
            "    template: 'Interpret: {question}'\n"
        ),
        encoding="utf-8",
    )
    return path


def test_registry_loads_and_renders(tmp_path: Path) -> None:
    registry = PromptRegistry.load(write_registry(tmp_path))
    assert registry.names() == ("interpret",)
    entry = registry.get("interpret")
    assert entry.version == "1"
    messages = entry.render(question="customers?")
    assert "customers?" in str(messages[0].content)
    assert "customers?" in str(registry.render("interpret", question="customers?")[0].content)


def test_unknown_prompt_is_an_error(tmp_path: Path) -> None:
    registry = PromptRegistry.load(write_registry(tmp_path))
    with pytest.raises(ConfigurationError, match="Unknown prompt"):
        registry.get("missing")


def test_missing_registry_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        PromptRegistry.load(tmp_path / "missing.yaml")


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    body = (
        "version: 1\n"
        "prompts:\n"
        "  interpret:\n"
        "    version: '1'\n"
        "    template: 'first'\n"
        "  interpret:\n"
        "    version: '2'\n"
        "    template: 'second'\n"
    )
    with pytest.raises(ConfigurationError, match="Duplicate"):
        PromptRegistry.load(write_registry(tmp_path, body))


def test_malformed_template_is_an_actionable_error(tmp_path: Path) -> None:
    body = (
        "version: 1\n"
        "prompts:\n"
        "  interpret:\n"
        "    version: '1'\n"
        "    template: 'Hello {question'\n"
    )
    with pytest.raises(ConfigurationError, match="interpret.*invalid template"):
        PromptRegistry.load(write_registry(tmp_path, body))


def test_missing_required_template_field_is_an_error(tmp_path: Path) -> None:
    body = "version: 1\nprompts:\n  interpret:\n    version: '1'\n"
    with pytest.raises(ConfigurationError, match="interpret.*template"):
        PromptRegistry.load(write_registry(tmp_path, body))


def test_missing_prompt_version_is_an_error(tmp_path: Path) -> None:
    body = "version: 1\nprompts:\n  interpret:\n    template: 'Hello'\n"
    with pytest.raises(ConfigurationError, match="interpret.*version"):
        PromptRegistry.load(write_registry(tmp_path, body))


@pytest.mark.parametrize("version", ["0", "one", "1.0"])
def test_invalid_registry_version_is_an_error(tmp_path: Path, version: str) -> None:
    body = f"version: {version}\nprompts:\n  interpret:\n    version: '1'\n    template: 'x'\n"
    with pytest.raises(ConfigurationError, match="positive integer 'version'"):
        PromptRegistry.load(write_registry(tmp_path, body))


def test_missing_registry_version_is_an_error(tmp_path: Path) -> None:
    body = "prompts:\n  interpret:\n    version: '1'\n    template: 'x'\n"
    with pytest.raises(ConfigurationError, match="positive integer 'version'"):
        PromptRegistry.load(write_registry(tmp_path, body))


def test_missing_template_variable_is_an_actionable_error(tmp_path: Path) -> None:
    registry = PromptRegistry.load(write_registry(tmp_path))
    with pytest.raises(ConfigurationError, match="interpret.*could not be rendered"):
        registry.get("interpret").render()
