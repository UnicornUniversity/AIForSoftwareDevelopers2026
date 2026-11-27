"""Deterministic prompt assembly for structure-first discovery.

Prompt construction is deliberately separate from LLM invocation. The same structural
evidence and configuration always produce the same messages and fingerprint. DDL inclusion is
budgeted deterministically and every omission or truncation is recorded as a warning so the
model and the reviewer know the evidence is incomplete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..errors import DiscoveryInputError
from ..prompts import PromptRegistry
from .evidence import StructuralEvidence
from .schema import discovery_output_schema_json

PROMPT_NAME = "discover_semantics"
DEFAULT_MAX_DDL_CHARS_PER_OBJECT = 4000
DEFAULT_MAX_TOTAL_DDL_CHARS = 20000


@dataclass(frozen=True)
class PromptBundle:
    """Rendered, fingerprinted discovery prompt."""

    messages: tuple[BaseMessage, ...]
    prompt_version: str
    prompt_sha256: str
    evidence_sha256: str
    object_count: int
    ddl_included: int
    truncated_ddl: tuple[str, ...]
    warnings: tuple[str, ...]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _message_role(message: BaseMessage) -> str:
    return {
        "system": "system",
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
        "function": "function",
    }.get(message.type, message.type)


def _prompt_sha256(messages: tuple[BaseMessage, ...]) -> str:
    payload = [
        {"role": _message_role(message), "content": message.content}
        for message in messages
    ]
    return _sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _ddl_payload(
    evidence: StructuralEvidence,
    physical_id: str,
    *,
    include_ddl: bool,
    remaining: int,
    per_object_limit: int,
    warnings: list[str],
    truncated: list[str],
) -> tuple[dict[str, Any] | None, int]:
    """Return the DDL section for one object and the characters consumed."""

    record = evidence.ddl.get(physical_id)
    if record is None:
        return None, 0
    if not include_ddl:
        return None, 0
    if remaining <= 0:
        warnings.append(
            f"DDL for {physical_id} was omitted because the total prompt DDL budget "
            "was exhausted."
        )
        return {
            "included": False,
            "reason": "total prompt DDL budget exhausted",
            "provenance": record.provenance,
            "is_original_text": record.is_original_text,
        }, 0
    limit = min(per_object_limit, remaining)
    text = record.text
    if len(text) > limit:
        omitted = len(text) - limit
        text = text[:limit] + (
            f"\n-- [truncated: {omitted} characters omitted from the prompt]\n"
        )
        truncated.append(physical_id)
        warnings.append(
            f"DDL for {physical_id} was truncated by {omitted} characters to keep the "
            "prompt bounded."
        )
    return {
        "included": True,
        "provenance": record.provenance,
        "is_original_text": record.is_original_text,
        "text": text,
    }, len(text)


def build_ddl_section(
    evidence: StructuralEvidence,
    physical_id: str,
    *,
    include_ddl: bool,
    remaining: int,
    per_object_limit: int,
    warnings: list[str],
    truncated: list[str],
) -> tuple[dict[str, Any] | None, int]:
    """Public wrapper used by the object-level prompt builder."""

    return _ddl_payload(
        evidence,
        physical_id,
        include_ddl=include_ddl,
        remaining=remaining,
        per_object_limit=per_object_limit,
        warnings=warnings,
        truncated=truncated,
    )


def prompt_fingerprint(messages: tuple[BaseMessage, ...]) -> str:
    """Return the deterministic SHA-256 fingerprint of rendered messages."""

    return _prompt_sha256(messages)


def text_sha256(value: str) -> str:
    """Return the SHA-256 hex digest of a UTF-8 string."""

    return _sha256_text(value)


def build_discovery_prompt(
    evidence: StructuralEvidence,
    registry: PromptRegistry,
    *,
    include_ddl: bool = True,
    max_ddl_chars_per_object: int = DEFAULT_MAX_DDL_CHARS_PER_OBJECT,
    max_total_ddl_chars: int = DEFAULT_MAX_TOTAL_DDL_CHARS,
) -> PromptBundle:
    """Assemble the deterministic discovery prompt from physical evidence."""

    if not evidence.metadata.objects:
        raise DiscoveryInputError(
            "The DDL Repository contains no tables or views; there are no structural "
            "facts to discover."
        )
    if max_ddl_chars_per_object <= 0 or max_total_ddl_chars <= 0:
        raise DiscoveryInputError("DDL prompt budgets must be positive.")

    warnings: list[str] = list(evidence.warnings)
    truncated: list[str] = []
    ddl_included = 0
    ddl_used = 0
    objects: list[dict[str, Any]] = []
    for table in evidence.metadata.objects:
        payload = table.model_dump(mode="json", by_alias=True)
        ddl_section, consumed = _ddl_payload(
            evidence,
            table.physical_id,
            include_ddl=include_ddl,
            remaining=max_total_ddl_chars - ddl_used,
            per_object_limit=max_ddl_chars_per_object,
            warnings=warnings,
            truncated=truncated,
        )
        ddl_used += consumed
        if ddl_section is not None and ddl_section.get("included"):
            ddl_included += 1
        payload["ddl"] = ddl_section
        objects.append(payload)

    if include_ddl and not evidence.ddl:
        warnings.append(
            "No per-object SQL DDL artifacts are available; proposals rely on the "
            "normalized structural metadata only."
        )

    evidence_payload = {
        "database": {
            "platform": evidence.database.platform,
            "name": evidence.database.database,
        },
        "snapshot_id": evidence.snapshot_id,
        "schemas": [schema.name for schema in evidence.metadata.schemas],
        "objects": objects,
        "extraction_issues": [
            issue.model_dump(mode="json") for issue in evidence.metadata.issues
        ],
        "warnings": list(_dedupe(warnings)),
    }
    evidence_json = json.dumps(
        evidence_payload, indent=2, sort_keys=True, ensure_ascii=False
    )

    entry = registry.get(PROMPT_NAME)
    rendered = entry.render(schema_json=discovery_output_schema_json())
    instruction = "\n\n".join(str(message.content) for message in rendered)
    messages = (
        SystemMessage(content=instruction),
        HumanMessage(content="STRUCTURAL EVIDENCE (JSON):\n" + evidence_json),
    )

    return PromptBundle(
        messages=messages,
        prompt_version=entry.version,
        prompt_sha256=_prompt_sha256(messages),
        evidence_sha256=_sha256_text(evidence_json),
        object_count=len(objects),
        ddl_included=ddl_included,
        truncated_ddl=tuple(truncated),
        warnings=_dedupe(warnings),
    )
