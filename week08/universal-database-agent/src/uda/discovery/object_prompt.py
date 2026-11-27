"""Deterministic per-table prompt assembly for object-level discovery.

The prompt contains exactly one table's identity, structure, keys, indexes, description,
and budgeted DDL. Directly related evidence such as foreign-key endpoints stays in the
table payload, but no other table's DDL or columns are included. DDL truncation and
omission are recorded as warnings rather than silently accepted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..errors import DiscoveryInputError
from ..metadata.models import TableMetadata
from ..prompts import PromptRegistry
from .evidence import StructuralEvidence
from .object_schema import object_output_schema_json
from .prompt import build_ddl_section, prompt_fingerprint, text_sha256

PROMPT_NAME = "discover_object_semantics"
DEFAULT_MAX_DDL_CHARS_PER_OBJECT = 6000


@dataclass(frozen=True)
class ObjectPromptBundle:
    """Rendered, fingerprinted prompt for one table."""

    object_physical_id: str
    object_kind: str
    messages: tuple[BaseMessage, ...]
    prompt_version: str
    prompt_sha256: str
    evidence_sha256: str
    ddl_included: bool
    truncated_ddl: bool
    warnings: tuple[str, ...]


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def build_object_discovery_prompt(
    evidence: StructuralEvidence,
    table: TableMetadata,
    registry: PromptRegistry,
    *,
    include_ddl: bool = True,
    max_ddl_chars_per_object: int = DEFAULT_MAX_DDL_CHARS_PER_OBJECT,
) -> ObjectPromptBundle:
    """Assemble the bounded prompt for one table."""

    if table.physical_id not in evidence.object_ids:
        raise DiscoveryInputError(
            "The requested object is not part of the loaded DDL Repository evidence."
        )
    if max_ddl_chars_per_object <= 0:
        raise DiscoveryInputError("The per-object DDL prompt budget must be positive.")

    warnings: list[str] = list(evidence.warnings)
    truncated: list[str] = []
    ddl_section, _consumed = build_ddl_section(
        evidence,
        table.physical_id,
        include_ddl=include_ddl,
        remaining=max_ddl_chars_per_object,
        per_object_limit=max_ddl_chars_per_object,
        warnings=warnings,
        truncated=truncated,
    )
    if include_ddl and ddl_section is None:
        warnings.append(
            f"No extracted SQL DDL is available for {table.physical_id}; the prompt "
            "relies on normalized structural metadata."
        )

    object_payload = table.model_dump(mode="json", by_alias=True)
    object_payload["ddl"] = ddl_section
    related_issues = [
        issue.model_dump(mode="json")
        for issue in evidence.metadata.issues
        if issue.object_id in (None, table.physical_id)
    ]
    evidence_payload: dict[str, Any] = {
        "database": {
            "platform": evidence.database.platform,
            "name": evidence.database.database,
        },
        "snapshot_id": evidence.snapshot_id,
        "object": object_payload,
        "extraction_issues": related_issues,
        "warnings": list(_dedupe(warnings)),
    }
    evidence_json = json.dumps(
        evidence_payload, indent=2, sort_keys=True, ensure_ascii=False
    )

    entry = registry.get(PROMPT_NAME)
    rendered = entry.render(schema_json=object_output_schema_json())
    instruction = "\n\n".join(str(message.content) for message in rendered)
    messages = (
        SystemMessage(content=instruction),
        HumanMessage(content="OBJECT EVIDENCE (JSON):\n" + evidence_json),
    )

    return ObjectPromptBundle(
        object_physical_id=table.physical_id,
        object_kind=table.object_type,
        messages=messages,
        prompt_version=entry.version,
        prompt_sha256=prompt_fingerprint(messages),
        evidence_sha256=text_sha256(evidence_json),
        ddl_included=bool(ddl_section and ddl_section.get("included")),
        truncated_ddl=table.physical_id in truncated,
        warnings=_dedupe(warnings),
    )
