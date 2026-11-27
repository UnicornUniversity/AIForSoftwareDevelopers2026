from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def clear_uda_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests independent of the developer's shell and .env files."""

    for key in list(os.environ):
        if key.startswith(("UDA_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)
