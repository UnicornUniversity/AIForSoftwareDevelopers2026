from __future__ import annotations

import copy
import json

import pytest
from _discovery_fixtures import valid_json, valid_payload

from uda.discovery.models import DiscoveryOutput
from uda.discovery.schema import (
    discovery_output_schema,
    discovery_output_schema_json,
    validate_discovery_output,
)
from uda.discovery.validation import parse_discovery_output
from uda.errors import ProposalValidationError


def test_valid_payload_passes_json_schema_and_pydantic() -> None:
    payload = valid_payload()
    assert validate_discovery_output(payload) == ()
    output = parse_discovery_output(valid_json())
    assert isinstance(output, DiscoveryOutput)
    assert len(output.concepts) == 3
    assert len(output.mappings) == 7
    assert len(output.relationships) == 1


def test_schema_is_generated_deterministically_and_strict() -> None:
    first = discovery_output_schema()
    second = discovery_output_schema()
    assert first == second
    assert first["additionalProperties"] is False
    text = discovery_output_schema_json()
    assert text == discovery_output_schema_json()
    assert '"additionalProperties": false' in text


def test_missing_required_collection_fails() -> None:
    payload = valid_payload()
    payload.pop("concepts")
    errors = validate_discovery_output(payload)
    assert errors
    assert any("concepts" in error for error in errors)


def test_missing_required_source_references_fails() -> None:
    payload = valid_payload()
    payload["concepts"][0]["source_references"] = []
    errors = validate_discovery_output(payload)
    assert any("source_references" in error for error in errors)


def test_invalid_status_and_unknown_fields_fail() -> None:
    payload = valid_payload()
    payload["concepts"][0]["status"] = "approved"
    errors = validate_discovery_output(payload)
    assert any("status" in error or "Additional" in error for error in errors)


def test_invalid_confidence_fails() -> None:
    payload = valid_payload()
    payload["concepts"][0]["confidence"] = "certain"
    errors = validate_discovery_output(payload)
    assert any("confidence" in error for error in errors)


def test_invalid_relationship_type_and_level_fail() -> None:
    payload = valid_payload()
    payload["relationships"][0]["relationship_type"] = "Places"
    assert any(
        "relationship_type" in error
        for error in validate_discovery_output(payload)
    )
    payload = valid_payload()
    payload["mappings"][0]["level"] = "schema"
    assert any("level" in error for error in validate_discovery_output(payload))


def test_non_object_or_malformed_json_is_rejected() -> None:
    for raw in ("", "not json", "[]", '"text"'):
        with pytest.raises(ProposalValidationError):
            parse_discovery_output(raw)


def test_unknown_field_is_rejected_by_schema_and_pydantic() -> None:
    payload = valid_payload()
    payload["concepts"][0]["unexpected"] = "value"
    assert validate_discovery_output(payload)
    with pytest.raises(ProposalValidationError):
        parse_discovery_output(json.dumps(payload))


def test_schema_errors_do_not_include_the_whole_payload() -> None:
    payload = copy.deepcopy(valid_payload())
    payload["concepts"][0]["definition"] = ""
    errors = validate_discovery_output(payload)
    assert errors
    assert all(len(error) < 1000 for error in errors)
