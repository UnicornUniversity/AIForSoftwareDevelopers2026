"""Construction of reviewable candidates from validated proposals."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from uda.models import Candidate, ConceptProposal, TableSchema
from uda.schema import schema_version as schema_fingerprint
from uda.validation import (
    ValidationIssue,
    canonicalize_proposal,
    validate_proposal,
)


class CandidateRejectedError(ValueError):
    """Raised when a proposal fails physical-reference validation."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        codes = ", ".join(sorted({issue.code for issue in issues}))
        super().__init__(f"candidate rejected: {len(issues)} issue(s) [{codes}]")


def build_candidate(
    schema: TableSchema,
    proposal: ConceptProposal,
    *,
    candidate_id: UUID | None = None,
    created_at: datetime | None = None,
) -> Candidate:
    """Build a ``pending_review`` candidate, refusing invalid physical references."""
    issues = validate_proposal(schema, proposal)
    if issues:
        raise CandidateRejectedError(issues)

    return Candidate(
        candidate_id=candidate_id or uuid4(),
        created_at=created_at or datetime.now(UTC),
        source_table=schema.qualified_name,
        schema_version=schema_fingerprint(schema),
        concept=canonicalize_proposal(schema, proposal),
    )
