"""Compact LangGraph StateGraph skeleton.

The graph proves typed state, nodes, edges, conditional transitions, state management, and a
bounded validation-repair loop. It intentionally uses a fake LLM and does not execute SQL.

``demo_validate_sql`` is a demonstration-only placeholder, not a security boundary. Phase 7
must replace it with SQLGlot-based analysis and independent execution controls.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from ..llm.base import LLMClient
from ..tracing.base import Tracer
from .state import GraphState

MAX_REPAIRS = 2


def build_query_graph(llm: LLMClient, tracer: Tracer) -> Any:
    """Build and compile the Phase 1 query graph."""

    graph: StateGraph[GraphState] = StateGraph(GraphState)

    def interpret(state: GraphState) -> dict[str, Any]:
        with tracer.span("interpret"):
            text = llm.invoke(
                [HumanMessage(content=f"Interpret the user's question: {state['question']}")]
            )
        return {
            "intent": text,
            "ambiguity": "ambiguous" in state["question"].lower(),
            "retry_count": 0,
        }

    def clarify(state: GraphState) -> dict[str, Any]:
        with tracer.span("clarify"):
            return {
                "answer": "Please clarify your question before a query is generated.",
                "status": "clarification_required",
            }

    def map_concepts(state: GraphState) -> dict[str, Any]:
        with tracer.span("map_concepts"):
            return {"context": "fake schema context (Phase 1 skeleton)"}

    def generate_sql(state: GraphState) -> dict[str, Any]:
        with tracer.span("generate_sql"):
            text = llm.invoke(
                [HumanMessage(content=f"Generate a SQL Server SELECT for: {state['question']}")]
            )
        return {"candidate_sql": text}

    def demo_validate_sql(state: GraphState) -> dict[str, Any]:
        """Demonstration-only check; it is not a production SQL safety boundary."""

        sql = state.get("candidate_sql", "").strip()
        errors: tuple[str, ...] = ()
        if not sql:
            errors = ("demonstration validator: empty SQL",)
        elif not sql.upper().startswith("SELECT"):
            errors = (
                "demonstration validator: only SELECT-prefixed candidate strings are "
                "accepted; Phase 7 must replace this with SQLGlot analysis and "
                "independent execution controls",
            )
        return {
            "validation_errors": errors,
            "status": "validated" if not errors else "invalid",
        }

    def repair_sql(state: GraphState) -> dict[str, Any]:
        with tracer.span("repair_sql"):
            text = llm.invoke(
                [
                    HumanMessage(
                        content=(
                            f"Repair this SQL: {state.get('candidate_sql', '')}\n"
                            f"Validation errors: {state.get('validation_errors', ())}"
                        )
                    )
                ]
            )
        return {
            "candidate_sql": text,
            "retry_count": state.get("retry_count", 0) + 1,
        }

    def explain(state: GraphState) -> dict[str, Any]:
        with tracer.span("explain"):
            return {
                "answer": f"Phase 1 placeholder result for: {state['question']}",
                "status": "answered",
            }

    def fail(state: GraphState) -> dict[str, Any]:
        with tracer.span("fail"):
            return {
                "answer": "The generated SQL could not be validated after two repair attempts.",
                "status": "failed",
            }

    def route_after_interpret(state: GraphState) -> str:
        return "clarify" if state.get("ambiguity") else "map_concepts"

    def route_after_demo_validation(state: GraphState) -> str:
        if not state.get("validation_errors"):
            return "explain"
        if state.get("retry_count", 0) < MAX_REPAIRS:
            return "repair_sql"
        return "fail"

    graph.add_node("interpret", interpret)
    graph.add_node("clarify", clarify)
    graph.add_node("map_concepts", map_concepts)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("demo_validate_sql", demo_validate_sql)
    graph.add_node("repair_sql", repair_sql)
    graph.add_node("explain", explain)
    graph.add_node("fail", fail)

    graph.add_edge(START, "interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {"clarify": "clarify", "map_concepts": "map_concepts"},
    )
    graph.add_edge("clarify", END)
    graph.add_edge("map_concepts", "generate_sql")
    graph.add_edge("generate_sql", "demo_validate_sql")
    graph.add_conditional_edges(
        "demo_validate_sql",
        route_after_demo_validation,
        {"explain": "explain", "repair_sql": "repair_sql", "fail": "fail"},
    )
    graph.add_edge("repair_sql", "demo_validate_sql")
    graph.add_edge("explain", END)
    graph.add_edge("fail", END)

    return graph.compile()
