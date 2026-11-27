from __future__ import annotations

import json
from pathlib import Path

import pytest
from _discovery_fixtures import load_evidence, sample_metadata, write_repository
from _object_discovery_fixtures import object_json, object_payload

from uda.discovery.object_validation import (
    parse_object_output,
    validate_object_output,
)
from uda.errors import ProposalValidationError


def _table(name: str):
    for table in sample_metadata().objects:
        if table.name == name:
            return table
    raise AssertionError(name)


def _evidence(tmp_path: Path):
    root = tmp_path / "ddl"
    write_repository(root)
    return load_evidence(root)


def test_valid_payload_parses_and_validates(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    output = parse_object_output(object_json("Customers"))
    warnings = validate_object_output(output, _table("Customers"), evidence)
    assert warnings == ()


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(ProposalValidationError, match="not valid JSON"):
        parse_object_output("{not json")


def test_empty_response_is_rejected() -> None:
    with pytest.raises(ProposalValidationError, match="empty response"):
        parse_object_output("   ")


def test_relationships_are_forbidden() -> None:
    payload = object_payload()
    payload["relationships"] = []
    with pytest.raises(ProposalValidationError, match="relationships"):
        parse_object_output(json.dumps(payload))


def test_wrong_object_identity_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["object_physical_id"] = _table("Orders").physical_id
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="does not describe the requested"):
        validate_object_output(output, _table("Customers"), evidence)


def test_wrong_object_kind_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["object_kind"] = "view"
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="does not match"):
        validate_object_output(output, _table("Customers"), evidence)


def test_table_cannot_be_a_derived_result_set(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["object_role"] = "derived_result_set"
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="derived result set"):
        validate_object_output(output, _table("Customers"), evidence)


def test_unknown_concept_ref_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"][0]["concept_ref"] = "missing"
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="unknown concept ref"):
        validate_object_output(output, _table("Customers"), evidence)


def test_column_from_another_table_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"][1]["source_physical_id"] = (
        _table("Orders").physical_id + "/column/OrderID"
    )
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="unknown column"):
        validate_object_output(output, _table("Customers"), evidence)


def test_unknown_attribute_name_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"][1]["attribute_name"] = "Missing attribute"
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="has no attribute"):
        validate_object_output(output, _table("Customers"), evidence)


def test_attribute_mapping_must_cite_the_mapped_column(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    # The Country attribute exists, but this mapping claims it represents
    # CustomerName, which the attribute does not cite.
    payload["mappings"][1]["attribute_name"] = "Country"
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="is not cited by attribute"):
        validate_object_output(output, _table("Customers"), evidence)


def test_duplicate_mapping_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"].append(dict(payload["mappings"][1]))
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="duplicate mapping"):
        validate_object_output(output, _table("Customers"), evidence)


def test_object_mapping_must_reference_the_requested_table(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"][0]["source_physical_id"] = _table("Orders").physical_id
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="object mappings"):
        validate_object_output(output, _table("Customers"), evidence)


def test_every_concept_must_be_mapped(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["concepts"].append(
        {
            "ref": "c2",
            "name": "Unmapped",
            "definition": "A concept with no mapping.",
            "attributes": [payload["concepts"][0]["attributes"][0]],
            "source_references": [payload["concepts"][0]["source_references"][0]],
            "rationale": "This concept intentionally has no mapping for the test.",
        }
    )
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="no mapping references"):
        validate_object_output(output, _table("Customers"), evidence)


def test_at_least_one_object_mapping_is_required(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    payload = object_payload()
    payload["mappings"] = payload["mappings"][1:]
    output = parse_object_output(json.dumps(payload))
    with pytest.raises(ProposalValidationError, match="object-level mapping"):
        validate_object_output(output, _table("Customers"), evidence)
