from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from uda.models import (
    AttributeMapping,
    Candidate,
    Column,
    ConceptProposal,
    TableSchema,
)

SCHEMA_VERSION = "sha256:" + "0" * 64


def _column(
    name: str = "customer_id",
    data_type: str = "int",
    nullable: bool = False,
) -> Column:
    return Column(name=name, data_type=data_type, nullable=nullable)


def _proposal(**overrides: object) -> ConceptProposal:
    data: dict[str, object] = {
        "concept_name": "Customer",
        "description": "A person who buys from the store.",
        "attributes": (
            AttributeMapping(attribute="identifier", column="customer_id"),
        ),
    }
    data.update(overrides)
    return ConceptProposal(**data)  # type: ignore[arg-type]


def test_table_schema_qualified_name_and_column_names() -> None:
    schema = TableSchema(table_name="Customer", columns=[_column()])

    assert schema.qualified_name == "dbo.Customer"
    assert schema.column_names() == {"customer_id"}


def test_table_schema_rejects_no_columns() -> None:
    with pytest.raises(ValidationError, match="at least one column"):
        TableSchema(table_name="Customer", columns=[])


def test_table_schema_rejects_duplicate_columns() -> None:
    with pytest.raises(ValidationError, match="duplicate column names: customer_id"):
        TableSchema(table_name="Customer", columns=[_column(), _column()])


def test_names_are_stripped_and_cannot_be_blank() -> None:
    column = _column(name="  customer_id  ")

    assert column.name == "customer_id"
    with pytest.raises(ValidationError):
        _column(name="   ")


def test_proposal_requires_at_least_one_attribute() -> None:
    with pytest.raises(ValidationError, match="at least one attribute"):
        _proposal(attributes=())


def test_proposal_rejects_duplicate_attribute_names() -> None:
    with pytest.raises(ValidationError, match="duplicate attribute names: identifier"):
        _proposal(
            attributes=(
                AttributeMapping(attribute="identifier", column="customer_id"),
                AttributeMapping(attribute="Identifier", column="email"),
            )
        )


def test_candidate_defaults_to_pending_review() -> None:
    candidate = Candidate(
        physical_table="dbo.Customer",
        schema_version=SCHEMA_VERSION,
        concept=_proposal(),
    )

    assert candidate.status == "pending_review"
    assert candidate.source_table == "dbo.Customer"
    assert candidate.physical_table == "dbo.Customer"
    assert candidate.candidate_id.version == 4
    assert candidate.created_at.tzinfo is not None


def test_candidate_rejects_any_other_status() -> None:
    with pytest.raises(ValidationError):
        Candidate(
            status="approved",  # type: ignore[arg-type]
            physical_table="dbo.Customer",
            schema_version=SCHEMA_VERSION,
            concept=_proposal(),
        )


def test_candidate_json_round_trip() -> None:
    candidate = Candidate(
        physical_table="dbo.Customer",
        schema_version=SCHEMA_VERSION,
        concept=_proposal(),
    )

    restored = Candidate.model_validate_json(candidate.model_dump_json())

    assert restored == candidate


def test_candidate_requires_schema_version() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        Candidate(source_table="dbo.Customer", concept=_proposal())


def test_candidate_id_must_be_uuid4() -> None:
    with pytest.raises(ValidationError, match="UUIDv4"):
        Candidate(
            candidate_id=UUID("00000000-0000-1000-8000-000000000000"),
            source_table="dbo.Customer",
            schema_version=SCHEMA_VERSION,
            concept=_proposal(),
        )


def test_candidate_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Candidate(
            created_at=datetime(2026, 11, 20, 10, 0, 0),
            source_table="dbo.Customer",
            schema_version=SCHEMA_VERSION,
            concept=_proposal(),
        )


def test_attribute_mapping_accepts_legacy_single_column() -> None:
    mapping = AttributeMapping(attribute="identifier", column="customer_id")

    assert mapping.column_names == ("customer_id",)
    assert mapping.column == "customer_id"


def test_attribute_mapping_accepts_multiple_columns() -> None:
    mapping = AttributeMapping(
        attribute="contact",
        column_names=["full_name", "email"],
    )

    assert mapping.column_names == ("full_name", "email")
    with pytest.raises(ValueError, match="exactly one"):
        _ = mapping.column


def test_attribute_mapping_rejects_no_columns() -> None:
    with pytest.raises(ValidationError, match="at least one column"):
        AttributeMapping(attribute="identifier", column_names=[])


def test_attribute_mapping_rejects_duplicate_columns() -> None:
    with pytest.raises(
        ValidationError, match="duplicate column names: customer_id"
    ):
        AttributeMapping(
            attribute="identifier",
            column_names=["customer_id", "Customer_ID"],
        )


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Column(
            name="customer_id",
            data_type="int",
            nullable=False,
            comment="not part of the contract",  # type: ignore[call-arg]
        )


def test_column_accepts_sql_type_and_legacy_data_type() -> None:
    modern = Column(name="customer_id", sql_type="int", nullable=False)
    legacy = Column(name="customer_id", data_type="int", nullable=False)

    assert modern.sql_type == "int"
    assert modern.data_type == "int"
    assert legacy.sql_type == "int"
    assert legacy.data_type == "int"


def test_primary_key_flag_is_unknown_by_default() -> None:
    unknown = Column(name="customer_id", sql_type="int")
    primary = Column(name="customer_id", sql_type="int", is_primary_key=True)
    not_primary = Column(name="customer_id", sql_type="int", is_primary_key=False)

    assert unknown.is_primary_key is None
    assert primary.is_primary_key is True
    assert not_primary.is_primary_key is False
