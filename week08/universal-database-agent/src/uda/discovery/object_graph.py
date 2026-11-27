"""Sequential object-level discovery workflow.

A compact LangGraph loop plans one bounded request per table, then processes each table in
deterministic order. Every table receives its own independent ``LLMClient.invoke`` call
unless an identical successful request already exists in the candidate store. A failure for
one table is recorded and does not abort the remaining tables. No canonical proposal is
written by this workflow.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from ..errors import (
    CandidateRepositoryError,
    DiscoveryError,
    DiscoveryInputError,
    LLMProviderError,
    ProposalValidationError,
    UDAError,
)
from ..llm.base import LLMClient
from ..metadata.models import TableMetadata
from ..prompts import PromptRegistry
from ..repository.serialization import sha256_hex
from ..tracing.base import Tracer
from .candidates import CandidateStore, format_timestamp
from .evidence import StructuralEvidence, load_ddl_repository
from .object_models import (
    ObjectCandidate,
    ObjectRequestRecord,
    ObjectRunOutcome,
    ObjectRunRecord,
    ObjectStatusRecord,
    object_candidate_id,
    object_execution_key,
    object_request_key,
)
from .object_prompt import ObjectPromptBundle, build_object_discovery_prompt
from .object_validation import parse_object_output, validate_object_output

_TRANSIENT_EXCEPTIONS = (TimeoutError, OSError, LLMProviderError)
_LIMITATIONS = (
    "Only tables are processed; views are deferred.",
    "Tables are processed sequentially with one independent LLM request each.",
    "Candidates are immutable and are never published into the canonical Proposal "
    "Repository.",
    "A terminal failure for an execution key is not retried automatically on a later run.",
)


@dataclass(frozen=True)
class ObjectDiscoveryRunConfig:
    """Non-secret provider and execution settings for an object-level run."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    include_ddl: bool = True
    max_tables: int | None = None
    max_ddl_chars_per_object: int = 6000


@dataclass(frozen=True)
class ObjectRequestPlan:
    """One table's prompt and deterministic request identity."""

    table: TableMetadata
    prompt: ObjectPromptBundle
    request: ObjectRequestRecord


@dataclass(frozen=True)
class ObjectOutcome:
    """Runtime outcome for one table."""

    object_physical_id: str
    object_kind: Literal["table", "view"]
    status: str
    execution_key: str
    candidate_id: str | None = None
    concepts: int = 0
    mappings: int = 0
    validation: str = "not_run"
    errors: tuple[str, ...] = ()
    message: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status in {"succeeded", "reused"}

    def record(self) -> ObjectRunOutcome:
        return ObjectRunOutcome(
            object_physical_id=self.object_physical_id,
            object_kind=self.object_kind,
            status=self.status,
            execution_key=self.execution_key,
            candidate_id=self.candidate_id,
            concepts=self.concepts,
            mappings=self.mappings,
            validation=self.validation,  # type: ignore[arg-type]
            errors=self.errors,
            message=self.message,
        )


@dataclass(frozen=True)
class ObjectRunResult:
    """Summary returned by the object-level workflow."""

    run_id: str
    run_path: Path | None
    status: str
    started_at: str
    finished_at: str
    tables_scheduled: int
    tables_succeeded: int
    tables_reused: int
    tables_failed: int
    outcomes: tuple[ObjectOutcome, ...]
    warnings: tuple[str, ...]
    record: ObjectRunRecord | None = None


class ObjectDiscoveryState(TypedDict, total=False):
    ddl_repository: str
    max_tables: int | None
    evidence: StructuralEvidence
    plans: tuple[ObjectRequestPlan, ...]
    index: int
    outcomes: tuple[ObjectOutcome, ...]
    run_id: str
    started_at: str
    warnings: tuple[str, ...]
    run_result: ObjectRunResult
    status: str
    error: str


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


def select_object_tables(
    evidence: StructuralEvidence, max_tables: int | None = None
) -> tuple[TableMetadata, ...]:
    """Return the deterministic table selection for an object-level run."""

    if max_tables is not None and max_tables < 1:
        raise DiscoveryInputError("--max-tables must be a positive integer.")
    tables = sorted(
        (item for item in evidence.metadata.objects if item.object_type == "table"),
        key=lambda item: item.physical_id,
    )
    if max_tables is not None:
        tables = tables[:max_tables]
    return tuple(tables)


