"""Parse, validate, and turn untrusted LLM output into reviewable proposals.

Validation has two layers:

1. JSON Schema validation of the raw response, generated from the Pydantic contract.
2. Application validation against the physical evidence: source references must name real
   Physical IDs, DDL provenance must match the repository, concept references must resolve,
   identities must be unique, and rationales must explain rather than repeat.

A failure produces no partial proposal batch. The caller persists only a fully valid batch.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from ..errors import ProposalValidationError
from .evidence import StructuralEvidence
from .models import (
    ConceptProposal,
    DiscoveryConcept,
    DiscoveryOutput,
    MappingProposal,
    ProposalBatch,
    ProposalRecord,
    RelationshipProposal,
    SourceReference,
    make_mapping_id,
    make_relationship_id,
    make_semantic_id,
)
from .schema import validate_discovery_output

_MIN_RATIONALE_CHARS = 10
_MIN_RATIONALE_WORDS = 3


def _pydantic_errors(exc: ValidationError) -> tuple[str, ...]:
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        message = " ".join(str(error["msg"]).split())
        errors.append(f"{location}: {message}")
    return tuple(errors)


def parse_discovery_output(raw: str) -> DiscoveryOutput:
    """Parse and schema-validate one untrusted LLM response."""

    if not raw or not raw.strip():
        raise ProposalValidationError(["The LLM returned an empty response."])
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProposalValidationError(
            [
                "The LLM response is not valid JSON "
                f"({exc.msg} at line {exc.lineno}, column {exc.colno})."
            ]
        ) from exc
    if not isinstance(payload, dict):
        raise ProposalValidationError(
            ["The LLM response must be a JSON object."]
        )
    schema_errors = validate_discovery_output(payload)
    if schema_errors:
        raise ProposalValidationError(schema_errors)
    try:
        return DiscoveryOutput.model_validate(payload)
    except ValidationError as exc:
        raise ProposalValidationError(_pydantic_errors(exc)) from exc


def _rationale_errors(rationale: str, name: str, context: str) -> list[str]:
    text = " ".join(rationale.split())
    errors: list[str] = []
    if (
        len(text) < _MIN_RATIONALE_CHARS
        or len(text.split()) < _MIN_RATIONALE_WORDS
    ):
        errors.append(
            f"{context}.rationale: provide a concise explanation of at least "
            f"{_MIN_RATIONALE_WORDS} words, not a label."
        )
    if text.lower() == name.strip().lower():
        errors.append(
            f"{context}.rationale: the rationale must not merely repeat the name."
        )
    return errors


def _source_reference_errors(
    references: tuple[SourceReference, ...],
    evidence: StructuralEvidence,
    context: str,
) -> list[str]:
    errors: list[str] = []
    if not references:
        errors.append(f"{context}.source_references: at least one reference is required.")
        return errors
    for index, reference in enumerate(references):
        location = f"{context}.source_references[{index}]"
        known = evidence.known_ids(reference.kind)
        if reference.physical_id not in known:
            errors.append(
                f"{location}.physical_id: unknown {reference.kind} Physical ID "
                f"{reference.physical_id[:120]!r}."
            )
            continue
        if reference.kind == "ddl":
            record = evidence.ddl.get(reference.physical_id)
            if record is None:
                errors.append(
                    f"{location}.physical_id: no extracted DDL artifact exists for "
                    f"{reference.physical_id[:120]!r}."
                )
            elif (
                reference.ddl_provenance != record.provenance
                or reference.is_original_text != record.is_original_text
            ):
                errors.append(
                    f"{location}: DDL provenance must match the repository "
                    f"({record.provenance}, is_original_text={record.is_original_text})."
                )
        elif (
            reference.ddl_provenance is not None
            or reference.is_original_text is not None
        ):
            errors.append(
                f"{location}: DDL provenance fields are only valid for kind 'ddl'."
            )
    return errors


def _attribute_errors(
    concept: DiscoveryConcept,
    evidence: StructuralEvidence,
    context: str,
) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    for index, attribute in enumerate(concept.attributes):
        attribute_context = f"{context}.attributes[{index}]"
        if attribute.name in names:
            errors.append(
                f"{attribute_context}.name: duplicate attribute name "
                f"{attribute.name[:120]!r}."
            )
        names.add(attribute.name)
        errors.extend(
            _source_reference_errors(
                attribute.source_references, evidence, attribute_context
            )
        )
        errors.extend(
            _rationale_errors(
                attribute.rationale, attribute.name, attribute_context
            )
        )
        if len(set(attribute.allowed_values)) != len(attribute.allowed_values):
            errors.append(
                f"{attribute_context}.allowed_values: values must be unique."
            )
    return errors


def _build_concepts(
    output: DiscoveryOutput,
    evidence: StructuralEvidence,
) -> tuple[dict[str, ConceptProposal], list[str]]:
    concepts: dict[str, ConceptProposal] = {}
    errors: list[str] = []
    semantic_ids: set[str] = set()
    for index, concept in enumerate(output.concepts):
        context = f"concepts[{index}]"
        if concept.ref in concepts:
            errors.append(
                f"{context}.ref: duplicate concept ref {concept.ref[:120]!r}."
            )
        try:
            semantic_id = make_semantic_id(concept.name)
        except ProposalValidationError as exc:
            errors.extend(f"{context}: {message}" for message in exc.errors)
            continue
        if semantic_id in semantic_ids:
            errors.append(
                f"{context}.name: duplicate Semantic ID {semantic_id!r}; concept "
                "names must produce distinct identities."
            )
        semantic_ids.add(semantic_id)
        errors.extend(
            _source_reference_errors(concept.source_references, evidence, context)
        )
        errors.extend(
            _rationale_errors(concept.rationale, concept.name, context)
        )
        errors.extend(_attribute_errors(concept, evidence, context))
        concepts[concept.ref] = ConceptProposal(
            proposal_id=semantic_id,
            semantic_id=semantic_id,
            name=concept.name,
            definition=concept.definition,
            domain=concept.domain,
            attributes=concept.attributes,
            source_references=concept.source_references,
            rationale=concept.rationale,
            confidence=concept.confidence,
        )
    return concepts, errors


def _build_mappings(
    output: DiscoveryOutput,
    concepts: dict[str, ConceptProposal],
    evidence: StructuralEvidence,
) -> tuple[list[MappingProposal], list[str]]:
    mappings: list[MappingProposal] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, mapping in enumerate(output.mappings):
        context = f"mappings[{index}]"
        concept = concepts.get(mapping.concept_ref)
        if concept is None:
            errors.append(
                f"{context}.concept_ref: unknown concept ref "
                f"{mapping.concept_ref[:120]!r}."
            )
        known = (
            evidence.object_ids
            if mapping.level == "object"
            else evidence.column_ids
        )
        if mapping.source_physical_id not in known:
            errors.append(
                f"{context}.source_physical_id: unknown {mapping.level} Physical ID "
                f"{mapping.source_physical_id[:120]!r}."
            )
        errors.extend(
            _source_reference_errors(mapping.source_references, evidence, context)
        )
        errors.extend(
            _rationale_errors(
                mapping.rationale,
                mapping.concept_ref,
                context,
            )
        )
        if concept is None:
            continue
        mapping_id = make_mapping_id(
            mapping.level, mapping.source_physical_id, concept.semantic_id
        )
        if mapping_id in seen_ids:
            errors.append(
                f"{context}: duplicate mapping identity {mapping_id!r}; the same "
                "physical source may map to a concept only once per run."
            )
            continue
        seen_ids.add(mapping_id)
        mappings.append(
            MappingProposal(
                proposal_id=mapping_id,
                mapping_id=mapping_id,
                level=mapping.level,
                source_physical_id=mapping.source_physical_id,
                semantic_id=concept.semantic_id,
                source_references=mapping.source_references,
                rationale=mapping.rationale,
                confidence=mapping.confidence,
            )
        )
    return mappings, errors


def _build_relationships(
    output: DiscoveryOutput,
    concepts: dict[str, ConceptProposal],
    evidence: StructuralEvidence,
) -> tuple[list[RelationshipProposal], list[str]]:
    relationships: list[RelationshipProposal] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, relationship in enumerate(output.relationships):
        context = f"relationships[{index}]"
        source = concepts.get(relationship.source_concept_ref)
        target = concepts.get(relationship.target_concept_ref)
        if source is None:
            errors.append(
                f"{context}.source_concept_ref: unknown concept ref "
                f"{relationship.source_concept_ref[:120]!r}."
            )
        if target is None:
            errors.append(
                f"{context}.target_concept_ref: unknown concept ref "
                f"{relationship.target_concept_ref[:120]!r}."
            )
        errors.extend(
            _source_reference_errors(
                relationship.source_references, evidence, context
            )
        )
        errors.extend(
            _rationale_errors(
                relationship.rationale,
                relationship.relationship_type.replace("-", " ").replace("_", " "),
                context,
            )
        )
        if source is None or target is None:
            continue
        relationship_id = make_relationship_id(
            relationship.relationship_type,
            source.semantic_id,
            target.semantic_id,
        )
        if relationship_id in seen_ids:
            errors.append(
                f"{context}: duplicate relationship identity {relationship_id!r}."
            )
            continue
        seen_ids.add(relationship_id)
        relationships.append(
            RelationshipProposal(
                proposal_id=relationship_id,
                relationship_id=relationship_id,
                relationship_type=relationship.relationship_type,
                source_semantic_id=source.semantic_id,
                target_semantic_id=target.semantic_id,
                source_references=relationship.source_references,
                rationale=relationship.rationale,
                confidence=relationship.confidence,
            )
        )
    return relationships, errors


def build_proposals(
    output: DiscoveryOutput, evidence: StructuralEvidence
) -> ProposalBatch:
    """Validate a parsed response against evidence and build final proposals."""

    errors: list[str] = []
    if not output.concepts and (output.mappings or output.relationships):
        errors.append(
            "Mappings and relationships require at least one concept proposal."
        )
    concepts, concept_errors = _build_concepts(output, evidence)
    mappings, mapping_errors = _build_mappings(output, concepts, evidence)
    relationships, relationship_errors = _build_relationships(
        output, concepts, evidence
    )
    errors.extend(concept_errors)
    errors.extend(mapping_errors)
    errors.extend(relationship_errors)
    if errors:
        raise ProposalValidationError(errors)
    return ProposalBatch(
        concepts=tuple(sorted(concepts.values(), key=lambda item: item.semantic_id)),
        mappings=tuple(sorted(mappings, key=lambda item: item.mapping_id)),
        relationships=tuple(
            sorted(relationships, key=lambda item: item.relationship_id)
        ),
        warnings=evidence.warnings,
    )


def rationale_errors(rationale: str, name: str, context: str) -> list[str]:
    """Public wrapper reused by the object-level validator."""

    return _rationale_errors(rationale, name, context)


def source_reference_errors(
    references: tuple[SourceReference, ...],
    evidence: StructuralEvidence,
    context: str,
) -> list[str]:
    """Public wrapper reused by the object-level validator."""

    return _source_reference_errors(references, evidence, context)


def attribute_errors(
    concept: DiscoveryConcept,
    evidence: StructuralEvidence,
    context: str,
) -> list[str]:
    """Public wrapper reused by the object-level validator."""

    return _attribute_errors(concept, evidence, context)


def validate_record_evidence(
    records: Iterable[ProposalRecord], evidence: StructuralEvidence
) -> tuple[str, ...]:
    """Re-check persisted records against the physical evidence and rationale rules."""

    errors: list[str] = []
    for record in records:
        context = f"{record.kind} {record.proposal_id}"
        errors.extend(
            _source_reference_errors(record.source_references, evidence, context)
        )
        if isinstance(record, ConceptProposal):
            errors.extend(_rationale_errors(record.rationale, record.name, context))
            for index, attribute in enumerate(record.attributes):
                attribute_context = f"{context}.attributes[{index}]"
                errors.extend(
                    _source_reference_errors(
                        attribute.source_references, evidence, attribute_context
                    )
                )
                errors.extend(
                    _rationale_errors(
                        attribute.rationale, attribute.name, attribute_context
                    )
                )
        elif isinstance(record, MappingProposal):
            known = (
                evidence.object_ids
                if record.level == "object"
                else evidence.column_ids
            )
            if record.source_physical_id not in known:
                errors.append(
                    f"{context}.source_physical_id: unknown {record.level} Physical "
                    f"ID {record.source_physical_id[:120]!r}."
                )
            errors.extend(
                _rationale_errors(record.rationale, record.semantic_id, context)
            )
        elif isinstance(record, RelationshipProposal):
            errors.extend(
                _rationale_errors(
                    record.rationale,
                    record.relationship_type.replace("-", " ").replace("_", " "),
                    context,
                )
            )
    return tuple(errors)


def validate_proposal_batch(batch: ProposalBatch) -> tuple[str, ...]:
    """Validate internal identity and endpoint consistency before persistence."""

    errors: list[str] = []
    if batch.schema_version != "1.0":
        errors.append(
            f"Unsupported proposal schema version {batch.schema_version!r}."
        )
    concepts: dict[str, ConceptProposal] = {}
    for index, concept in enumerate(batch.concepts):
        context = f"concepts[{index}]"
        if concept.proposal_id != concept.semantic_id:
            errors.append(
                f"{context}: proposal_id must equal semantic_id."
            )
        if concept.semantic_id in concepts:
            errors.append(
                f"{context}: duplicate Semantic ID {concept.semantic_id!r}."
            )
        concepts[concept.semantic_id] = concept
    mapping_ids: set[str] = set()
    for index, mapping in enumerate(batch.mappings):
        context = f"mappings[{index}]"
        expected = make_mapping_id(
            mapping.level, mapping.source_physical_id, mapping.semantic_id
        )
        if mapping.mapping_id != expected:
            errors.append(
                f"{context}: mapping_id does not match its stable identity."
            )
        if mapping.proposal_id != mapping.mapping_id:
            errors.append(f"{context}: proposal_id must equal mapping_id.")
        if mapping.mapping_id in mapping_ids:
            errors.append(
                f"{context}: duplicate mapping identity {mapping.mapping_id!r}."
            )
        mapping_ids.add(mapping.mapping_id)
        if mapping.semantic_id not in concepts:
            errors.append(
                f"{context}: semantic_id {mapping.semantic_id!r} has no concept "
                "proposal in this batch."
            )
    relationship_ids: set[str] = set()
    for index, relationship in enumerate(batch.relationships):
        context = f"relationships[{index}]"
        expected = make_relationship_id(
            relationship.relationship_type,
            relationship.source_semantic_id,
            relationship.target_semantic_id,
        )
        if relationship.relationship_id != expected:
            errors.append(
                f"{context}: relationship_id does not match its stable identity."
            )
        if relationship.proposal_id != relationship.relationship_id:
            errors.append(
                f"{context}: proposal_id must equal relationship_id."
            )
        if relationship.relationship_id in relationship_ids:
            errors.append(
                f"{context}: duplicate relationship identity "
                f"{relationship.relationship_id!r}."
            )
        relationship_ids.add(relationship.relationship_id)
        for field_name, value in (
            ("source_semantic_id", relationship.source_semantic_id),
            ("target_semantic_id", relationship.target_semantic_id),
        ):
            if value not in concepts:
                errors.append(
                    f"{context}.{field_name}: {value!r} has no concept proposal in "
                    "this batch."
                )
    return tuple(errors)
