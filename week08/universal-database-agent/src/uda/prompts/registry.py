"""Versioned prompt registry loaded from YAML."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from ..errors import ConfigurationError


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader, node: Any, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigurationError(f"Duplicate prompt registry key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class PromptEntry:
    name: str
    version: str
    template: ChatPromptTemplate

    def render(self, **values: Any) -> list[BaseMessage]:
        """Render the prompt, converting missing variables into a configuration error."""

        try:
            return self.template.format_messages(**values)
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(
                f"Prompt '{self.name}' could not be rendered; "
                f"check its template variables: {exc}"
            ) from exc


class PromptRegistry:
    """Loads named, versioned prompts from a YAML registry."""

    def __init__(self, entries: Mapping[str, PromptEntry]) -> None:
        self._entries = dict(entries)

    @classmethod
    def load(cls, path: Path) -> PromptRegistry:
        if not path.exists():
            raise ConfigurationError(f"Prompt registry not found: {path}")
        try:
            raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Prompt registry is not valid YAML: {path}") from exc
        if not isinstance(raw, Mapping):
            raise ConfigurationError("Prompt registry must be a mapping.")
        version = raw.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ConfigurationError(
                "Prompt registry needs a positive integer 'version'."
            )
        prompts = raw.get("prompts")
        if not isinstance(prompts, Mapping):
            raise ConfigurationError("Prompt registry must contain a 'prompts' mapping.")
        entries: dict[str, PromptEntry] = {}
        for name, value in prompts.items():
            prompt_name = str(name)
            if not prompt_name:
                raise ConfigurationError("Prompt names must be non-empty.")
            if not isinstance(value, Mapping):
                raise ConfigurationError(f"Prompt '{prompt_name}' must be a mapping.")
            prompt_version = value.get("version")
            template = value.get("template")
            if not isinstance(prompt_version, str) or not prompt_version:
                raise ConfigurationError(f"Prompt '{prompt_name}' needs a string version.")
            if not isinstance(template, str) or not template:
                raise ConfigurationError(f"Prompt '{prompt_name}' needs a string template.")
            try:
                parsed = ChatPromptTemplate.from_template(template)
            except Exception as exc:
                raise ConfigurationError(
                    f"Prompt '{prompt_name}' has an invalid template: {exc}"
                ) from exc
            entries[prompt_name] = PromptEntry(
                name=prompt_name,
                version=prompt_version,
                template=parsed,
            )
        if not entries:
            raise ConfigurationError("Prompt registry contains no prompts.")
        return cls(entries)

    def get(self, name: str) -> PromptEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown prompt: {name}") from exc

    def render(self, name: str, **values: Any) -> list[BaseMessage]:
        return self.get(name).render(**values)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))