def plan_object_requests(
    evidence: StructuralEvidence,
    registry: PromptRegistry,
    run_config: ObjectDiscoveryRunConfig,
    *,
    max_tables: int | None = None,
) -> tuple[ObjectRequestPlan, ...]:
    """Build one bounded prompt and deterministic request identity per selected table."""

    plans: list[ObjectRequestPlan] = []
    for table in select_object_tables(evidence, max_tables):
        prompt = build_object_discovery_prompt(
            evidence,
            table,
            registry,
            include_ddl=run_config.include_ddl,
            max_ddl_chars_per_object=run_config.max_ddl_chars_per_object,
        )
        request_key = object_request_key(
            table.physical_id,
            evidence.snapshot_id,
            prompt.evidence_sha256,
            prompt.prompt_version,
        )
        execution_key = object_execution_key(
            request_key,
            run_config.provider,
            run_config.model,
            run_config.temperature,
            run_config.max_tokens,
        )
        plans.append(
            ObjectRequestPlan(
                table=table,
                prompt=prompt,
                request=ObjectRequestRecord(
                    request_key=request_key,
                    execution_key=execution_key,
                    object_physical_id=table.physical_id,
                    object_kind=table.object_type,
                    snapshot_id=evidence.snapshot_id,
                    evidence_sha256=prompt.evidence_sha256,
                    prompt_version=prompt.prompt_version,
                    prompt_sha256=prompt.prompt_sha256,
                    provider=run_config.provider,
                    model=run_config.model,
                    temperature=run_config.temperature,
                    max_tokens=run_config.max_tokens,
                    include_ddl=run_config.include_ddl,
                    ddl_included=prompt.ddl_included,
                ),
            )
        )
    return tuple(plans)


def _success_outcome(
    status: str,
    candidate: ObjectCandidate,
    message: str | None = None,
) -> ObjectOutcome:
    return ObjectOutcome(
        object_physical_id=candidate.object_physical_id,
        object_kind=candidate.object_kind,
        status=status,
        execution_key=candidate.execution_key,
        candidate_id=candidate.candidate_id,
        concepts=candidate.concept_count,
        mappings=candidate.mapping_count,
        validation="passed",
        message=message,
        warnings=candidate.warnings,
    )


def _failure_outcome(
    plan: ObjectRequestPlan,
    status: str,
    errors: tuple[str, ...],
    *,
    validation: str = "not_run",
    message: str | None = None,
) -> ObjectOutcome:
    return ObjectOutcome(
        object_physical_id=plan.table.physical_id,
        object_kind=plan.table.object_type,
        status=status,
        execution_key=plan.request.execution_key,
        validation=validation,
        errors=errors,
        message=message,
    )


def _status_record(
    plan: ObjectRequestPlan,
    status: str,
    started_at: str,
    finished_at: str,
    *,
    error_class: str | None = None,
    errors: tuple[str, ...] = (),
    candidate: ObjectCandidate | None = None,
    response_sha256: str | None = None,
) -> ObjectStatusRecord:
    return ObjectStatusRecord(
        execution_key=plan.request.execution_key,
        request_key=plan.request.request_key,
        object_physical_id=plan.table.physical_id,
        status=status,  # type: ignore[arg-type]
        started_at=started_at,
        finished_at=finished_at,
        error_class=error_class,
        errors=errors,
        candidate_id=candidate.candidate_id if candidate is not None else None,
        concept_count=candidate.concept_count if candidate is not None else 0,
        mapping_count=candidate.mapping_count if candidate is not None else 0,
        response_sha256=response_sha256,
    )


