"""Typed state for the Phase 1 query-graph skeleton."""

from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict, total=False):
    question: str
    intent: str
    ambiguity: bool
    clarification_question: str
    context: str
    candidate_sql: str
    validation_errors: tuple[str, ...]
    retry_count: int
    result_columns: tuple[str, ...]
    result_rows: tuple[tuple[object, ...], ...]
    result_truncated: bool
    error: str
    answer: str
    status: str
