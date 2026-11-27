from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from uda.adapters.base import ReadResult
from uda.adapters.fake import FakeAdapter
from uda.errors import AdapterError, LLMProviderError
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    TableMetadata,
    make_physical_id,
)
from uda.prompts import PromptRegistry
from uda.query.context import build_schema_context
from uda.query.graph import build_live_query_graph
from uda.tracing.noop import NoopTracer

REGISTRY_PATH = Path("config/prompts/registry.yaml")
INTERPRET_OK = '{"ambiguous": false, "clarification": "", "intent": "count orders"}'


def schema_context() -> Any:
    orders_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Orders")
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        objects=(
            TableMetadata(
                physical_id=orders_id,
                schema_name="dbo",
                name="Orders",
                object_type="table",
                columns=(
                    ColumnMetadata(
                        physical_id=f"{orders_id}/column/OrderID",
                        name="OrderID",
                        ordinal=1,
                        data_type="int",
                        nullable=False,
                    ),
                ),
            ),
        ),
    )
    return build_schema_context(metadata)


def build(llm: Any, adapter: Any) -> Any:
    return build_live_query_graph(
        llm,
        NoopTracer(),
        adapter=adapter,
        schema_context=schema_context(),
        registry=PromptRegistry.load(REGISTRY_PATH),
        timeout_seconds=30,
        row_limit=100,
    )


class RecordingLLM:
    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "recording"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        del messages
        self.calls += 1
        return self.responses.pop(0)


class FailingAdapter(FakeAdapter):
    def execute_read(self, sql: str, *, timeout_seconds: int, row_limit: int) -> ReadResult:
        del sql, timeout_seconds, row_limit
        raise AdapterError("Timeout expired; no retry was attempted.")


class FailingExplainLLM(RecordingLLM):
    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        if self.calls == 2:
            self.calls += 1
            raise LLMProviderError("provider down")
        return super().invoke(messages)


def test_live_graph_answers_with_query_results() -> None:
    llm = RecordingLLM([INTERPRET_OK, "SELECT 1 AS value", "The value is 1."])
    adapter = FakeAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "How many orders are there?", "retry_count": 0}
    )

    assert result["status"] == "answered"
    assert result["candidate_sql"] == "SELECT 1 AS value"
    assert result["result_columns"] == ("value",)
    assert result["result_rows"] == ((1,),)
    assert result["answer"] == "The value is 1."
    assert llm.calls == 3


def test_ambiguous_question_short_circuits_to_clarification() -> None:
    llm = RecordingLLM(
        ['{"ambiguous": true, "clarification": "Which revenue definition?", "intent": ""}']
    )
    adapter = FakeAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "What was revenue?", "retry_count": 0}
    )

    assert result["status"] == "clarification_required"
    assert result["answer"] == "Which revenue definition?"
    assert llm.calls == 1


def test_repair_loop_is_bounded_to_two_attempts() -> None:
    llm = RecordingLLM(
        [
            INTERPRET_OK,
            "DELETE FROM dbo.Orders",
            "DELETE FROM dbo.Orders",
            "DELETE FROM dbo.Orders",
        ]
    )
    adapter = FakeAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "Remove orders", "retry_count": 0}
    )

    assert result["status"] == "failed"
    assert result["retry_count"] == 2
    assert "after 2 repair attempts" in result["answer"]
    assert llm.calls == 4


def test_valid_sql_after_repair_is_executed() -> None:
    llm = RecordingLLM(
        [INTERPRET_OK, "SELECT * FROM dbo.Missing", "SELECT 1 AS value", "One row."]
    )
    adapter = FakeAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "How many orders?", "retry_count": 0}
    )

    assert result["status"] == "answered"
    assert result["retry_count"] == 1
    assert result["candidate_sql"] == "SELECT 1 AS value"


def test_execution_failure_does_not_enter_repair_loop() -> None:
    llm = RecordingLLM([INTERPRET_OK, "SELECT 1 AS value"])
    adapter = FailingAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "How many orders?", "retry_count": 0}
    )

    assert result["status"] == "execution_failed"
    assert "could not be executed" in result["answer"]
    assert result["retry_count"] == 0
    assert llm.calls == 2


def test_explain_falls_back_when_provider_fails() -> None:
    llm = FailingExplainLLM([INTERPRET_OK, "SELECT 1 AS value", "unused"])
    adapter = FakeAdapter()
    adapter.connect()

    result = build(llm, adapter).invoke(
        {"question": "How many orders?", "retry_count": 0}
    )

    assert result["status"] == "answered"
    assert "returned 1 row" in result["answer"]
