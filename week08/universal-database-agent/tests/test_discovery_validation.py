from __future__ import annotations

import copy
from pathlib import Path

import pytest
from _discovery_fixtures import load_evidence, valid_payload, write_repository

from uda.discovery.models import (
    DiscoveryOutput,
    MappingProposal,
    ProposalBatch,
    SourceReference,
    make_mapping_id,
)
from uda.discovery.validation import (
    build_proposals,
    validate_proposal_batch,
    validate_record_evidence,
)
from uda.errors import ProposalValidationError


def _output_and_evidence(tmp_path: Path):
    root = tmp_path / "ddl"
    write_repository(root)
    return DiscoveryOutput.model_validate(valid_payload()), load_evidence(root)


def test_valid_payload_builds_many_to_many_proposals(tmp_path: Path) -> None:
    output, evidence = _output_and_evidence(tmp_path)
    batch = build_proposals(output, evidence)
    assert batch.counts == {"concepts": 3, "mappings": 7, "relationships": 1}
    customer_mappings = [
        item for item in batch.mappings if item.semantic_id == "customer"
    ]
    assert len(customer_mappings) == 4
    country_sources = {
        item.semantic_id
        for item in batch.mappings
        if item.source_physical_id.endswith("/column/Country")
    }
    assert country_sources == {"customer", "customer-location"}
    order_sources = {
        item.source_physical_id
        for item in batch.mappings
        if item.semantic_id == "order"
    }
    assert len(order_sources) == 2
    assert all(item.status == "proposed" for item in batch.concepts)
    assert all(item.status == "proposed" for item in batch.mappings)
    assert all(item.status == "proposed" for item in batch.relationships)


def test_unknown_object_physical_id_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["concepts"][0]["source_references"][0]["physical_id"] = (
        "sqlserver/Northwind/dbo/table/Missing"
    )
    with pytest.raises(ProposalValidationError, match="unknown object Physical ID"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_unknown_column_id_in_mapping_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["mappings"][1]["source_physical_id"] = (
        "sqlserver/Northwind/dbo/table/Customers/column/Missing"
    )
    with pytest.raises(ProposalValidationError, match="unknown column Physical ID"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_unknown_concept_reference_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["mappings"][0]["concept_ref"] = "missing"
    with pytest.raises(ProposalValidationError, match="unknown concept ref"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_invalid_relationship_endpoint_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["relationships"][0]["source_concept_ref"] = "missing"
    with pytest.raises(ProposalValidationError, match="unknown concept ref"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_duplicate_concept_identity_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["concepts"][1]["name"] = "Customer"
    with pytest.raises(ProposalValidationError, match="duplicate Semantic ID"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_duplicate_mapping_identity_is_rejected(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["mappings"].append(copy.deepcopy(payload["mappings"][0]))
    with pytest.raises(ProposalValidationError, match="duplicate mapping identity"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_rationale_must_explain_not_repeat_the_name(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["concepts"][0]["rationale"] = payload["concepts"][0]["name"]
    with pytest.raises(ProposalValidationError, match="repeat"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_ddl_reference_requires_matching_provenance(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["concepts"][0]["source_references"][2].pop("ddl_provenance")
    with pytest.raises(ProposalValidationError, match="DDL provenance"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_non_ddl_reference_rejects_ddl_provenance(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    payload["concepts"][0]["source_references"][0]["ddl_provenance"] = "smo_scripter"
    with pytest.raises(ProposalValidationError, match="only valid for kind 'ddl'"):
        build_proposals(DiscoveryOutput.model_validate(payload), evidence)


def test_optional_confidence_may_be_absent(tmp_path: Path) -> None:
    _, evidence = _output_and_evidence(tmp_path)
    payload = valid_payload()
    for collection in ("concepts", "mappings", "relationships"):
        for item in payload[collection]:
            item.pop("confidence", None)
    batch = build_proposals(DiscoveryOutput.model_validate(payload), evidence)
    assert batch.counts["concepts"] == 3


def test_relationships_are_independent_of_concept_order(tmp_path: Path) -> None:
    output, evidence = _output_and_evidence(tmp_path)
    original = build_proposals(output, evidence)
    payload = valid_payload()
    payload["concepts"].reverse()
    reordered = build_proposals(
        DiscoveryOutput.model_validate(payload), evidence
    )
    assert [item.relationship_id for item in original.relationships] == [
        item.relationship_id for item in reordered.relationships
    ]
    assert [item.mapping_id for item in original.mappings] == [
        item.mapping_id for item in reordered.mappings
    ]


def test_validate_proposal_batch_detects_proposal_id_mismatch(
    tmp_path: Path,
) -> None:
    output, evidence = _output_and_evidence(tmp_path)
    batch = build_proposals(output, evidence)
    mapping = batch.mappings[0]
    broken = batch.model_copy(
        update={
            "mappings": (
                mapping.model_copy(update={"proposal_id": "mapping-0000000000000000"}),
            )
        }
    )
    errors = validate_proposal_batch(broken)
    assert any("proposal_id must equal mapping_id" in error for error in errors)


def test_validate_proposal_batch_detects_unknown_mapping_concept(
    tmp_path: Path,
) -> None:
    output, evidence = _output_and_evidence(tmp_path)
    batch = build_proposals(output, evidence)
    mapping = batch.mappings[0]
    broken_mapping = MappingProposal(
        proposal_id=make_mapping_id(
            mapping.level, mapping.source_physical_id, "missing"
        ),
        mapping_id=make_mapping_id(
            mapping.level, mapping.source_physical_id, "missing"
        ),
        level=mapping.level,
        source_physical_id=mapping.source_physical_id,
        semantic_id="missing",
        source_references=mapping.source_references,
        rationale=mapping.rationale,
    )
    broken = ProposalBatch(concepts=batch.concepts, mappings=(broken_mapping,))
    errors = validate_proposal_batch(broken)
    assert any("has no concept proposal" in error for error in errors)


def test_validate_record_evidence_rechecks_physical_references(
    tmp_path: Path,
) -> None:
    output, evidence = _output_and_evidence(tmp_path)
    batch = build_proposals(output, evidence)
    concept = batch.concepts[0]
    missing = SourceReference(
        physical_id="sqlserver/Northwind/dbo/table/Missing",
        kind="object",
        detail="A missing object.",
    )
    broken = concept.model_copy(update={"source_references": (missing,)})
    errors = validate_record_evidence((broken,), evidence)
    assert any("unknown object Physical ID" in error for error in errors)
