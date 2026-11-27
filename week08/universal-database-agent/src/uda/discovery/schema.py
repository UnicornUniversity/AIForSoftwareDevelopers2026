"""JSON Schema validation for untrusted discovery output.

The schema is generated from the same Pydantic contract that parses the response, so the
prompt's schema and the application's validation cannot drift apart. LLM output is always
validated by application code before it is parsed into typed records.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator

from .models import DiscoveryOutput

_SCHEMA: dict[str, Any] = copy.deepcopy(DiscoveryOutput.model_json_schema())
_VALIDATOR = Draft202012Validator(_SCHEMA)

_MAX_ERROR_LENGTH = 300


def discovery_output_schema() -> dict[str, Any]:
    """Return a defensive copy of the JSON Schema used for LLM output."""

    return copy.deepcopy(_SCHEMA)


def discovery_output_schema_json() -> str:
    """Return the prompt-facing schema text in deterministic form."""

    return json.dumps(_SCHEMA, indent=2, sort_keys=True)


def _format_path(path: Any) -> str:
    parts = [str(part) for part in path]
    return ".".join(parts) if parts else "<root>"


def validate_discovery_output(payload: object) -> tuple[str, ...]:
    """Validate untrusted JSON data and return human-readable schema errors."""

    errors: list[str] = []
    for error in sorted(
        _VALIDATOR.iter_errors(payload),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        message = " ".join(str(error.message).split())
        if len(message) > _MAX_ERROR_LENGTH:
            message = message[:_MAX_ERROR_LENGTH] + "...[truncated]"
        errors.append(f"{_format_path(error.absolute_path)}: {message}")
    return tuple(errors)
