"""Parse and validate one table's object-level discovery response.

Validation has two layers: JSON Schema generated from the Pydantic contract, then
application checks against the physical evidence. A table may be described only with its
own object and columns; concept references, attributes, and mappings must all resolve.
An invalid response never becomes a candidate.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..errors import ProposalValidationError
from ..metadata.models import TableMetadata
from .evidence import StructuralEvidence
from .models import DiscoveryConcept, make_semantic_id
from .object_models import ObjectDiscoveryOutput
from .object_schema import validate_object_output_schema
from .validation import (
    attribute_errors,
    rationale_errors,
    source_reference_errors,
)


def _pydantic_errors(exc: ValidationError) -> tuple[str, ...]:
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        message = " ".join(str(error["msg"]).split())
        errors.append(f"{location}: {message}")
    return tuple(errors)


def parse_object_output(raw: str) -> ObjectDiscoveryOutput:
    """Parse and schema-validate one table's untrusted LLM response."""

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
        raise ProposalValidationError(["The LLM response must be a JSON object."])
    schema_errors = validate_object_output_schema(payload)
    if schema_errors:
        raise ProposalValidationError(schema_errors)
    try:
        return ObjectDiscoveryOutput.model_validate(payload)
    except ValidationError as exc:
        raise ProposalValidationError(_pydantic_errors(exc)) from exc


def _concept_errors(
    output: ObjectDiscoveryOutput,
    concepts_by_ref: dict[str, DiscoveryConcept],
    evidence: StructuralEvidence,
) -> list[str]:
    errors: list[str] = []
    semantic_ids: set[str] = set()
    for index, concept in enumerate(output.concepts):
        context = f"concepts[{index}]"
        if concept.ref in concepts_by_ref:
            errors.append(
                f"{context}.ref: duplicate concept ref {concept.ref[:120]!r}."
            )
        concepts_by_ref[concept.ref] = concept
        try:
            semantic_id = make_semantic_id(concept.name)
        except ProposalValidationError as exc:
            errors.extend(f"{context}: {message}" for message in exc.errors)
        else:
            if semantic_id in semantic_ids:
                errors.append(
                    f"{context}.name: duplicate Semantic ID {semantic_id!r}; concept "
                    "names must produce distinct identities."
                )
            semantic_ids.add(semantic_id)
        errors.extend(
            source_reference_errors(concept.source_references, evidence, context)
        )
        errors.extend(rationale_errors(concept.rationale, concept.name, context))
        errors.extend(attribute_errors(concept, evidence, context))
    return errors


def _mapping_errors(
    output: ObjectDiscoveryOutput,
    concepts_by_ref: dict[str, DiscoveryConcept],
    table: TableMetadata,
    evidence: StructuralEvidence,
) -> list[str]:
    errors: list[str] = []
    table_column_ids = {column.physical_id for column in table.columns}
    seen: set[tuple[str, str, str, str | None]] = set()
    for index, mapping in enumerate(output.mappings):
        context = f"mappings[{index}]"
        concept = concepts_by_ref.get(mapping.concept_ref)
        if concept is None:
            errors.append(
                f"{context}.concept_ref: unknown concept ref "
                f"{mapping.concept_ref[:120]!r}."
            )
        if mapping.level == "object":
            if mapping.source_physical_id != table.physical_id:
                errors.append(
                    f"{context}.source_physical_id: object mappings in this request "
                    f"must reference {table.physical_id[:120]!r}."
                )
            if mapping.attribute_name is not None:
                errors.append(
                    f"{context}.attribute_name: attribute mappings must use level "
                    "'column'."
                )
        else:
            if mapping.source_physical_id not in table_column_ids:
                errors.append(
                    f"{context}.source_physical_id: unknown column of the requested "
                    f"table {mapping.source_physical_id[:120]!r}."
                )
            if mapping.attribute_name is not None and concept is not None:
                attribute = next(
                    (
                        item
                        for item in concept.attributes
                        if item.name == mapping.attribute_name
                    ),
                    None,
                )
                if attribute is None:
                    available = ", ".join(
                        repr(item.name) for item in concept.attributes
                    ) or "none"
                    errors.append(
                        f"{context}.attribute_name: concept "
                        f"{mapping.concept_ref[:120]!r} has no attribute "
                        f"{mapping.attribute_name[:120]!r}; declared attributes: "
                        f"{available[:300]}."
                    )
                else:
                    cited = {
                        reference.physical_id
                        for reference in attribute.source_references
                    }
                    if mapping.source_physical_id not in cited:
                        errors.append(
                            f"{context}: mapped column "
                            f"{mapping.source_physical_id[:120]!r} is not cited by "
                            f"attribute {mapping.attribute_name[:120]!r}."
                        )
        key = (
            mapping.level,
            mapping.source_physical_id,
            mapping.concept_ref,
            mapping.attribute_name,
        )
        if key in seen:
            errors.append(
                f"{context}: duplicate mapping for the same source, concept, and "
                "attribute."
            )
        seen.add(key)
        errors.extend(
            source_reference_errors(mapping.source_references, evidence, context)
        )
        errors.extend(
            rationale_errors(mapping.rationale, mapping.concept_ref, context)
        )
    return errors


def validate_object_output(
    output: ObjectDiscoveryOutput,
    table: TableMetadata,
    evidence: StructuralEvidence,
) -> tuple[str, ...]:
    """Validate a parsed object response against its table evidence.

    Returns non-fatal warnings. Raises ``ProposalValidationError`` when any error is
    found; no partial candidate may be produced.
    """

    errors: list[str] = []
    if output.object_physical_id != table.physical_id:
        errors.append(
            "object_physical_id: response does not describe the requested table "
            f"({output.object_physical_id[:120]!r})."
        )
    if output.object_kind != table.object_type:
        errors.append(
            "object_kind: response kind "
            f"{output.object_kind!r} does not match the requested "
            f"{table.object_type!r} object."
        )
    if table.object_type == "table" and output.object_role == "derived_result_set":
        errors.append(
            "object_role: a table cannot be classified as a derived result set."
        )

    concepts_by_ref: dict[str, DiscoveryConcept] = {}
    errors.extend(_concept_errors(output, concepts_by_ref, evidence))
    errors.extend(_mapping_errors(output, concepts_by_ref, table, evidence))

    mapped_refs = {mapping.concept_ref for mapping in output.mappings}
    for index, concept in enumerate(output.concepts):
        if concept.ref not in mapped_refs:
            errors.append(
                f"concepts[{index}]: no mapping references concept "
                f"{concept.ref[:120]!r}."
            )
    if not any(
        mapping.level == "object"
        and mapping.source_physical_id == table.physical_id
        for mapping in output.mappings
    ):
        errors.append(
            "mappings: at least one object-level mapping must tie the requested "
            "table to a proposed concept."
        )

    if errors:
        raise ProposalValidationError(errors)

    warnings: list[str] = []
    if not any(mapping.attribute_name is not None for mapping in output.mappings):
        warnings.append(
            "No attribute-to-column mappings were proposed; the response maps only "
            "objects or whole columns to concepts."
        )
    for concept in output.concepts:
        if not concept.attributes:
            warnings.append(
                f"Concept {concept.name[:120]!r} has no semantic attributes."
            )
    return tuple(warnings)
