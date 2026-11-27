"""Live natural-language query graph.

The topology is the project's compact ``StateGraph``: interpret -> clarify or map -> generate
-> validate -> (bounded repair) -> execute -> explain. Only validation failures may re-enter
the repair loop; execution errors and timeouts terminate the attempt.

This module contains no safety policy of its own beyond routing: SQL validation lives in
``sql_safety`` and execution limits live in the adapter and configuration.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..adapters.base import DatabaseAdapter
from ..errors import AdapterError, LLMProviderError
from ..graph.builder import MAX_REPAIRS
from ..graph.state import GraphState
from ..llm.base import LLMClient
from ..prompts import PromptRegistry
from ..tracing.base import Tracer
from .context import SchemaContext
from .sql_safety import validate_read_query

EXPLAIN_ROW_SAMPLE = 100
MAX_EXPLAIN_ROWS_CHARS = 12_000


def _strip_code_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _clean_sql(text: str) -> str:
    value = _strip_code_fence(text)
    if value.lower().startswith("sql:"):
        value = value[4:].strip()
    return value


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _fallback_explanation(columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...],
                          *, truncated: bool) -> str:
    if not rows:
        return "The query returned no rows."
    note = " Results were truncated by the row limit." if truncated else ""
    if columns:
        return (
            f"The query returned {len(rows)} row(s) with columns "
            f"{', '.join(columns)}.{note}"
        )
    return f"The query returned {len(rows)} row(s).{note}"


def build_live_query_graph(
    llm: LLMClient,
    tracer: Tracer,
    *,
    adapter: DatabaseAdapter,
    schema_context: SchemaContext,
    registry: PromptRegistry,
    timeout_seconds: int,
    row_limit: int,
    max_repairs: int = MAX_REPAIRS,
) -> Any:
    """Build and compile the live query graph for one schema snapshot."""

    graph: StateGraph[GraphState] = StateGraph(GraphState)

    def interpret(state: GraphState) -> dict[str, Any]:
        with tracer.generation("interpret", question_length=len(state["question"])):
            messages = registry.render("query_interpret", question=state["question"])
            text = llm.invoke(messages)
        payload = _extract_json_object(text)
        if payload is None:
            return {
                "intent": text.strip(),
                "ambiguity": False,
                "clarification_question": "",
                "retry_count": 0,
            }
        return {
            "intent": str(payload.get("intent") or "").strip(),
            "ambiguity": bool(payload.get("ambiguous", False)),
            "clarification_question": str(payload.get("clarification") or "").strip(),
            "retry_count": 0,
        }

    def clarify(state: GraphState) -> dict[str, Any]:
        with tracer.span("clarify"):
            question = state.get("clarification_question") or (
                "Please clarify your question before a query is generated."
            )
        return {"answer": question, "status": "clarification_required"}

    def map_concepts(state: GraphState) -> dict[str, Any]:
        with tracer.span("map_concepts", object_count=schema_context.object_count):
            return {"context": schema_context.text}

    def generate_sql(state: GraphState) -> dict[str, Any]:
        with tracer.generation("generate_sql", question_length=len(state["question"])):
            messages = registry.render(
                "query_generate",
                question=state["question"],
                schema=schema_context.text,
            )
            text = llm.invoke(messages)
        return {"candidate_sql": _clean_sql(text)}

    def validate_sql(state: GraphState) -> dict[str, Any]:
        candidate = state.get("candidate_sql", "")
        result = validate_read_query(
            candidate,
            allowed_objects=schema_context.allowed_objects,
            default_schema=schema_context.default_schema,
            database=schema_context.database,
        )
        with tracer.span(
            "validate_sql",
            sql_length=len(candidate),
            error_count=len(result.errors),
            table_count=len(result.tables),
        ):
            pass
        return {
            "validation_errors": result.errors,
            "status": "validated" if result.valid else "invalid",
        }

    def repair_sql(state: GraphState) -> dict[str, Any]:
        errors = "\n".join(state.get("validation_errors", ()))
        with tracer.generation(
            "repair_sql",
            error_count=len(state.get("validation_errors", ())),
            attempt=state.get("retry_count", 0) + 1,
        ):
            messages = registry.render(
                "query_repair",
                question=state["question"],
                schema=schema_context.text,
                sql=state.get("candidate_sql", ""),
                errors=errors,
            )
            text = llm.invoke(messages)
        return {
            "candidate_sql": _clean_sql(text),
            "retry_count": state.get("retry_count", 0) + 1,
        }

    def execute_read(state: GraphState) -> dict[str, Any]:
        sql = state.get("candidate_sql", "")
        try:
            result = adapter.execute_read(
                sql, timeout_seconds=timeout_seconds, row_limit=row_limit
            )
        except AdapterError as exc:
            with tracer.span("execute_read", outcome="execution_failed"):
                pass
            return {
                "error": str(exc),
                "status": "execution_failed",
                "answer": f"The query could not be executed: {exc}",
            }
        with tracer.span(
            "execute_read",
            outcome="ok",
            row_count=len(result.rows),
            truncated=result.truncated,
        ):
            pass
        return {
            "result_columns": tuple(result.columns),
            "result_rows": tuple(tuple(row) for row in result.rows),
            "result_truncated": result.truncated,
            "status": "executed",
        }

    def explain(state: GraphState) -> dict[str, Any]:
        columns = state.get("result_columns", ())
        rows = state.get("result_rows", ())
        truncated = state.get("result_truncated", False)
        sample = rows[:EXPLAIN_ROW_SAMPLE]
        rows_text = json.dumps(
            {"columns": list(columns), "rows": [list(row) for row in sample]},
            default=str,
            ensure_ascii=False,
        )
        if len(rows_text) > MAX_EXPLAIN_ROWS_CHARS:
            rows_text = rows_text[:MAX_EXPLAIN_ROWS_CHARS] + "...[truncated]"
        try:
            with tracer.generation("explain", row_count=len(rows), truncated=truncated):
                messages = registry.render(
                    "query_explain",
                    question=state["question"],
                    sql=state.get("candidate_sql", ""),
                    result_json=rows_text,
                    truncated="yes" if truncated else "no",
                )
                answer = llm.invoke(messages)
        except LLMProviderError:
            answer = _fallback_explanation(columns, rows, truncated=truncated)
        return {"answer": answer.strip(), "status": "answered"}

    def execution_error(state: GraphState) -> dict[str, Any]:
        with tracer.span("execution_error"):
            return {
                "answer": (
                    state.get("answer")
                    or state.get("error")
                    or "The query could not be executed."
                ),
                "status": "execution_failed",
            }

    def fail(state: GraphState) -> dict[str, Any]:
        with tracer.span("fail", error_count=len(state.get("validation_errors", ()))):
            errors = state.get("validation_errors", ())
            detail = "; ".join(errors) if errors else "unknown validation failure"
            return {
                "answer": (
                    "The generated SQL could not be validated after "
                    f"{max_repairs} repair attempts: {detail}"
                ),
                "status": "failed",
            }

    def route_after_interpret(state: GraphState) -> str:
        return "clarify" if state.get("ambiguity") else "map_concepts"

    def route_after_validation(state: GraphState) -> str:
        if not state.get("validation_errors"):
            return "execute_read"
        if state.get("retry_count", 0) < max_repairs:
            return "repair_sql"
        return "fail"

    def route_after_execute(state: GraphState) -> str:
        return "execution_error" if state.get("status") == "execution_failed" else "explain"

    graph.add_node("interpret", interpret)
    graph.add_node("clarify", clarify)
    graph.add_node("map_concepts", map_concepts)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("repair_sql", repair_sql)
    graph.add_node("execute_read", execute_read)
    graph.add_node("explain", explain)
    graph.add_node("execution_error", execution_error)
    graph.add_node("fail", fail)

    graph.add_edge(START, "interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {"clarify": "clarify", "map_concepts": "map_concepts"},
    )
    graph.add_edge("clarify", END)
    graph.add_edge("map_concepts", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validation,
        {
            "execute_read": "execute_read",
            "repair_sql": "repair_sql",
            "fail": "fail",
        },
    )
    graph.add_edge("repair_sql", "validate_sql")
    graph.add_conditional_edges(
        "execute_read",
        route_after_execute,
        {"execution_error": "execution_error", "explain": "explain"},
    )
    graph.add_edge("explain", END)
    graph.add_edge("execution_error", END)
    graph.add_edge("fail", END)

    return graph.compile()
