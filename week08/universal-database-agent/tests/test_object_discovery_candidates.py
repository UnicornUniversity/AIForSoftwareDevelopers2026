from __future__ import annotations

import json
from pathlib import Path

import pytest
from _discovery_fixtures import PROJECT_ROOT
from _object_discovery_fixtures import object_payload

from uda.discovery.candidates import CandidateStore
from uda.discovery.object_models import (
    ObjectCandidate,
    ObjectRequestRecord,
    ObjectRunRecord,
    ObjectStatusRecord,
)
from uda.errors import (
    CandidateRepositoryValidationError,
    CandidateRepositoryWriteError,
)


def _candidate() -> ObjectCandidate:
    payload = object_payload()
    return ObjectCandidate(
        candidate_id="cand-" + "a" * 16,
        execution_key="b" * 64,
        request_key="c" * 64,
        object_physical_id=payload["object_physical_id"],
        object_kind="table",
        object_role="entity",
        snapshot_id="sha256:snapshot",
        evidence_sha256="d" * 64,
        prompt_version="1",
        prompt_sha256="e" * 64,
        provider="fake",
        model="fixture",
        temperature=0.0,
        max_tokens=1024,
        concepts=payload["concepts"],
        mappings=payload["mappings"],
        generated_at="2026-11-18T12:00:00Z",
    )


def _request() -> ObjectRequestRecord:
    return ObjectRequestRecord(
        request_key="c" * 64,
        execution_key="b" * 64,
        object_physical_id="sqlserver/Northwind/dbo/table/Customers",
        object_kind="table",
        snapshot_id="sha256:snapshot",
        evidence_sha256="d" * 64,
        prompt_version="1",
        prompt_sha256="e" * 64,
        provider="fake",
        model="fixture",
        temperature=0.0,
        max_tokens=1024,
        ddl_included=True,
    )


def _status(status: str = "succeeded") -> ObjectStatusRecord:
    return ObjectStatusRecord(
        execution_key="b" * 64,
        request_key="c" * 64,
        object_physical_id="sqlserver/Northwind/dbo/table/Customers",
        status=status,  # type: ignore[arg-type]
        started_at="2026-11-18T12:00:00Z",
        finished_at="2026-11-18T12:00:01Z",
        errors=("invalid",) if status == "failed_validation" else (),
    )


def test_lookup_returns_none_before_execution(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates")
    assert store.lookup("b" * 64) is None


def test_result_is_immutable_and_reusable(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates")
    candidate = _candidate()
    assert store.write_request(_request()) is True
    assert store.write_result(candidate) is True
    result_path = (
        tmp_path
        / "candidates"
        / "requests"
        / "objects"
        / ("b" * 64)
        / "result.json"
    )
    original = result_path.read_bytes()

    lookup = store.lookup("b" * 64)
    assert lookup is not None
    assert lookup.status == "succeeded"
    assert lookup.candidate is not None
    assert lookup.candidate.candidate_id == candidate.candidate_id

    assert store.write_request(_request()) is False
    assert store.write_result(candidate) is False
    assert result_path.read_bytes() == original

    changed = candidate.model_copy(update={"warnings": ("changed",)})
    with pytest.raises(CandidateRepositoryWriteError, match="Refusing to overwrite"):
        store.write_result(changed)
    assert result_path.read_bytes() == original


def test_terminal_failure_is_reported(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates")
    assert store.write_status(_status("failed_validation")) is True
    lookup = store.lookup("b" * 64)
    assert lookup is not None
    assert lookup.status == "failed_validation"
    assert lookup.candidate is None
    assert lookup.status_record is not None
    assert lookup.status_record.errors == ("invalid",)
    with pytest.raises(CandidateRepositoryWriteError, match="Refusing to overwrite"):
        store.write_status(_status("failed_terminal"))


def test_status_reporting_success_without_result_is_invalid(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates")
    store.write_status(_status("failed_terminal"))
    status_path = (
        tmp_path
        / "candidates"
        / "requests"
        / "objects"
        / ("b" * 64)
        / "status.json"
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["status"] = "succeeded"
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CandidateRepositoryValidationError, match="no candidate result"):
        store.lookup("b" * 64)


def test_run_summary_is_written_once(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "candidates")
    record = ObjectRunRecord(
        run_id="run-test",
        status="completed",
        started_at="2026-11-18T12:00:00Z",
        finished_at="2026-11-18T12:00:01Z",
        ddl_repository="ddl",
        snapshot_id="sha256:snapshot",
        database_platform="sqlserver",
        database_name="Northwind",
        provider="fake",
        model="fixture",
        temperature=0.0,
        max_tokens=1024,
        candidate_root=str(tmp_path / "candidates"),
        tables_scheduled=1,
        tables_succeeded=1,
        tables_reused=0,
        tables_failed=0,
    )
    path = store.write_run(record)
    assert path.is_file()
    with pytest.raises(CandidateRepositoryWriteError, match="Refusing to overwrite"):
        store.write_run(record)


def test_candidate_root_must_be_discovery_runs() -> None:
    with pytest.raises(CandidateRepositoryWriteError, match="discovery-runs"):
        CandidateStore(
            PROJECT_ROOT / "data" / "knowledge" / "proposals",
            project_root=PROJECT_ROOT,
        )
