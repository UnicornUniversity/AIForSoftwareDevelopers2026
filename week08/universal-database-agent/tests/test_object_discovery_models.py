from __future__ import annotations

import pytest
from _object_discovery_fixtures import object_payload
from pydantic import ValidationError

from uda.discovery.object_models import (
    ObjectCandidate,
    ObjectDiscoveryOutput,
    object_candidate_id,
    object_execution_key,
    object_request_key,
)
from uda.discovery.object_schema import validate_object_output_schema


def test_object_output_accepts_valid_payload() -> None:
    output = ObjectDiscoveryOutput.model_validate(object_payload())
    assert output.object_kind == "table"
    assert len(output.concepts) == 1
    assert any(mapping.attribute_name for mapping in output.mappings)


def test_object_output_rejects_relationships() -> None:
    payload = object_payload()
    payload["relationships"] = []
    with pytest.raises(ValidationError):
        ObjectDiscoveryOutput.model_validate(payload)
    errors = validate_object_output_schema(payload)
    assert any("relationships" in error for error in errors)


def test_object_output_requires_at_least_one_concept_and_mapping() -> None:
    payload = object_payload()
    payload["concepts"] = []
    payload["mappings"] = []
    errors = validate_object_output_schema(payload)
    assert errors


def test_object_concept_requires_declared_attributes() -> None:
    payload = object_payload()
    del payload["concepts"][0]["attributes"]
    errors = validate_object_output_schema(payload)
    assert any("attributes" in error for error in errors)

    payload = object_payload()
    payload["concepts"][0]["attributes"] = []
    errors = validate_object_output_schema(payload)
    assert any("attributes" in error for error in errors)


def test_identity_is_deterministic_and_name_independent() -> None:
    key = object_request_key(
        "sqlserver/Northwind/dbo/table/Customers",
        "sha256:snapshot",
        "a" * 64,
        "1",
    )
    same = object_request_key(
        "sqlserver/Northwind/dbo/table/Customers",
        "sha256:snapshot",
        "a" * 64,
        "1",
    )
    different_object = object_request_key(
        "sqlserver/Northwind/dbo/table/Orders",
        "sha256:snapshot",
        "a" * 64,
        "1",
    )
    assert key == same
    assert key != different_object

    execution = object_execution_key(key, "deepseek", "deepseek-chat", 0.0, 1024)
    assert execution == object_execution_key(
        key, "deepseek", "deepseek-chat", 0.0, 1024
    )
    assert execution != object_execution_key(
        key, "deepseek", "deepseek-chat", 0.1, 1024
    )
    assert object_candidate_id(execution).startswith("cand-")
    assert len(object_candidate_id(execution)) == len("cand-") + 16


def test_candidate_rejects_relationship_payload() -> None:
    payload = object_payload()
    candidate_payload = {
        "candidate_id": "cand-" + "a" * 16,
        "execution_key": "b" * 64,
        "request_key": "c" * 64,
        "object_physical_id": payload["object_physical_id"],
        "object_kind": "table",
        "object_role": "entity",
        "snapshot_id": "sha256:snapshot",
        "evidence_sha256": "d" * 64,
        "prompt_version": "1",
        "prompt_sha256": "e" * 64,
        "provider": "fake",
        "model": "fixture",
        "temperature": 0.0,
        "max_tokens": 1024,
        "concepts": payload["concepts"],
        "mappings": payload["mappings"],
        "generated_at": "2026-11-18T12:00:00Z",
        "relationships": [],
    }
    with pytest.raises(ValidationError):
        ObjectCandidate.model_validate(candidate_payload)
