"""Compact LangGraph workflow for structure-first discovery.

The graph loads evidence, assembles a deterministic prompt, invokes the configured provider
once, validates the response, and persists only a fully valid proposal batch. There is no
automatic retry and no write after a validation failure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..errors import ProposalValidationError, UDAError
from ..llm.base import LLMClient
from ..prompts import PromptRegistry
from ..tracing.base import Tracer
from .evidence import load_ddl_repository
from .models import ProposalBatch
from .prompt import build_discovery_prompt
from .proposals import ProposalRepositoryWriter
from .state import DiscoveryState
from .validation import build_proposals, parse_discovery_output


@dataclass(frozen=True)
class DiscoveryRunConfig:
    """Non-secret provider metadata recorded with generated proposals."""

    provider: str
    model: str
    temperature: float
    max_tokens: int


def _merge_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for value in group:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return tuple(result)


def _safe_error(prefix: str, exc: Exception) -> str:
    if isinstance(exc, UDAError):
        message = " ".join(str(exc).split())
    else:
        message = type(exc).__name__
    return f"{prefix}: {message[:500]}"


def build_discovery_graph(
    llm: LLMClient,
    tracer: Tracer,
    *,
    registry: PromptRegistry,
    proposals_root: Path | str,
    run_config: DiscoveryRunConfig,
    project_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> Any:
    """Build and compile the Phase 3 discovery graph."""

    graph: StateGraph[DiscoveryState] = StateGraph(DiscoveryState)
    root = Path(proposals_root)

    def load_evidence(state: DiscoveryState) -> dict[str, Any]:
        repository = state.get("ddl_repository")
        if not repository:
            return {
                "status": "failed",
                "error": "No DDL Repository was supplied for discovery.",
            }
        try:
            with tracer.span("load_evidence", node="load_evidence"):
                evidence = load_ddl_repository(Path(repository))
        except Exception as exc:  # noqa: BLE001 - converted to an observable failure
            with tracer.span(
                "load_evidence_failed",
                node="load_evidence",
                error_class=type(exc).__name__,
            ):
                pass
            return {
                "status": "failed",
                "error": _safe_error("Could not load the DDL Repository", exc),
            }
        return {"evidence": evidence, "warnings": evidence.warnings}

    def assemble_prompt(state: DiscoveryState) -> dict[str, Any]:
        evidence = state.get("evidence")
        if evidence is None:
            return {
                "status": "failed",
                "error": "Discovery reached prompt assembly without structural evidence.",
            }
        try:
            with tracer.span("assemble_prompt", node="assemble_prompt"):
                prompt = build_discovery_prompt(
                    evidence,
                    registry,
                    include_ddl=state.get("include_ddl", True),
                )
        except Exception as exc:  # noqa: BLE001 - converted to an observable failure
            with tracer.span(
                "assemble_prompt_failed",
                node="assemble_prompt",
                error_class=type(exc).__name__,
            ):
                pass
            return {
                "status": "failed",
                "error": _safe_error("Could not assemble the discovery prompt", exc),
            }
        return {
            "prompt": prompt,
            "warnings": _merge_warnings(
                state.get("warnings", ()), prompt.warnings
            ),
        }

    def invoke_llm(state: DiscoveryState) -> dict[str, Any]:
        prompt = state.get("prompt")
        if prompt is None:
            return {
                "status": "failed",
                "error": "Discovery reached provider invocation without a prompt.",
            }
        started = time.perf_counter()
        try:
            with tracer.generation(
                "discover_semantics",
                provider=run_config.provider,
                model=run_config.model,
                prompt_version=prompt.prompt_version,
            ):
                response = llm.invoke(prompt.messages)
        except Exception as exc:  # noqa: BLE001 - provider failures are external
            with tracer.span(
                "invoke_llm_failed",
                node="invoke_llm",
                error_class=type(exc).__name__,
            ):
                pass
            return {
                "status": "failed",
                "error": _safe_error(
                    "The LLM provider call failed; no retry was attempted", exc
                ),
            }
        latency_ms = int((time.perf_counter() - started) * 1000)
        with tracer.span("invoke_llm", node="invoke_llm", latency_ms=latency_ms):
            pass
        if not isinstance(response, str):
            return {
                "status": "failed",
                "error": "The LLM provider returned a non-text response.",
            }
        return {"raw_response": response}

    def parse_output(state: DiscoveryState) -> dict[str, Any]:
        raw = state.get("raw_response")
        evidence = state.get("evidence")
        if raw is None or evidence is None:
            return {
                "status": "failed",
                "error": "Discovery reached validation without a response or evidence.",
            }
        try:
            with tracer.span("parse_output", node="parse_output"):
                output = parse_discovery_output(raw)
                proposals = build_proposals(output, evidence)
        except ProposalValidationError as exc:
            with tracer.span(
                "validation_failed",
                node="parse_output",
                validation_outcome="failed",
            ):
                pass
            return {
                "status": "failed",
                "validation_errors": exc.errors,
                "error": "Proposal validation failed; no records were written.",
            }
        except Exception as exc:  # noqa: BLE001 - converted to an observable failure
            with tracer.span(
                "parse_output_failed",
                node="parse_output",
                error_class=type(exc).__name__,
            ):
                pass
            return {
                "status": "failed",
                "error": _safe_error("Could not validate the LLM response", exc),
            }
        with tracer.span(
            "validation_passed",
            node="parse_output",
            validation_outcome="passed",
        ):
            pass
        if proposals.is_empty:
            return {
                "output": output,
                "proposals": proposals,
                "status": "no_proposals",
                "validation_errors": (),
            }
        return {
            "output": output,
            "proposals": proposals,
            "validation_errors": (),
        }

    def no_proposals(state: DiscoveryState) -> dict[str, Any]:
        with tracer.span("no_proposals", node="no_proposals"):
            pass
        return {"status": "no_proposals"}

    def persist_proposals(state: DiscoveryState) -> dict[str, Any]:
        proposals: ProposalBatch | None = state.get("proposals")
        prompt = state.get("prompt")
        evidence = state.get("evidence")
        repository = state.get("ddl_repository")
        if proposals is None or prompt is None or evidence is None or not repository:
            return {
                "status": "failed",
                "error": "Discovery reached persistence without complete run state.",
            }
        writer = ProposalRepositoryWriter(
            root,
            project_root=project_root,
            clock=clock,
            run_id_factory=run_id_factory,
        )
        try:
            with tracer.span("persist_proposals", node="persist_proposals"):
                result = writer.write(
                    proposals,
                    ddl_repository=repository,
                    snapshot_id=evidence.snapshot_id,
                    prompt_version=prompt.prompt_version,
                    prompt_sha256=prompt.prompt_sha256,
                    provider=run_config.provider,
                    model=run_config.model,
                    temperature=run_config.temperature,
                    max_tokens=run_config.max_tokens,
                    warnings=_merge_warnings(
                        state.get("warnings", ()), proposals.warnings
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - converted to an observable failure
            with tracer.span(
                "persist_failed",
                node="persist_proposals",
                error_class=type(exc).__name__,
            ):
                pass
            return {
                "status": "failed",
                "error": _safe_error("Could not persist proposals", exc),
            }
        return {
            "write_result": result,
            "status": result.status,
            "warnings": _merge_warnings(
                state.get("warnings", ()), proposals.warnings
            ),
        }

    def fail(state: DiscoveryState) -> dict[str, Any]:
        with tracer.span(
            "fail", node="fail", validation_outcome="failed"
        ):
            pass
        updates: dict[str, Any] = {"status": "failed"}
        if not state.get("error"):
            updates["error"] = "Discovery failed."
        return updates

    def route_after_load(state: DiscoveryState) -> str:
        return "fail" if state.get("status") == "failed" else "assemble_prompt"

    def route_after_prompt(state: DiscoveryState) -> str:
        return "fail" if state.get("status") == "failed" else "invoke_llm"

    def route_after_llm(state: DiscoveryState) -> str:
        return "fail" if state.get("status") == "failed" else "parse_output"

    def route_after_parse(state: DiscoveryState) -> str:
        if state.get("status") == "failed":
            return "fail"
        if state.get("status") == "no_proposals":
            return "no_proposals"
        return "persist_proposals"

    def route_after_persist(state: DiscoveryState) -> str:
        if state.get("status") == "failed":
            return "fail"
        if state.get("status") == "no_proposals":
            return "no_proposals"
        return "done"

    graph.add_node("load_evidence", load_evidence)
    graph.add_node("assemble_prompt", assemble_prompt)
    graph.add_node("invoke_llm", invoke_llm)
    graph.add_node("parse_output", parse_output)
    graph.add_node("persist_proposals", persist_proposals)
    graph.add_node("no_proposals", no_proposals)
    graph.add_node("fail", fail)

    graph.add_edge(START, "load_evidence")
    graph.add_conditional_edges(
        "load_evidence",
        route_after_load,
        {"assemble_prompt": "assemble_prompt", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "assemble_prompt",
        route_after_prompt,
        {"invoke_llm": "invoke_llm", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "invoke_llm",
        route_after_llm,
        {"parse_output": "parse_output", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "parse_output",
        route_after_parse,
        {
            "persist_proposals": "persist_proposals",
            "no_proposals": "no_proposals",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "persist_proposals",
        route_after_persist,
        {"done": END, "no_proposals": "no_proposals", "fail": "fail"},
    )
    graph.add_edge("no_proposals", END)
    graph.add_edge("fail", END)

    return graph.compile()