def _process_plan(
    plan: ObjectRequestPlan,
    evidence: StructuralEvidence,
    store: CandidateStore,
    llm: LLMClient,
    tracer: Tracer,
    run_config: ObjectDiscoveryRunConfig,
    clock: Callable[[], datetime],
) -> ObjectOutcome:
    try:
        existing = store.lookup(plan.request.execution_key)
    except CandidateRepositoryError as exc:
        return _failure_outcome(
            plan,
            "failed_terminal",
            (_safe_error("Could not read the candidate store", exc),),
            validation="failed",
        )
    if existing is not None:
        if existing.status == "succeeded" and existing.candidate is not None:
            if (
                existing.candidate.object_physical_id != plan.table.physical_id
                or existing.candidate.request_key != plan.request.request_key
            ):
                return _failure_outcome(
                    plan,
                    "failed_validation",
                    ("Stored candidate does not match the requested table.",),
                    validation="failed",
                )
            return _success_outcome(
                "reused",
                existing.candidate,
                message="Reused an existing successful candidate; no LLM call was made.",
            )
        record = existing.status_record
        return _failure_outcome(
            plan,
            existing.status,
            record.errors if record is not None else (),
            validation=(
                "failed" if existing.status == "failed_validation" else "not_run"
            ),
            message=(
                "A terminal failure is already recorded for this execution key; no "
                "LLM call was made."
            ),
        )

    started = clock()
    started_at = format_timestamp(started)
    try:
        store.write_request(plan.request)
    except CandidateRepositoryError as exc:
        return _failure_outcome(
            plan,
            "failed_terminal",
            (_safe_error("Could not write the request record", exc),),
        )

    started_perf = time.perf_counter()
    try:
        with tracer.generation(
            "discover_object_semantics",
            provider=run_config.provider,
            model=run_config.model,
            prompt_version=plan.prompt.prompt_version,
            temperature=run_config.temperature,
            max_tokens=run_config.max_tokens,
        ):
            raw = llm.invoke(plan.prompt.messages)
    except Exception as exc:  # noqa: BLE001 - provider failures are external
        latency_ms = int((time.perf_counter() - started_perf) * 1000)
        status = (
            "failed_transient"
            if isinstance(exc, _TRANSIENT_EXCEPTIONS)
            else "failed_terminal"
        )
        errors: tuple[str, ...] = (
            _safe_error(
                "The LLM provider call failed; no retry was attempted", exc
            ),
        )
        finished_at = format_timestamp(clock())
        with tracer.span(
            "invoke_llm_failed",
            node="process_table",
            error_class=type(exc).__name__,
            latency_ms=latency_ms,
        ):
            pass
        try:
            store.write_status(
                _status_record(
                    plan,
                    status,
                    started_at,
                    finished_at,
                    error_class=type(exc).__name__,
                    errors=errors,
                )
            )
        except CandidateRepositoryError as store_exc:
            errors = (
                *errors,
                _safe_error("Could not write the status record", store_exc),
            )
        return _failure_outcome(plan, status, errors)

    latency_ms = int((time.perf_counter() - started_perf) * 1000)
    with tracer.span(
        "invoke_llm", node="process_table", latency_ms=latency_ms
    ):
        pass
    if not isinstance(raw, str):
        errors = ("The LLM provider returned a non-text response.",)
        finished_at = format_timestamp(clock())
        try:
            store.write_status(
                _status_record(
                    plan,
                    "failed_terminal",
                    started_at,
                    finished_at,
                    error_class="NonTextResponse",
                    errors=errors,
                )
            )
        except CandidateRepositoryError:
            pass
        return _failure_outcome(plan, "failed_terminal", errors)

    response_sha256 = sha256_hex(raw.encode("utf-8"))
    try:
        store.write_response_hash(plan.request.execution_key, raw)
    except CandidateRepositoryError as exc:
        return _failure_outcome(
            plan,
            "failed_terminal",
            (_safe_error("Could not record the response hash", exc),),
        )

    try:
        with tracer.span("parse_output", node="process_table"):
            output = parse_object_output(raw)
            validation_warnings = validate_object_output(
                output, plan.table, evidence
            )
    except ProposalValidationError as exc:
        finished_at = format_timestamp(clock())
        with tracer.span(
            "validation_failed",
            node="process_table",
            validation_outcome="failed",
        ):
            pass
        errors = tuple(exc.errors)
        try:
            store.write_status(
                _status_record(
                    plan,
                    "failed_validation",
                    started_at,
                    finished_at,
                    error_class=type(exc).__name__,
                    errors=errors,
                    response_sha256=response_sha256,
                )
            )
        except CandidateRepositoryError as store_exc:
            errors = (
                *errors,
                _safe_error("Could not write the status record", store_exc),
            )
        return _failure_outcome(
            plan,
            "failed_validation",
            errors,
            validation="failed",
            message="Object-level validation failed; no candidate was stored.",
        )
    except Exception as exc:  # noqa: BLE001 - converted to an observable failure
        errors = (_safe_error("Could not validate the LLM response", exc),)
        finished_at = format_timestamp(clock())
        try:
            store.write_status(
                _status_record(
                    plan,
                    "failed_terminal",
                    started_at,
                    finished_at,
                    error_class=type(exc).__name__,
                    errors=errors,
                    response_sha256=response_sha256,
                )
            )
        except CandidateRepositoryError:
            pass
        return _failure_outcome(plan, "failed_terminal", errors)

    with tracer.span(
        "validation_passed", node="process_table", validation_outcome="passed"
    ):
        pass
    finished = clock()
    finished_at = format_timestamp(finished)
    warnings = _merge_warnings(
        plan.prompt.warnings, tuple(validation_warnings)
    )
    candidate = ObjectCandidate(
        candidate_id=object_candidate_id(plan.request.execution_key),
        execution_key=plan.request.execution_key,
        request_key=plan.request.request_key,
        object_physical_id=plan.table.physical_id,
        object_kind=plan.table.object_type,
        object_role=output.object_role,
        snapshot_id=evidence.snapshot_id,
        evidence_sha256=plan.prompt.evidence_sha256,
        prompt_version=plan.prompt.prompt_version,
        prompt_sha256=plan.prompt.prompt_sha256,
        provider=run_config.provider,
        model=run_config.model,
        temperature=run_config.temperature,
        max_tokens=run_config.max_tokens,
        concepts=output.concepts,
        mappings=output.mappings,
        warnings=warnings,
        generated_at=finished_at,
    )
    try:
        store.write_result(candidate)
    except CandidateRepositoryError as exc:
        return _failure_outcome(
            plan,
            "failed_terminal",
            (_safe_error("Could not persist the candidate", exc),),
            validation="passed",
        )
    try:
        store.write_status(
            _status_record(
                plan,
                "succeeded",
                started_at,
                finished_at,
                candidate=candidate,
                response_sha256=response_sha256,
            )
        )
    except CandidateRepositoryError:
        pass
    return _success_outcome("succeeded", candidate)


