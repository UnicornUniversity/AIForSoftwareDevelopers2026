from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from uda.cli import main
from uda.errors import TracingError


def make_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text("profile: test\nllm:\n  model: test-model\n", encoding="utf-8")
    return path


def base_args(tmp_path: Path, *rest: str) -> list[str]:
    return ["--env-file", str(tmp_path / "no.env"), *rest]


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "Universal Database Agent" in capsys.readouterr().out


def test_subcommand_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["config", "--help"])
    assert excinfo.value.code == 0


def test_config_show_masks_secrets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UDA_LLM_API_KEY", "cli-secret-value")
    profile = make_profile(tmp_path)
    code = main(base_args(tmp_path, "config", "show", "--profile", str(profile), "--json"))
    assert code == 0
    output = capsys.readouterr().out
    assert "cli-secret-value" not in output
    assert '"api_key": "***"' in output


def test_config_show_json_contains_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = make_profile(tmp_path)
    code = main(base_args(tmp_path, "config", "show", "--profile", str(profile), "--json"))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["llm"]["model"] == "test-model"


def test_config_error_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        base_args(
            tmp_path,
            "config",
            "validate",
            "--profile",
            str(tmp_path / "missing.yaml"),
        )
    )
    assert code == 2
    assert "configuration error" in capsys.readouterr().err


def test_graph_writes_mermaid(tmp_path: Path) -> None:
    profile = make_profile(tmp_path)
    output = tmp_path / "graph.mmd"
    code = main(
        base_args(
            tmp_path,
            "graph",
            "--profile",
            str(profile),
            "--output",
            str(output),
        )
    )
    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "interpret" in text and "validate_sql" in text


def test_demo_runs_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile = make_profile(tmp_path)
    code = main(
        base_args(tmp_path, "demo", "--profile", str(profile), "--question", "How many customers?")
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "status: answered" in output


def test_provider_check_reports_non_ollama(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = make_profile(tmp_path)
    code = main(base_args(tmp_path, "provider", "check", "--profile", str(profile)))
    assert code == 0
    assert "not 'ollama'" in capsys.readouterr().out


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any]]] = []
        self.flushed = False

    def span(self, name: str, **attributes: Any) -> Any:
        self.spans.append((name, attributes))
        return nullcontext()

    def flush(self) -> None:
        self.flushed = True


def test_trace_demo_noop_reports_no_external_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = make_profile(tmp_path)
    code = main(base_args(tmp_path, "trace-demo", "--profile", str(profile)))
    assert code == 0
    assert "No external trace emitted" in capsys.readouterr().out


def test_trace_demo_langfuse_reports_emission(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = make_profile(tmp_path)
    tracer = FakeTracer()
    monkeypatch.setenv("UDA_TRACER", "langfuse")
    monkeypatch.setattr("uda.cli.build_tracer", lambda config: tracer)
    code = main(base_args(tmp_path, "trace-demo", "--profile", str(profile)))
    assert code == 0
    assert "Trace emitted through langfuse tracer." in capsys.readouterr().out
    assert tracer.flushed is True


def test_trace_demo_error_is_reported(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = make_profile(tmp_path)
    monkeypatch.setenv("UDA_TRACER", "langfuse")

    def broken_tracer(config: Any) -> Any:
        raise TracingError("tracer failure")

    monkeypatch.setattr("uda.cli.build_tracer", broken_tracer)
    code = main(base_args(tmp_path, "trace-demo", "--profile", str(profile)))
    assert code == 1
    assert "tracer failure" in capsys.readouterr().err
