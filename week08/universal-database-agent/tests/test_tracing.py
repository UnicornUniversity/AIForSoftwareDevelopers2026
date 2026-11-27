from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from uda.config import load_config
from uda.errors import TracingError
from uda.tracing import NoopTracer, build_tracer
from uda.tracing.langfuse import LangfuseTracer


class FakeSpan:
    def __enter__(self) -> FakeSpan:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.spans: list[dict[str, Any]] = []
        self.generations: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []
        self.flushed = False
        FakeClient.instances.append(self)

    def start_as_current_span(self, **kwargs: Any) -> FakeSpan:
        self.spans.append(kwargs)
        return FakeSpan()

    def start_as_current_generation(self, **kwargs: Any) -> FakeSpan:
        self.generations.append(kwargs)
        return FakeSpan()

    def create_score(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed = True


def install_fake_langfuse(
    monkeypatch: pytest.MonkeyPatch, client_class: type[Any] = FakeClient
) -> None:
    module = types.ModuleType("langfuse")
    module.Langfuse = client_class  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", module)
    FakeClient.instances.clear()


def test_default_tracer_is_noop() -> None:
    tracer = build_tracer(load_config(env={}))
    assert isinstance(tracer, NoopTracer)


def test_noop_tracer_is_usable() -> None:
    tracer = NoopTracer()
    with tracer.span("step", result_ref="r1"):
        pass
    with tracer.generation("generate", model="fake"):
        pass
    tracer.score("correctness", 1.0)
    tracer.flush()


def test_langfuse_without_keys_fails_clearly() -> None:
    config = load_config(env={"UDA_TRACER": "langfuse"})
    with pytest.raises(TracingError, match="LANGFUSE"):
        build_tracer(config)


def test_langfuse_initialization_and_span_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_langfuse(monkeypatch)
    tracer = LangfuseTracer("pub", "sec", "http://localhost:3000")
    client = FakeClient.instances[0]
    assert client.init_kwargs == {
        "public_key": "pub",
        "secret_key": "sec",
        "host": "http://localhost:3000",
    }

    with tracer.span(
        "step",
        node="interpret",
        max_tokens=1024,
        question="sensitive question",
        api_key="should-not-pass",
        result_ref="john.doe@example.com",
    ):
        pass

    assert client.spans == [
        {
            "name": "step",
            "metadata": {
                "node": "interpret",
                "max_tokens": 1024,
                "result_ref": "[REDACTED]",
            },
        }
    ]


def test_langfuse_generation_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_langfuse(monkeypatch)
    tracer = LangfuseTracer("pub", "sec", "http://localhost:3000")
    client = FakeClient.instances[0]

    with tracer.generation(
        "generate",
        model="deepseek",
        temperature=0.0,
        input_tokens=10,
        question="sensitive",
    ):
        pass

    assert client.generations == [
        {
            "name": "generate",
            "model": "deepseek",
            "metadata": {
                "model": "deepseek",
                "temperature": 0.0,
                "input_tokens": 10,
            },
        }
    ]


def test_langfuse_score_and_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_langfuse(monkeypatch)
    tracer = LangfuseTracer("pub", "sec", "http://localhost:3000")
    client = FakeClient.instances[0]

    tracer.score("correctness", 1.0, node="explain", question="sensitive")
    tracer.flush()

    assert client.scores == [
        {"name": "correctness", "value": 1.0, "metadata": {"node": "explain"}}
    ]
    assert client.flushed is True


def test_langfuse_init_error_becomes_tracing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenClient:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("boom")

    install_fake_langfuse(monkeypatch, BrokenClient)
    with pytest.raises(TracingError, match="initialize"):
        LangfuseTracer("pub", "sec", "http://localhost:3000")
