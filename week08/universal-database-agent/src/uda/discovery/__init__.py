"""Structure-first semantic discovery (Phase 3).

Phase 3 reads the Phase 2 DDL Repository and produces reviewable semantic proposals under
``data/knowledge/proposals/``. It never writes approved semantic records, never approves a
proposal, and never uses the database as a write target.
"""

from .models import (
    ConceptAttribute,
    ConceptProposal,
    DiscoveryConcept,
    DiscoveryMapping,
    DiscoveryOutput,
    DiscoveryRelationship,
    GenerationMetadata,
    MappingProposal,
    ProposalBatch,
    RelationshipProposal,
    SourceReference,
    make_mapping_id,
    make_relationship_id,
    make_semantic_id,
)

__all__ = [
    "ConceptAttribute",
    "ConceptProposal",
    "DiscoveryConcept",
    "DiscoveryMapping",
    "DiscoveryOutput",
    "DiscoveryRelationship",
    "GenerationMetadata",
    "MappingProposal",
    "ProposalBatch",
    "RelationshipProposal",
    "SourceReference",
    "make_mapping_id",
    "make_relationship_id",
    "make_semantic_id",
]
