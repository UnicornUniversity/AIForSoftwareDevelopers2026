from __future__ import annotations

import pytest
from _discovery_fixtures import valid_payload
from pydantic import ValidationError

from uda.discovery.models import (
    ConceptProposal,
    DiscoveryOutput,
    MappingProposal,
    ProposalBatch,
    RelationshipProposal,
    SourceReference,
    make_mapping_id,
    make_relationship_id,
    make_semantic_id,
)
from uda.errors import ProposalValidationError


def reference() -> SourceReference:
    return SourceReference(
        physical_id="sqlserver/db/dbo/table/T",
        kind="object",
        detail="Table T.",
    )


def test_semantic_id_is_lower_case_and_platform_independent() -> None:
    assert make_semantic_id("Customer") == "customer"
    assert make_semantic_id("Customer Location") == "customer-location"
    assert make_semantic_id("A/B") == "a-b"
    assert "/" not in make_semantic_id("A/B")


def test_semantic_id_rejects_a_name_without_ascii_alphanumerics() -> None:
    with pytest.raises(ProposalValidationError, match="ASCII"):
        make_semantic_id("!!!")


def test_mapping_id_is_deterministic_and_level_sensitive() -> None:
    value = make_mapping_id("object", "sqlserver/db/dbo/table/T", "thing")
    assert value == make_mapping_id("object", "sqlserver/db/dbo/table/T", "thing")
    assert value != make_mapping_id("column", "sqlserver/db/dbo/table/T", "thing")
    assert value.startswith("mapping-")
    assert len(value.split("-", 1)[1]) == 16


def test_relationship_id_is_deterministic_and_endpoint_order_sensitive() -> None:
    value = make_relationship_id("places", "customer", "order")
    assert value == make_relationship_id("places", "customer", "order")
    assert value != make_relationship_id("places", "order", "customer")
    assert value.startswith("relationship-")


def test_source_reference_rejects_unknown_kind_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SourceReference(physical_id="x", kind="table", detail="x")
    with pytest.raises(ValidationError):
        SourceReference(
            physical_id="x", kind="object", detail="x", unexpected=True
        )


def test_final_records_reject_non_proposed_status() -> None:
    with pytest.raises(ValidationError):
        ConceptProposal(
            proposal_id="customer",
            semantic_id="customer",
            name="Customer",
            definition="A party.",
            source_references=(reference(),),
            rationale="The table rows identify a customer.",
            status="approved",
        )
    with pytest.raises(ValidationError):
        MappingProposal(
            proposal_id=make_mapping_id("object", "p", "customer"),
            mapping_id=make_mapping_id("object", "p", "customer"),
            level="object",
            source_physical_id="p",
            semantic_id="customer",
            source_references=(reference(),),
            rationale="The table maps to a customer.",
            status="rejected",
        )
    with pytest.raises(ValidationError):
        RelationshipProposal(
            proposal_id=make_relationship_id("places", "customer", "order"),
            relationship_id=make_relationship_id("places", "customer", "order"),
            relationship_type="places",
            source_semantic_id="customer",
            target_semantic_id="order",
            source_references=(reference(),),
            rationale="The key indicates a customer places orders.",
            status="approved",
        )


def test_optional_confidence_is_preserved_and_may_be_absent() -> None:
    output = DiscoveryOutput.model_validate(valid_payload())
    assert output.concepts[0].confidence == "high"
    payload = valid_payload()
    for concept in payload["concepts"]:
        concept.pop("confidence", None)
    without_confidence = DiscoveryOutput.model_validate(payload)
    assert all(concept.confidence is None for concept in without_confidence.concepts)


def test_discovery_output_requires_all_three_collections() -> None:
    with pytest.raises(ValidationError):
        DiscoveryOutput.model_validate({"concepts": []})
    with pytest.raises(ValidationError):
        DiscoveryOutput.model_validate({"concepts": [], "mappings": []})


def test_proposal_batch_counts_and_empty_state() -> None:
    batch = ProposalBatch()
    assert batch.is_empty is True
    assert batch.counts == {"concepts": 0, "mappings": 0, "relationships": 0}
    concept = ConceptProposal(
        proposal_id="customer",
        semantic_id="customer",
        name="Customer",
        definition="A party.",
        source_references=(reference(),),
        rationale="The table rows identify a customer.",
    )
    populated = ProposalBatch(concepts=(concept,))
    assert populated.is_empty is False
    assert populated.counts["concepts"] == 1
