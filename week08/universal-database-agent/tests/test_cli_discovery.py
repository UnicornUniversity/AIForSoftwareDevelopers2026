from __future__ import annotations

import json
from pathlib import Path

import pytest
from _discovery_fixtures import (
    REGISTRY_PATH,
    FailingLLM,
    StaticLLM,
    valid_json,
    valid_payload,
    write_repository,
)

from uda.cli import main


def make_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text("profile: test\nllm:\n  model: test-model\n", encoding="utf-8")
    return path


def base_args(tmp_path: Path, *rest: str) -> list[str]:
    return ["--env-file", str(tmp_path / "no.env"), *rest]


def _run_args(tmp_path: Path, ddl_root: Path, props: Path) -> list[str]:
    return [
        "discover",
        "run",
        "--profile",
        str(make_profile(tmp_path)),
        "--repo",
        str(ddl_root),
        "--proposals",
        str(props),
        "--prompts",
        str(REGISTRY_PATH),
    ]


def test_discover_dry_run_summarizes_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    code = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, props),
            "--dry-run",
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["objects_considered"] == 3
    assert payload["prompt_version"] == "2"
    assert payload["prompt_sha256"]
    assert not props.exists()


def test_discover_run_writes_proposals_with_fake_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: StaticLLM(valid_json())
    )
    code = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, props),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["concepts"] == 3
    assert payload["mappings"] == 7
    assert payload["relationships"] == 1
    assert payload["validation"] == "passed"
    assert len(payload["written"]) == 11
    assert (props / "manifest.json").is_file()


def test_discover_run_reports_provider_failure_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: FailingLLM()
    )
    code = main(
        base_args(tmp_path, *_run_args(tmp_path, ddl_root, props))
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "Discovery failed" in captured.err
    assert "no retry" in captured.err
    assert not props.exists()


def test_discover_run_conflict_returns_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: StaticLLM(valid_json())
    )
    first = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, props),
            "--json",
        )
    )
    assert first == 0
    concept_path = props / "concepts" / "customer.yaml"
    original = concept_path.read_bytes()
    payload = valid_payload()
    payload["concepts"][0]["definition"] = "A changed definition."
    monkeypatch.setattr(
        "uda.cli.build_llm_client",
        lambda config: StaticLLM(json.dumps(payload)),
    )
    second = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, props),
            "--json",
        )
    )
    assert second == 3
    assert concept_path.read_bytes() == original


def test_discover_run_no_proposals_is_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client",
        lambda config: StaticLLM(
            '{"concepts": [], "mappings": [], "relationships": []}'
        ),
    )
    code = main(
        base_args(tmp_path, *_run_args(tmp_path, ddl_root, props))
    )
    assert code == 0
    assert "No proposals produced" in capsys.readouterr().out
    assert not props.exists()


def test_discover_validate_reports_valid_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: StaticLLM(valid_json())
    )
    main(base_args(tmp_path, *_run_args(tmp_path, ddl_root, props)))
    capsys.readouterr()
    code = main(
        base_args(
            tmp_path,
            "discover",
            "validate",
            "--repo",
            str(props),
            "--ddl-repo",
            str(ddl_root),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["counts"]["concepts"] == 3


def test_discover_validate_reports_invalid_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    monkeypatch.setattr(
        "uda.cli.build_llm_client", lambda config: StaticLLM(valid_json())
    )
    main(base_args(tmp_path, *_run_args(tmp_path, ddl_root, props)))
    concept_path = props / "concepts" / "customer.yaml"
    concept_path.write_text(
        concept_path.read_text(encoding="utf-8") + "\n# tampered\n",
        encoding="utf-8",
    )
    code = main(
        base_args(
            tmp_path,
            "discover",
            "validate",
            "--repo",
            str(props),
        )
    )
    assert code == 1
    assert "valid: no" in capsys.readouterr().err


def test_discover_dry_run_can_show_the_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, tmp_path / "proposals"),
            "--dry-run",
            "--show-prompt",
        )
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "sqlserver/Northwind/dbo/table/Customers" in captured.err
    assert "Objects considered: 3" in captured.out


def test_discover_dry_run_can_exclude_ddl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    code = main(
        base_args(
            tmp_path,
            *_run_args(tmp_path, ddl_root, tmp_path / "proposals"),
            "--dry-run",
            "--no-ddl",
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ddl_included"] == 0


def test_discover_dry_run_missing_repository_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        base_args(
            tmp_path,
            *_run_args(
                tmp_path, tmp_path / "missing-ddl", tmp_path / "proposals"
            ),
            "--dry-run",
        )
    )
    assert code == 1
    assert "invalid" in capsys.readouterr().err.lower()


def test_discover_config_error_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        base_args(
            tmp_path,
            "discover",
            "run",
            "--profile",
            str(tmp_path / "missing.yaml"),
            "--repo",
            str(tmp_path / "ddl"),
        )
    )
    assert code == 2
    assert "configuration error" in capsys.readouterr().err


def test_discover_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["discover", "--help"])
    assert excinfo.value.code == 0
