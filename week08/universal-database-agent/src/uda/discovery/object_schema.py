"""JSON Schema validation for object-level discovery output.

The schema is generated from the Pydantic contract that also parses the response, so the
prompt and application validation cannot drift. Relationships are absent from the contract
and are therefore rejected by ``extra="forbid"``.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator

from .object_models import ObjectDiscoveryOutput

_SCHEMA: dict[str, Any] = copy.deepcopy(ObjectDiscoveryOutput.model_json_schema())

# Object-level discovery must produce usable semantic attributes. The shared
# DiscoveryConcept model keeps `attributes` optional for Phase 3 compatibility, so the
# object-level schema tightens it without changing the canonical contract.
_CONCEPT_DEFINITION = _SCHEMA.get("$defs", {}).get("DiscoveryConcept")
if _CONCEPT_DEFINITION is not None:
    _required = _CONCEPT_DEFINITION.setdefault("required", [])
    if "attributes" not in _required:
        _required.append("attributes")
    _CONCEPT_DEFINITION["properties"]["attributes"]["minItems"] = 1

_VALIDATOR = Draft202012Validator(_SCHEMA)
_MAX_ERROR_LENGTH = 300


def object_output_schema() -> dict[str, Any]:
    """Return a defensive copy of the object-level JSON Schema."""

    return copy.deepcopy(_SCHEMA)


def object_output_schema_json() -> str:
    """Return the prompt-facing schema text in deterministic form."""

    return json.dumps(_SCHEMA, indent=2, sort_keys=True)


def _format_path(path: Any) -> str:
    parts = [str(part) for part in path]
    return ".".join(parts) if parts else "<root>"


def validate_object_output_schema(payload: object) -> tuple[str, ...]:
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
