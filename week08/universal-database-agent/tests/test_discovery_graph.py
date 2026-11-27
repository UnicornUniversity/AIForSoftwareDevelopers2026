from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from _discovery_fixtures import (
    FIXED_TIME,
    FailingLLM,
    NonTextLLM,
    StaticLLM,
    TimeoutLLM,
    real_registry,
    valid_json,
    valid_payload,
    write_empty_repository,
    write_repository,
)

from uda.discovery.graph import DiscoveryRunConfig, build_discovery_graph
from uda.graph import render_mermaid
from uda.tracing.noop import NoopTracer


class RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any]]] = []
        self.generations: list[tuple[str, dict[str, Any]]] = []
        self.flushed = False

    def span(self, name: str, **attributes: Any) -> Any:
        self.spans.append((name, attributes))
        return nullcontext()

    def generation(self, name: str, **attributes: Any) -> Any:
        self.generations.append((name, attributes))
        return nullcontext()

    def score(self, name: str, value: float, **attributes: Any) -> None:
        return None

    def flush(self) -> None:
        self.flushed = True


def _graph(
    llm: object, proposals_root: Path, tracer: object | None = None
) -> Any:
    return build_discovery_graph(
        llm,  # type: ignore[arg-type]
        tracer or NoopTracer(),  # type: ignore[arg-type]
        registry=real_registry(),
        proposals_root=proposals_root,
        run_config=DiscoveryRunConfig(
            provider="fake",
            model="fixture",
            temperature=0.0,
            max_tokens=1024,
        ),
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-graph",
    )


def _invoke(graph: Any, ddl_root: Path, *, include_ddl: bool = True) -> dict[str, Any]:
    return graph.invoke(
        {"ddl_repository": str(ddl_root), "include_ddl": include_ddl}
    )


def test_graph_writes_valid_proposals_once(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    llm = StaticLLM(valid_json())
    result = _invoke(_graph(llm, props), ddl_root)
    assert result["status"] == "completed"
    assert llm.calls == 1
    assert result["proposals"].counts == {
        "concepts": 3,
        "mappings": 7,
        "relationships": 1,
    }
    assert (props / "manifest.json").is_file()
    assert len(list(props.rglob("*.yaml"))) == 11


def test_graph_records_nodes_and_generation(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    tracer = RecordingTracer()
    result = _invoke(
        _graph(StaticLLM(valid_json()), tmp_path / "proposals", tracer),
        ddl_root,
    )
    assert result["status"] == "completed"
    names = {name for name, _ in tracer.spans}
    assert {
        "load_evidence",
        "assemble_prompt",
        "invoke_llm",
        "parse_output",
        "validation_passed",
        "persist_proposals",
    } <= names
    assert tracer.generations[0][0] == "discover_semantics"
    assert tracer.generations[0][1]["provider"] == "fake"


def test_graph_no_proposals_does_not_write(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    empty = json.dumps(
        {"concepts": [], "mappings": [], "relationships": []}
    )
    result = _invoke(_graph(StaticLLM(empty), props), ddl_root)
    assert result["status"] == "no_proposals"
    assert not props.exists()


def test_graph_provider_failure_is_observable_and_writes_nothing(
    tmp_path: Path,
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    result = _invoke(_graph(FailingLLM(), props), ddl_root)
    assert result["status"] == "failed"
    assert "no retry" in result["error"]
    assert not props.exists()


def test_graph_timeout_is_observable_and_writes_nothing(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    result = _invoke(_graph(TimeoutLLM(), props), ddl_root)
    assert result["status"] == "failed"
    assert "TimeoutError" in result["error"]
    assert not props.exists()


def test_graph_malformed_and_schema_invalid_output_writes_nothing(
    tmp_path: Path,
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    for response in ("not json", '{"concepts": []}'):
        props = tmp_path / f"proposals-{len(response)}"
        llm = StaticLLM(response)
        result = _invoke(_graph(llm, props), ddl_root)
        assert result["status"] == "failed"
        assert result["validation_errors"]
        assert llm.calls == 1
        assert not props.exists()


def test_graph_semantic_invalid_output_writes_nothing(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    payload = valid_payload()
    payload["concepts"][0]["source_references"][0]["physical_id"] = (
        "sqlserver/Northwind/dbo/table/Missing"
    )
    props = tmp_path / "proposals"
    result = _invoke(
        _graph(StaticLLM(json.dumps(payload)), props), ddl_root
    )
    assert result["status"] == "failed"
    assert any(
        "unknown object Physical ID" in error
        for error in result["validation_errors"]
    )
    assert not props.exists()


def test_graph_conflict_does_not_overwrite(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    first = _invoke(_graph(StaticLLM(valid_json()), props), ddl_root)
    assert first["status"] == "completed"
    concept_path = props / "concepts" / "customer.yaml"
    original = concept_path.read_bytes()
    payload = valid_payload()
    payload["concepts"][0]["definition"] = "A changed definition."
    second = _invoke(
        _graph(StaticLLM(json.dumps(payload)), props), ddl_root
    )
    assert second["status"] == "conflicts"
    assert concept_path.read_bytes() == original


def test_graph_non_text_response_fails(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    result = _invoke(_graph(NonTextLLM(), tmp_path / "p"), ddl_root)
    assert result["status"] == "failed"


def test_graph_missing_repository_and_empty_repository_fail(
    tmp_path: Path,
) -> None:
    missing = _invoke(
        _graph(StaticLLM(valid_json()), tmp_path / "p1"),
        tmp_path / "missing",
    )
    assert missing["status"] == "failed"
    empty_root = tmp_path / "empty-ddl"
    write_empty_repository(empty_root)
    empty = _invoke(
        _graph(StaticLLM(valid_json()), tmp_path / "p2"), empty_root
    )
    assert empty["status"] == "failed"
    assert "no tables or views" in empty["error"]


def test_graph_can_exclude_ddl(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    props = tmp_path / "proposals"
    result = _invoke(
        _graph(StaticLLM(valid_json()), props), ddl_root, include_ddl=False
    )
    assert result["status"] == "completed"
    assert result["prompt"].ddl_included == 0
    assert (props / "manifest.json").is_file()


def test_graph_renders_nodes(tmp_path: Path) -> None:
    compiled = _graph(StaticLLM(valid_json()), tmp_path / "proposals")
    mermaid = render_mermaid(compiled)
    assert "load_evidence" in mermaid
    assert "persist_proposals" in mermaid
    assert "fail" in mermaid
