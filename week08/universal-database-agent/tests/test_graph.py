from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from uda.graph import MAX_REPAIRS, build_query_graph, render_mermaid
from uda.llm.fake import FakeLLMClient
from uda.tracing.noop import NoopTracer


class AlwaysInvalidLLM:
    @property
    def provider_name(self) -> str:
        return "invalid"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        return "NOT SQL"


def test_graph_answers_offline() -> None:
    graph = build_query_graph(FakeLLMClient(), NoopTracer())
    result = graph.invoke({"question": "How many customers are there?", "retry_count": 0})
    assert result["status"] == "answered"
    assert "Phase 1 placeholder" in result["answer"]


def test_ambiguous_question_takes_clarification_branch() -> None:
    graph = build_query_graph(FakeLLMClient(), NoopTracer())
    result = graph.invoke({"question": "This is ambiguous", "retry_count": 0})
    assert result["status"] == "clarification_required"


def test_repair_loop_is_bounded() -> None:
    graph = build_query_graph(AlwaysInvalidLLM(), NoopTracer())
    result = graph.invoke({"question": "How many customers?", "retry_count": 0})
    assert result["status"] == "failed"
    assert result["retry_count"] == MAX_REPAIRS
    assert "demonstration validator" in result["validation_errors"][0]


def test_mermaid_rendering_contains_nodes() -> None:
    graph = build_query_graph(FakeLLMClient(), NoopTracer())
    mermaid = render_mermaid(graph)
    assert "interpret" in mermaid
    assert "demo_validate_sql" in mermaid
    assert "repair_sql" in mermaid
