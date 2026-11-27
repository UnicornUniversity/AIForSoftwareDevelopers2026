"""Object-level discovery contracts and deterministic identity.

The object-level strategy is additive to the Phase 3 single-shot pipeline. One LLM
request is made per table. Its untrusted response describes the concept(s) the table
realizes, their semantic attributes, and mappings from table objects and columns to those
concepts. Relationships are deliberately forbidden at this layer.

Candidates produced from a response are immutable application records stored outside the
canonical Proposal Repository. No model-generated value participates in any identity.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from .models import Confidence, DiscoveryConcept, ProposalModel, SourceReference

OBJECT_OUTPUT_SCHEMA_VERSION = "1.0"
OBJECT_REQUEST_VERSION = "uda-old-v1"

_REF_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
_EXECUTION_KEY_PATTERN = r"^[0-9a-f]{64}$"
_CANDIDATE_ID_PATTERN = r"^cand-[0-9a-f]{16}$"

ObjectRole = Literal[
    "entity", "derived_result_set", "implementation_artifact", "unknown"
]
CandidateStatus = Literal[
    "succeeded",
    "failed_validation",
    "failed_transient",
    "failed_terminal",
]


class ObjectMapping(ProposalModel):
    """A mapping from a table object or column to a proposed concept.

    ``attribute_name`` optionally ties a column to one semantic attribute. When present it
    must name a real attribute of the referenced concept.
    """

    level: Literal["object", "column"]
    source_physical_id: str = Field(min_length=1, max_length=500)
    concept_ref: str = Field(pattern=_REF_PATTERN)
    attribute_name: str | None = Field(default=None, min_length=1, max_length=200)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None


class ObjectDiscoveryOutput(ProposalModel):
    """The complete untrusted structured output expected for one table."""

    object_physical_id: str = Field(min_length=1, max_length=500)
    object_kind: Literal["table", "view"]
    object_role: ObjectRole = "unknown"
    concepts: tuple[DiscoveryConcept, ...] = Field(min_length=1, max_length=5)
    mappings: tuple[ObjectMapping, ...] = Field(min_length=1, max_length=100)


class ObjectRequestRecord(ProposalModel):
    """Immutable request identity and provenance for one table."""

    schema_version: str = "1.0"
    kind: Literal["request"] = "request"
    phase: Literal["object"] = "object"
    strategy: Literal["object-level"] = "object-level"
    request_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    execution_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    object_physical_id: str = Field(min_length=1, max_length=500)
    object_kind: Literal["table", "view"]
    snapshot_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=50)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(gt=0)
    include_ddl: bool = True
    ddl_included: bool = False
    catalogue_mode: Literal["independent"] = "independent"
    output_schema_version: str = OBJECT_OUTPUT_SCHEMA_VERSION


class ObjectStatusRecord(ProposalModel):
    """Terminal execution status for one request/execution key."""

    schema_version: str = "1.0"
    kind: Literal["status"] = "status"
    execution_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    request_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    object_physical_id: str = Field(min_length=1, max_length=500)
    status: CandidateStatus
    attempts: int = Field(default=1, ge=1)
    started_at: str
    finished_at: str
    error_class: str | None = Field(default=None, max_length=200)
    errors: tuple[str, ...] = ()
    candidate_id: str | None = Field(default=None, pattern=_CANDIDATE_ID_PATTERN)
    concept_count: int = Field(default=0, ge=0)
    mapping_count: int = Field(default=0, ge=0)
    response_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class ObjectCandidate(ProposalModel):
    """A validated, immutable object-level discovery candidate.

    This is not a canonical proposal. It is never approved, merged, or published by this
    increment.
    """

    schema_version: str = OBJECT_OUTPUT_SCHEMA_VERSION
    kind: Literal["object-candidate"] = "object-candidate"
    candidate_id: str = Field(pattern=_CANDIDATE_ID_PATTERN)
    status: Literal["succeeded"] = "succeeded"
    execution_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    request_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    object_physical_id: str = Field(min_length=1, max_length=500)
    object_kind: Literal["table", "view"]
    object_role: ObjectRole
    snapshot_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=50)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(gt=0)
    concepts: tuple[DiscoveryConcept, ...] = Field(min_length=1, max_length=5)
    mappings: tuple[ObjectMapping, ...] = Field(min_length=1, max_length=100)
    validation: Literal["passed"] = "passed"
    warnings: tuple[str, ...] = ()
    generated_at: str

    @property
    def concept_count(self) -> int:
        return len(self.concepts)

    @property
    def mapping_count(self) -> int:
        return len(self.mappings)


class ObjectRunOutcome(ProposalModel):
    """Per-table result recorded in the run summary."""

    object_physical_id: str = Field(min_length=1, max_length=500)
    object_kind: Literal["table", "view"]
    status: str = Field(min_length=1, max_length=100)
    execution_key: str = Field(pattern=_EXECUTION_KEY_PATTERN)
    candidate_id: str | None = Field(default=None, pattern=_CANDIDATE_ID_PATTERN)
    concepts: int = Field(default=0, ge=0)
    mappings: int = Field(default=0, ge=0)
    validation: Literal["passed", "failed", "not_run"] = "not_run"
    errors: tuple[str, ...] = ()
    message: str | None = Field(default=None, max_length=500)


class ObjectRunRecord(ProposalModel):
    """Summary of one object-level discovery run."""

    schema_version: str = "1.0"
    kind: Literal["run"] = "run"
    strategy: Literal["object-level"] = "object-level"
    run_id: str = Field(min_length=1, max_length=100)
    status: Literal["completed", "partial", "failed", "no_tables"]
    started_at: str
    finished_at: str
    ddl_repository: str = Field(min_length=1, max_length=1000)
    snapshot_id: str = Field(min_length=1, max_length=200)
    database_platform: str = Field(min_length=1, max_length=100)
    database_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(gt=0)
    candidate_root: str = Field(min_length=1, max_length=1000)
    tables_scheduled: int = Field(ge=0)
    tables_succeeded: int = Field(ge=0)
    tables_reused: int = Field(ge=0)
    tables_failed: int = Field(ge=0)
    outcomes: tuple[ObjectRunOutcome, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def object_request_key(
    object_physical_id: str,
    snapshot_id: str,
    evidence_sha256: str,
    prompt_version: str,
    *,
    output_schema_version: str = OBJECT_OUTPUT_SCHEMA_VERSION,
) -> str:
    """Return the deterministic input identity for one table request."""

    return _digest(
        OBJECT_REQUEST_VERSION,
        "object",
        object_physical_id,
        snapshot_id,
        evidence_sha256,
        prompt_version,
        output_schema_version,
    )


def object_execution_key(
    request_key: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Return the deterministic input-plus-model identity for one request."""

    return _digest(
        request_key,
        provider,
        model,
        f"{temperature:.6f}",
        str(max_tokens),
    )


def object_candidate_id(execution_key: str) -> str:
    """Return the deterministic, name-independent candidate identity."""

    return f"cand-{_digest('object-candidate-v1', execution_key)[:16]}"
