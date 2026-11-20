"""Physical-reference validation for LLM proposals.

Validation is pure and offline: it compares a proposal against a ``TableSchema``
and never contacts a database or a model. Physical names are matched
case-insensitively, matching SQL Server's default collation.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from uda.models import (
    AttributeMapping,
    Candidate,
    ConceptProposal,
    NonEmptyStr,
    TableSchema,
)

IssueCode = Literal[
    "table_mismatch",
    "unknown_column",
    "duplicate_column_mapping",
]


class ValidationIssue(BaseModel):
    """One actionable reason a candidate cannot leave ``pending_review``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: IssueCode
    message: NonEmptyStr
    attribute: str | None = None
    column: str | None = None


def _key(name: str) -> str:
    return name.casefold()


def validate_proposal(
    schema: TableSchema, proposal: ConceptProposal
) -> tuple[ValidationIssue, ...]:
    """Return every physical-reference issue in ``proposal``, in mapping order."""
    issues: list[ValidationIssue] = []
    known_columns = {_key(column.name): column.name for column in schema.columns}
    mapped_by: dict[str, str] = {}

    for mapping in proposal.attributes:
        for requested in mapping.column_names:
            key = _key(requested)
            canonical = known_columns.get(key)

            if canonical is None:
                issues.append(
                    ValidationIssue(
                        code="unknown_column",
                        message=(
                            f"column {requested!r} does not exist in "
                            f"{schema.qualified_name}"
                        ),
                        attribute=mapping.attribute,
                        column=requested,
                    )
                )
                continue

            first_attribute = mapped_by.get(key)
            if first_attribute is not None:
                issues.append(
                    ValidationIssue(
                        code="duplicate_column_mapping",
                        message=(
                            f"column {canonical!r} is already mapped by "
                            f"attribute {first_attribute!r}"
                        ),
                        attribute=mapping.attribute,
                        column=canonical,
                    )
                )
                continue

            mapped_by[key] = mapping.attribute

    return tuple(issues)


def canonicalize_proposal(
    schema: TableSchema, proposal: ConceptProposal
) -> ConceptProposal:
    """Return a copy whose columns use the schema's exact physical spelling.

    Callers should validate first; unknown columns raise ``ValueError``.
    """
    canonical = {_key(column.name): column.name for column in schema.columns}
    attributes: list[AttributeMapping] = []

    for mapping in proposal.attributes:
        names: list[str] = []
        for requested in mapping.column_names:
            name = canonical.get(_key(requested))
            if name is None:
                raise ValueError(
                    f"cannot canonicalize unknown column {requested!r}"
                )
            names.append(name)
        attributes.append(
            AttributeMapping(
                attribute=mapping.attribute,
                column_names=tuple(names),
            )
        )

    return ConceptProposal(
        concept_name=proposal.concept_name,
        description=proposal.description,
        attributes=tuple(attributes),
    )


def validate_candidate(
    schema: TableSchema, candidate: Candidate
) -> tuple[ValidationIssue, ...]:
    """Validate the table reference and every mapping in an existing candidate."""
    issues: list[ValidationIssue] = []

    if _key(candidate.source_table) != _key(schema.qualified_name):
        issues.append(
            ValidationIssue(
                code="table_mismatch",
                message=(
                    f"candidate targets {candidate.source_table!r} but the "
                    f"schema is {schema.qualified_name!r}"
                ),
            )
        )

    issues.extend(validate_proposal(schema, candidate.concept))
    return tuple(issues)
