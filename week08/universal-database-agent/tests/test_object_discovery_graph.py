from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _discovery_fixtures import (
    FIXED_TIME,
    real_registry,
    write_empty_repository,
    write_repository,
)
from _object_discovery_fixtures import (
    RoutingObjectLLM,
    object_json,
    responses_by_table,
)

from uda.discovery.object_graph import (
    ObjectDiscoveryRunConfig,
    ObjectRunResult,
    run_object_level_discovery,
)
from uda.tracing.noop import NoopTracer


def _run(
    llm: Any,
    ddl_root: Path,
    candidates: Path,
    *,
    run_id: str = "run-object-test",
    max_tables: int | None = None,
) -> ObjectRunResult:
    return run_object_level_discovery(
        llm,
        NoopTracer(),
        registry=real_registry(),
        candidates_root=candidates,
        ddl_repository=ddl_root,
        run_config=ObjectDiscoveryRunConfig(
            provider="fake",
            model="fixture",
            temperature=0.0,
            max_tokens=1024,
            max_tables=max_tables,
        ),
        max_tables=max_tables,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: run_id,
    )


def test_runs_one_independent_request_per_table(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    llm = RoutingObjectLLM(responses_by_table())

    result = _run(llm, ddl_root, candidates, max_tables=None)

    assert result.status == "completed"
    assert result.tables_scheduled == 2
    assert result.tables_succeeded == 2
    assert result.tables_failed == 0
    assert llm.calls == 2
    assert len(set(llm.prompts)) == 2
    assert len(result.outcomes) == 2
    assert all(outcome.validation == "passed" for outcome in result.outcomes)
    assert all(outcome.candidate_id for outcome in result.outcomes)
    assert result.run_path is not None and result.run_path.is_file()
    result_files = list((candidates / "requests" / "objects").rglob("result.json"))
    assert len(result_files) == 2
    assert not (candidates / "concepts").exists()
    assert not (candidates / "mappings").exists()


def test_one_validation_failure_does_not_abort_others(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    responses = responses_by_table()
    orders_id = next(
        object_id for object_id in responses if object_id.endswith("/Orders")
    )
    responses[orders_id] = '{"invalid": true}'
    llm = RoutingObjectLLM(responses)

    result = _run(llm, ddl_root, candidates)

    assert result.status == "partial"
    assert result.tables_succeeded == 1
    assert result.tables_failed == 1
    assert llm.calls == 2
    failed = next(item for item in result.outcomes if not item.succeeded)
    assert failed.object_physical_id == orders_id
    assert failed.status == "failed_validation"
    assert failed.validation == "failed"
    assert failed.errors
    status_path = (
        candidates
        / "requests"
        / "objects"
        / failed.execution_key
        / "status.json"
    )
    assert status_path.is_file()
    assert not (
        candidates
        / "requests"
        / "objects"
        / failed.execution_key
        / "result.json"
    ).exists()


def test_provider_failure_is_isolated(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"

    class FailingCustomers(RoutingObjectLLM):
        def invoke(self, messages):  # type: ignore[no-untyped-def]
            human = str(messages[-1].content)
            marker = "OBJECT EVIDENCE (JSON):\n"
            payload = json.loads(human.split(marker, 1)[1])
            if payload["object"]["physical_id"].endswith("/Customers"):
                self.calls += 1
                self.prompts.append(human)
                raise RuntimeError("provider unavailable")
            return super().invoke(messages)

    llm = FailingCustomers(responses_by_table())
    result = _run(llm, ddl_root, candidates)

    assert result.status == "partial"
    assert result.tables_succeeded == 1
    assert result.tables_failed == 1
    assert llm.calls == 2
    failed = next(item for item in result.outcomes if not item.succeeded)
    assert failed.status == "failed_terminal"
    assert failed.errors and "no retry was attempted" in failed.errors[0]


def test_existing_successful_candidates_are_reused(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    first_llm = RoutingObjectLLM(responses_by_table())
    first = _run(first_llm, ddl_root, candidates, run_id="run-first")
    assert first.status == "completed"
    assert first_llm.calls == 2
    result_files = sorted(
        (candidates / "requests" / "objects").rglob("result.json")
    )
    originals = {path: path.read_bytes() for path in result_files}

    second_llm = RoutingObjectLLM(responses_by_table())
    second = _run(second_llm, ddl_root, candidates, run_id="run-second")

    assert second.status == "completed"
    assert second.tables_reused == 2
    assert second.tables_failed == 0
    assert second_llm.calls == 0
    assert all(outcome.status == "reused" for outcome in second.outcomes)
    assert {path: path.read_bytes() for path in result_files} == originals


def test_all_failures_produce_a_failed_run(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    responses = {key: "{}" for key in responses_by_table()}
    llm = RoutingObjectLLM(responses)

    result = _run(llm, ddl_root, candidates)

    assert result.status == "failed"
    assert result.tables_succeeded == 0
    assert result.tables_failed == 2
    assert result.run_path is not None and result.run_path.is_file()


def test_max_tables_limits_the_selection(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    llm = RoutingObjectLLM(responses_by_table())

    result = _run(llm, ddl_root, candidates, max_tables=1)

    assert result.tables_scheduled == 1
    assert llm.calls == 1
    assert result.outcomes[0].object_physical_id.endswith("/Customers")


def test_empty_repository_reports_no_tables(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_empty_repository(ddl_root)
    candidates = tmp_path / "candidates"
    llm = RoutingObjectLLM(responses_by_table())

    result = _run(llm, ddl_root, candidates)

    assert result.status == "no_tables"
    assert result.tables_scheduled == 0
    assert llm.calls == 0
    assert result.run_path is not None and result.run_path.is_file()


def test_valid_and_invalid_responses_use_one_call_per_table(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    responses = responses_by_table()
    customers_id = next(
        object_id for object_id in responses if object_id.endswith("/Customers")
    )
    responses[customers_id] = object_json("Customers")
    llm = RoutingObjectLLM(responses)

    result = _run(llm, ddl_root, candidates)

    assert llm.calls == len(result.outcomes) == 2
