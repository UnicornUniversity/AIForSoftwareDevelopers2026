from __future__ import annotations

import json
from pathlib import Path

import pytest
from _discovery_fixtures import (
    REGISTRY_PATH,
    StaticLLM,
    valid_json,
    write_repository,
)
from _object_discovery_fixtures import RoutingObjectLLM, responses_by_table

from uda.cli import main


def make_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text("profile: test\nllm:\n  model: test-model\n", encoding="utf-8")
    return path


def _args(
    tmp_path: Path,
    ddl_root: Path,
    candidates: Path,
    *rest: str,
) -> list[str]:
    return [
        "--env-file",
        str(tmp_path / "no.env"),
        "discover",
        "run",
        "--strategy",
        "object-level",
        "--profile",
        str(make_profile(tmp_path)),
        "--repo",
        str(ddl_root),
        "--candidates",
        str(candidates),
        "--prompts",
        str(REGISTRY_PATH),
        *rest,
    ]


def test_object_level_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    code = main(_args(tmp_path, ddl_root, candidates, "--dry-run", "--json"))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["strategy"] == "object-level"
    assert payload["tables_scheduled"] == 2
    assert all(item["prompt_sha256"] for item in payload["tables"])
    assert not candidates.exists()


def test_object_level_dry_run_can_limit_tables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        _args(
            tmp_path,
            ddl_root,
            tmp_path / "candidates",
            "--dry-run",
            "--json",
            "--max-tables",
            "1",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tables_scheduled"] == 1
    assert payload["tables"][0]["object_physical_id"].endswith("/Customers")


def test_object_level_dry_run_can_show_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        _args(
            tmp_path,
            ddl_root,
            tmp_path / "candidates",
            "--dry-run",
            "--show-prompt",
            "--max-tables",
            "1",
        )
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "sqlserver/Northwind/dbo/table/Customers" in captured.err
    assert "Tables scheduled: 1" in captured.out


def test_object_level_dry_run_can_exclude_ddl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        _args(
            tmp_path,
            ddl_root,
            tmp_path / "candidates",
            "--dry-run",
            "--json",
            "--no-ddl",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert all(item["ddl_included"] is False for item in payload["tables"])


def test_object_level_run_writes_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    llm = RoutingObjectLLM(responses_by_table())
    monkeypatch.setattr("uda.cli.build_llm_client", lambda config: llm)
    code = main(_args(tmp_path, ddl_root, candidates, "--json"))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["tables_scheduled"] == 2
    assert payload["tables_succeeded"] == 2
    assert payload["tables_failed"] == 0
    assert llm.calls == 2
    assert len(list((candidates / "requests" / "objects").rglob("result.json"))) == 2
    assert (candidates / "runs").is_dir()
    assert not (tmp_path / "proposals").exists()


def test_object_level_partial_failure_returns_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    candidates = tmp_path / "candidates"
    responses = responses_by_table()
    orders_id = next(
        object_id for object_id in responses if object_id.endswith("/Orders")
    )
    responses[orders_id] = "{}"
    llm = RoutingObjectLLM(responses)
    monkeypatch.setattr("uda.cli.build_llm_client", lambda config: llm)
    code = main(_args(tmp_path, ddl_root, candidates, "--json"))
    assert code == 3
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "partial"
    assert payload["tables_succeeded"] == 1
    assert payload["tables_failed"] == 1
    assert "Table failed" in captured.err


def test_default_strategy_remains_single_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    proposals = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: StaticLLM(valid_json())
    )
    code = main(
        [
            "--env-file",
            str(tmp_path / "no.env"),
            "discover",
            "run",
            "--profile",
            str(make_profile(tmp_path)),
            "--repo",
            str(ddl_root),
            "--proposals",
            str(proposals),
            "--prompts",
            str(REGISTRY_PATH),
            "--json",
        ]
    )
    assert code == 0
    assert (proposals / "manifest.json").is_file()
    assert not (tmp_path / "candidates").exists()


def test_object_level_rejects_zero_max_tables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        _args(
            tmp_path,
            ddl_root,
            tmp_path / "candidates",
            "--dry-run",
            "--max-tables",
            "0",
        )
    )
    assert code == 2
    assert "max-tables" in capsys.readouterr().err