def build_object_discovery_graph(
    llm: LLMClient,
    tracer: Tracer,
    *,
    registry: PromptRegistry,
    candidates_root: Path | str,
    run_config: ObjectDiscoveryRunConfig,
    project_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> Any:
    """Build and compile the sequential object-level discovery graph."""

    store = CandidateStore(Path(candidates_root), project_root=project_root)
    clock = clock or (lambda: datetime.now(UTC))
    run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)
    graph: StateGraph[ObjectDiscoveryState] = StateGraph(ObjectDiscoveryState)

    def load_evidence(state: ObjectDiscoveryState) -> dict[str, Any]:
        repository = state.get("ddl_repository")
        if not repository:
            return {
                "status": "failed",
                "error": "No DDL Repository was supplied for object-level discovery.",
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
        return {
            "evidence": evidence,
            "warnings": evidence.warnings,
            "run_id": run_id_factory(),
            "started_at": format_timestamp(clock()),
        }

    def plan_requests(state: ObjectDiscoveryState) -> dict[str, Any]:
        evidence = state.get("evidence")
        if evidence is None:
            return {
                "status": "failed",
                "error": "Object-level discovery reached planning without evidence.",
            }
        try:
            with tracer.span("plan_requests", node="plan_requests"):
                plans = plan_object_requests(
                    evidence,
                    registry,
                    run_config,
                    max_tables=state.get("max_tables", run_config.max_tables),
                )
        except Exception as exc:  # noqa: BLE001 - converted to an observable failure
            return {
                "status": "failed",
                "error": _safe_error("Could not plan object-level requests", exc),
            }
        warnings = list(state.get("warnings", ()))
        for plan in plans:
            warnings.extend(plan.prompt.warnings)
        return {
            "plans": plans,
            "index": 0,
            "outcomes": (),
            "warnings": _merge_warnings(tuple(warnings)),
        }

    def process_table(state: ObjectDiscoveryState) -> dict[str, Any]:
        plans = state.get("plans", ())
        index = state.get("index", 0)
        evidence = state.get("evidence")
        if evidence is None or index >= len(plans):
            return {
                "status": "failed",
                "error": "Object-level discovery reached an invalid processing index.",
            }
        with tracer.span("process_table", node="process_table"):
            outcome = _process_plan(
                plans[index], evidence, store, llm, tracer, run_config, clock
            )
        outcomes = (*state.get("outcomes", ()), outcome)
        return {"outcomes": outcomes, "index": index + 1}

    def finish(state: ObjectDiscoveryState) -> dict[str, Any]:
        evidence = state.get("evidence")
        if evidence is None:
            return {
                "status": "failed",
                "error": "Object-level discovery reached summary without evidence.",
            }
        outcomes = state.get("outcomes", ())
        plans = state.get("plans", ())
        succeeded = sum(1 for outcome in outcomes if outcome.succeeded)
        reused = sum(1 for outcome in outcomes if outcome.status == "reused")
        failed = len(outcomes) - succeeded
        if not plans:
            status = "no_tables"
        elif failed == 0:
            status = "completed"
        elif succeeded == 0:
            status = "failed"
        else:
            status = "partial"
        finished_at = format_timestamp(clock())
        warnings = list(state.get("warnings", ()))
        for outcome in outcomes:
            warnings.extend(outcome.warnings)
        record = ObjectRunRecord(
            run_id=state.get("run_id", "run"),
            status=status,  # type: ignore[arg-type]
            started_at=state.get("started_at", finished_at),
            finished_at=finished_at,
            ddl_repository=state.get("ddl_repository", ""),
            snapshot_id=evidence.snapshot_id,
            database_platform=evidence.database.platform,
            database_name=evidence.database.database,
            provider=run_config.provider,
            model=run_config.model,
            temperature=run_config.temperature,
            max_tokens=run_config.max_tokens,
            candidate_root=str(Path(candidates_root)),
            tables_scheduled=len(plans),
            tables_succeeded=succeeded,
            tables_reused=reused,
            tables_failed=failed,
            outcomes=tuple(outcome.record() for outcome in outcomes),
            warnings=_merge_warnings(tuple(warnings)),
            limitations=_LIMITATIONS,
        )
        try:
            with tracer.span("write_run_summary", node="finish"):
                run_path = store.write_run(record)
        except CandidateRepositoryError as exc:
            return {
                "status": "failed",
                "error": _safe_error("Could not write the run summary", exc),
            }
        result = ObjectRunResult(
            run_id=record.run_id,
            run_path=run_path,
            status=status,
            started_at=record.started_at,
            finished_at=record.finished_at,
            tables_scheduled=record.tables_scheduled,
            tables_succeeded=record.tables_succeeded,
            tables_reused=record.tables_reused,
            tables_failed=record.tables_failed,
            outcomes=outcomes,
            warnings=record.warnings,
            record=record,
        )
        return {"status": status, "run_result": result}

    def fail(state: ObjectDiscoveryState) -> dict[str, Any]:
        updates: dict[str, Any] = {"status": "failed"}
        if not state.get("error"):
            updates["error"] = "Object-level discovery failed."
        return updates

    def route_after_plan(state: ObjectDiscoveryState) -> str:
        if state.get("status") == "failed":
            return "fail"
        return "process_table" if state.get("plans") else "finish"

    def route_after_process(state: ObjectDiscoveryState) -> str:
        return (
            "process_table"
            if state.get("index", 0) < len(state.get("plans", ()))
            else "finish"
        )

    graph.add_node("load_evidence", load_evidence)
    graph.add_node("plan_requests", plan_requests)
    graph.add_node("process_table", process_table)
    graph.add_node("finish", finish)
    graph.add_node("fail", fail)

    graph.add_edge(START, "load_evidence")
    graph.add_conditional_edges(
        "load_evidence",
        lambda state: "fail" if state.get("status") == "failed" else "plan_requests",
        {"plan_requests": "plan_requests", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "plan_requests",
        route_after_plan,
        {"process_table": "process_table", "finish": "finish", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "process_table",
        route_after_process,
        {"process_table": "process_table", "finish": "finish"},
    )
    graph.add_edge("finish", END)
    graph.add_edge("fail", END)

    return graph.compile()


def run_object_level_discovery(
    llm: LLMClient,
    tracer: Tracer,
    *,
    registry: PromptRegistry,
    candidates_root: Path | str,
    ddl_repository: Path | str,
    run_config: ObjectDiscoveryRunConfig,
    max_tables: int | None = None,
    project_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> ObjectRunResult:
    """Execute one object-level discovery run and return its summary."""

    graph = build_object_discovery_graph(
        llm,
        tracer,
        registry=registry,
        candidates_root=candidates_root,
        run_config=run_config,
        project_root=project_root,
        clock=clock,
        run_id_factory=run_id_factory,
    )
    state: dict[str, Any] = graph.invoke(
        {
            "ddl_repository": str(ddl_repository),
            "max_tables": (
                max_tables if max_tables is not None else run_config.max_tables
            ),
        }
    )
    result = state.get("run_result")
    if not isinstance(result, ObjectRunResult):
        raise DiscoveryError(
            state.get("error") or "Object-level discovery failed."
        )
    return result
