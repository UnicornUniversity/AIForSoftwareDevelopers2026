"""Typed LangGraph state for structure-first discovery."""

from __future__ import annotations

from typing import TypedDict

from .evidence import StructuralEvidence
from .models import DiscoveryOutput, ProposalBatch
from .prompt import PromptBundle
from .proposals import ProposalWriteResult


class DiscoveryState(TypedDict, total=False):
    ddl_repository: str
    include_ddl: bool
    evidence: StructuralEvidence
    prompt: PromptBundle
    raw_response: str
    output: DiscoveryOutput
    proposals: ProposalBatch
    validation_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    write_result: ProposalWriteResult
    status: str
    error: str
