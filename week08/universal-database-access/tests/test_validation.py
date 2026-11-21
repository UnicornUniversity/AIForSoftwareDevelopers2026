import pytest

from uda.models import (
    AttributeMapping,
    Candidate,
    Column,
    ConceptProposal,
    TableSchema,
)
from uda.validation import (
    canonicalize_proposal,
    validate_candidate,
    validate_proposal,
)

SCHEMA_VERSION = "sha256:" + "0" * 64
SCHEMA = TableSchema(
    table_name="Customer",
    columns=[
        Column(name="customer_id", data_type="int", nullable=False),
        Column(name="full_name", data_type="nvarchar(200)", nullable=False),
        Column(name="email", data_type="nvarchar(320)", nullable=True),
    ],
)


def _mapping(
    attribute: str,
    column: str,
    description: str = "A mapped attribute.",
) -> AttributeMapping:
    return AttributeMapping(
        attribute=attribute,
        description=description,
        column=column,
    )


def _multi_mapping(attribute: str, *columns: str) -> AttributeMapping:
    return AttributeMapping(
        attribute=attribute,
        description="A composite attribute.",
        column_names=list(columns),
    )


def _proposal(*attributes: AttributeMapping) -> ConceptProposal:
    return ConceptProposal(
        concept_name="Customer",
        description="A person who buys from the store.",
        attributes=attributes or (_mapping("identifier", "customer_id"),),
    )


def test_valid_proposal_has_no_issues() -> None:
    proposal = _proposal(
        _mapping("identifier", "customer_id"),
        _mapping("name", "full_name"),
    )

    assert validate_proposal(SCHEMA, proposal) == ()


def test_unknown_column_is_reported() -> None:
    issues = validate_proposal(SCHEMA, _proposal(_mapping("identifier", "customer_key")))

    assert len(issues) == 1
    assert issues[0].code == "unknown_column"
    assert issues[0].attribute == "identifier"
    assert issues[0].column == "customer_key"
    assert "dbo.Customer" in issues[0].message


def test_column_matching_is_case_insensitive() -> None:
    proposal = _proposal(_mapping("identifier", "Customer_ID"))

    assert validate_proposal(SCHEMA, proposal) == ()


def test_duplicate_column_mapping_names_the_first_attribute() -> None:
    proposal = _proposal(
        _mapping("identifier", "customer_id"),
        _mapping("key", "Customer_ID"),
    )

    issues = validate_proposal(SCHEMA, proposal)

    assert [issue.code for issue in issues] == ["duplicate_column_mapping"]
    assert issues[0].attribute == "key"
    assert "'identifier'" in issues[0].message


def test_issues_follow_attribute_order() -> None:
    proposal = _proposal(
        _mapping("identifier", "missing_id"),
        _mapping("name", "full_name"),
        _mapping("email", "missing_email"),
    )

    issues = validate_proposal(SCHEMA, proposal)

    assert [(issue.code, issue.attribute) for issue in issues] == [
        ("unknown_column", "identifier"),
        ("unknown_column", "email"),
    ]


def test_repeated_unknown_column_reports_each_mapping() -> None:
    proposal = _proposal(
        _mapping("identifier", "missing"),
        _mapping("key", "missing"),
    )

    issues = validate_proposal(SCHEMA, proposal)

    assert [issue.code for issue in issues] == ["unknown_column", "unknown_column"]


def test_multi_column_mapping_is_valid() -> None:
    proposal = _proposal(_multi_mapping("contact", "full_name", "email"))

    assert validate_proposal(SCHEMA, proposal) == ()


def test_unknown_column_in_multi_column_mapping_is_reported() -> None:
    proposal = _proposal(_multi_mapping("contact", "full_name", "missing"))

    issues = validate_proposal(SCHEMA, proposal)

    assert [issue.code for issue in issues] == ["unknown_column"]
    assert issues[0].column == "missing"


def test_duplicate_columns_across_multi_column_mappings_are_reported() -> None:
    proposal = _proposal(
        _multi_mapping("contact", "full_name", "email"),
        _mapping("alias", "EMAIL"),
    )

    issues = validate_proposal(SCHEMA, proposal)

    assert [issue.code for issue in issues] == ["duplicate_column_mapping"]
    assert issues[0].column == "email"


def test_canonicalize_proposal_uses_schema_spelling() -> None:
    proposal = _proposal(_mapping("identifier", "CUSTOMER_ID"))

    normalized = canonicalize_proposal(SCHEMA, proposal)

    assert normalized.attributes[0].column_names == ("customer_id",)


def test_canonicalize_proposal_rejects_unknown_columns() -> None:
    proposal = _proposal(_mapping("identifier", "missing"))

    with pytest.raises(ValueError, match="unknown column"):
        canonicalize_proposal(SCHEMA, proposal)


def test_valid_candidate_has_no_issues() -> None:
    candidate = Candidate(
        physical_table="dbo.Customer",
        schema_version=SCHEMA_VERSION,
        concept=_proposal(),
    )

    assert validate_candidate(SCHEMA, candidate) == ()


def test_table_mismatch_is_reported() -> None:
    candidate = Candidate(
        physical_table="dbo.Other",
        schema_version=SCHEMA_VERSION,
        concept=_proposal(),
    )

    issues = validate_candidate(SCHEMA, candidate)

    assert [issue.code for issue in issues] == ["table_mismatch"]
    assert "dbo.Other" in issues[0].message


def test_candidate_reports_table_and_mapping_issues_together() -> None:
    candidate = Candidate(
        physical_table="dbo.Other",
        schema_version=SCHEMA_VERSION,
        concept=_proposal(_mapping("identifier", "missing_id")),
    )

    issues = validate_candidate(SCHEMA, candidate)

    assert [issue.code for issue in issues] == [
        "table_mismatch",
        "unknown_column",
    ]
