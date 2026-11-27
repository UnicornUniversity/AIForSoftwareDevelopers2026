"""Semantic proposal models and stable identity derivation.

Two layers are kept deliberately separate:

* ``Discovery*`` models describe the untrusted JSON contract returned by the LLM. They use
  local ``ref`` values and contain no status or application-assigned identity.
* ``*Proposal`` models are the validated records persisted under ``data/knowledge/
  proposals/``. The application derives their identities and forces status ``proposed``.

Physical evidence and inferred meaning remain distinct: a proposal carries source references
to the physical facts and a separate rationale explaining the interpretation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..errors import ProposalValidationError

PROPOSAL_SCHEMA_VERSION = "1.0"

type Confidence = Literal["low", "medium", "high"]
type SourceKind = Literal[
    "object", "column", "primary_key", "foreign_key", "index", "ddl"
]
type MappingLevel = Literal["object", "column"]
type ProposalStatus = Literal["proposed"]
type DdlProvenance = Literal["smo_scripter", "server_module_definition"]

_SEMANTIC_ID_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SEMANTIC_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAPPING_ID_PATTERN = re.compile(r"^mapping-[0-9a-f]{16}$")
_RELATIONSHIP_ID_PATTERN = re.compile(r"^relationship-[0-9a-f]{16}$")
_REF_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
_RELATIONSHIP_TYPE_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class ProposalModel(BaseModel):
    """Strict, immutable base for every proposal-layer record."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceReference(ProposalModel):
    """A concrete physical fact supporting a proposal."""

    physical_id: str = Field(min_length=1, max_length=500)
    kind: SourceKind
    detail: str = Field(min_length=1, max_length=500)
    ddl_provenance: DdlProvenance | None = None
    is_original_text: bool | None = None


class GenerationMetadata(ProposalModel):
    """Non-secret run metadata repeated on each record for independent review."""

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=50)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=1, max_length=200)
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(gt=0)


class ConceptAttribute(ProposalModel):
    """A candidate semantic property or attribute of a concept."""

    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)
    unit: str | None = Field(default=None, max_length=100)
    allowed_values: tuple[str, ...] = Field(default=(), max_length=50)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None


class DiscoveryConcept(ProposalModel):
    """LLM-proposed concept, using a local ref for cross-record references."""

    ref: str = Field(pattern=_REF_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)
    domain: str | None = Field(default=None, max_length=100)
    attributes: tuple[ConceptAttribute, ...] = Field(default=(), max_length=50)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None


class DiscoveryMapping(ProposalModel):
    """LLM-proposed physical-to-concept mapping."""

    level: MappingLevel
    source_physical_id: str = Field(min_length=1, max_length=500)
    concept_ref: str = Field(pattern=_REF_PATTERN)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None


class DiscoveryRelationship(ProposalModel):
    """LLM-proposed relationship between two locally referenced concepts."""

    relationship_type: str = Field(pattern=_RELATIONSHIP_TYPE_PATTERN)
    source_concept_ref: str = Field(pattern=_REF_PATTERN)
    target_concept_ref: str = Field(pattern=_REF_PATTERN)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None


class DiscoveryOutput(ProposalModel):
    """The complete untrusted structured output expected from the LLM."""

    concepts: tuple[DiscoveryConcept, ...] = Field(max_length=200)
    mappings: tuple[DiscoveryMapping, ...] = Field(max_length=500)
    relationships: tuple[DiscoveryRelationship, ...] = Field(max_length=200)


class ConceptProposal(ProposalModel):
    """A reviewable concept proposal with an application-assigned identity."""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    kind: Literal["concept"] = "concept"
    proposal_id: str = Field(min_length=1, max_length=100)
    semantic_id: str = Field(pattern=_SEMANTIC_ID_PATTERN.pattern, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=2000)
    domain: str | None = Field(default=None, max_length=100)
    attributes: tuple[ConceptAttribute, ...] = Field(default=(), max_length=50)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None
    generation: GenerationMetadata | None = None
    status: ProposalStatus = "proposed"


class MappingProposal(ProposalModel):
    """An independently identified object↔concept or column↔concept mapping."""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    kind: Literal["mapping"] = "mapping"
    proposal_id: str = Field(min_length=1, max_length=100)
    mapping_id: str = Field(pattern=_MAPPING_ID_PATTERN.pattern)
    level: MappingLevel
    source_physical_id: str = Field(min_length=1, max_length=500)
    semantic_id: str = Field(pattern=_SEMANTIC_ID_PATTERN.pattern, max_length=80)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None
    generation: GenerationMetadata | None = None
    status: ProposalStatus = "proposed"


class RelationshipProposal(ProposalModel):
    """An independently identified semantic relationship record."""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    kind: Literal["relationship"] = "relationship"
    proposal_id: str = Field(min_length=1, max_length=100)
    relationship_id: str = Field(pattern=_RELATIONSHIP_ID_PATTERN.pattern)
    relationship_type: str = Field(pattern=_RELATIONSHIP_TYPE_PATTERN)
    source_semantic_id: str = Field(pattern=_SEMANTIC_ID_PATTERN.pattern, max_length=80)
    target_semantic_id: str = Field(pattern=_SEMANTIC_ID_PATTERN.pattern, max_length=80)
    source_references: tuple[SourceReference, ...] = Field(
        min_length=1, max_length=20
    )
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: Confidence | None = None
    generation: GenerationMetadata | None = None
    status: ProposalStatus = "proposed"


type ProposalRecord = ConceptProposal | MappingProposal | RelationshipProposal


class ProposalBatch(ProposalModel):
    """A validated, internally consistent set of final proposal records."""

    schema_version: str = PROPOSAL_SCHEMA_VERSION
    concepts: tuple[ConceptProposal, ...] = ()
    mappings: tuple[MappingProposal, ...] = ()
    relationships: tuple[RelationshipProposal, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.concepts or self.mappings or self.relationships)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "concepts": len(self.concepts),
            "mappings": len(self.mappings),
            "relationships": len(self.relationships),
        }


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def make_semantic_id(name: str) -> str:
    """Derive a platform-independent Semantic ID from a proposed business name.

    The result contains only lower-case ASCII letters, digits, and single hyphens. It does
    not encode platform, schema, table, or column names; those remain in mapping records.
    """

    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SEMANTIC_ID_NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:80].strip("-")
    if not slug:
        raise ProposalValidationError(
            [
                "A concept name must contain at least one ASCII letter or digit to "
                f"produce a stable Semantic ID (got {name!r})."
            ]
        )
    if not _SEMANTIC_ID_PATTERN.fullmatch(slug):
        raise ProposalValidationError(
            [f"Could not derive a valid Semantic ID from name {name!r}."]
        )
    return slug


def make_mapping_id(level: str, source_physical_id: str, semantic_id: str) -> str:
    """Return a stable mapping identity for one physical source and concept."""

    return f"mapping-{_digest(level, source_physical_id, semantic_id)}"


def make_relationship_id(
    relationship_type: str, source_semantic_id: str, target_semantic_id: str
) -> str:
    """Return a stable relationship identity for one type and ordered endpoints."""

    return (
        "relationship-"
        f"{_digest(relationship_type, source_semantic_id, target_semantic_id)}"
    )
