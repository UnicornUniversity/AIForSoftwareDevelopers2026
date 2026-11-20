from datetime import UTC, datetime
from uuid import UUID

import pytest

from uda.candidate import CandidateRejectedError, build_candidate
from uda.fixtures import load_demo_schema
from uda.models import (
    AttributeMapping,
    Candidate,
    Column,
    ConceptProposal,
    TableSchema,
)


def _schema() -> TableSchema:
    return TableSchema(
        table_name="Customer",
        columns=[
            Column(name="customer_id", data_type="int", nullable=False),
            Column(name="full_name", data_type="nvarchar(200)", nullable=False),
        ],
    )


def _mapping(attribute: str, column: str) -> AttributeMapping:
    return AttributeMapping(attribute=attribute, column=column)


def _proposal(*attributes: AttributeMapping) -> ConceptProposal:
    return ConceptProposal(
        concept_name="Customer",
        description="A person who buys from the store.",
        attributes=attributes or (_mapping("identifier", "customer_id"),),
    )


def test_build_candidate_returns_pending_review_candidate() -> None:
    schema = _schema()
    proposal = _proposal(_mapping("identifier", "customer_id"))

    candidate = build_candidate(schema, proposal)

    assert candidate.status == "pending_review"
    assert candidate.source_table == "dbo.Customer"
    assert candidate.physical_table == "dbo.Customer"
    assert candidate.candidate_id.version == 4
    assert candidate.created_at.tzinfo is not None
    assert candidate.schema_version.startswith("sha256:")
    assert len(candidate.schema_version) == 71
    assert candidate.concept == proposal
    restored = Candidate.model_validate_json(candidate.model_dump_json())
    assert restored == candidate


def test_build_candidate_accepts_injected_id_and_timestamp() -> None:
    candidate_id = UUID("00000000-0000-4000-8000-000000000002")
    created_at = datetime(2026, 11, 20, 10, 0, 0, tzinfo=UTC)

    candidate = build_candidate(
        _schema(),
        _proposal(_mapping("identifier", "customer_id")),
        candidate_id=candidate_id,
        created_at=created_at,
    )

    assert candidate.candidate_id == candidate_id
    assert candidate.created_at == created_at


def test_build_candidate_canonicalizes_column_names() -> None:
    candidate = build_candidate(
        _schema(),
        _proposal(_mapping("identifier", "CUSTOMER_ID")),
    )

    assert candidate.concept.attributes[0].column_names == ("customer_id",)


def test_build_candidate_supports_multi_column_attributes() -> None:
    proposal = _proposal(
        AttributeMapping(
            attribute="contact",
            column_names=["full_name", "customer_id"],
        )
    )

    candidate = build_candidate(_schema(), proposal)

    assert candidate.concept.attributes[0].column_names == (
        "full_name",
        "customer_id",
    )


def test_build_candidate_uses_the_schema_qualified_name() -> None:
    schema = TableSchema(
        schema_name="sales",
        table_name="Orders",
        columns=[Column(name="order_id", data_type="int", nullable=False)],
    )

    candidate = build_candidate(
        schema,
        _proposal(_mapping("identifier", "order_id")),
    )

    assert candidate.source_table == "sales.Orders"
    assert candidate.physical_table == "sales.Orders"


def test_unknown_column_rejects_the_candidate() -> None:
    with pytest.raises(CandidateRejectedError) as caught:
        build_candidate(_schema(), _proposal(_mapping("identifier", "customer_key")))

    assert isinstance(caught.value, ValueError)
    assert [issue.code for issue in caught.value.issues] == ["unknown_column"]
    assert "unknown_column" in str(caught.value)


def test_duplicate_column_rejects_the_candidate() -> None:
    proposal = _proposal(
        _mapping("identifier", "customer_id"),
        _mapping("key", "Customer_ID"),
    )

    with pytest.raises(CandidateRejectedError) as caught:
        build_candidate(_schema(), proposal)

    assert [issue.code for issue in caught.value.issues] == [
        "duplicate_column_mapping"
    ]


def test_demo_fixture_builds_a_candidate() -> None:
    proposal = ConceptProposal(
        concept_name="Customer",
        description="A person who buys from the store.",
        attributes=(
            _mapping("identifier", "customer_id"),
            _mapping("name", "full_name"),
            _mapping("email", "email"),
            _mapping("active", "is_active"),
        ),
    )

    candidate = build_candidate(load_demo_schema(), proposal)

    assert candidate.source_table == "dbo.Customer"
    assert candidate.physical_table == "dbo.Customer"
    assert candidate.status == "pending_review"
    assert candidate.schema_version.startswith("sha256:")
