from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from uda.cli import check_ollama_available


class FakeResponse:
    status = 200

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def test_ollama_check_uses_api_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("uda.cli.urllib.request.urlopen", fake_urlopen)
    assert check_ollama_available("http://localhost:11434/v1", timeout=1.5)
    assert captured["url"] == "http://localhost:11434/api/tags"
    assert captured["timeout"] == 1.5


def test_ollama_check_handles_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        raise urllib.error.URLError("not running")

    monkeypatch.setattr("uda.cli.urllib.request.urlopen", fake_urlopen)
    assert not check_ollama_available("http://localhost:11434/v1", timeout=1.0)
