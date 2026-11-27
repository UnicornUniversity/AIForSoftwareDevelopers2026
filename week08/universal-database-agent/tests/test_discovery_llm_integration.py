"""Opt-in live DeepSeek verification.

The ordinary suite excludes the ``llm`` marker. This test also requires
``UDA_LLM_INTEGRATION=1`` and a real, non-placeholder ``UDA_LLM_API_KEY``. It never runs by
default and never uses the database.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _discovery_fixtures import (
    FIXED_TIME,
    real_registry,
    write_repository,
)
from dotenv import dotenv_values

from uda.config import load_config
from uda.discovery.graph import DiscoveryRunConfig, build_discovery_graph
from uda.discovery.proposals import validate_proposal_repository
from uda.llm import build_llm_client
from uda.tracing.noop import NoopTracer

pytestmark = pytest.mark.llm


def _environment() -> dict[str, str]:
    file_env = {
        str(key): str(value)
        for key, value in dotenv_values(".env").items()
        if value is not None
    }
    process_env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("UDA_", "LANGFUSE_"))
    }
    return {**file_env, **process_env}


def _skip_reason() -> str | None:
    env = _environment()
    if env.get("UDA_LLM_INTEGRATION") != "1":
        return "Set UDA_LLM_INTEGRATION=1 to run the live DeepSeek verification."
    key = env.get("UDA_LLM_API_KEY", "")
    if not key or key == "change-me":
        return "Set a real UDA_LLM_API_KEY to run the live DeepSeek verification."
    return None


_SKIP_REASON = _skip_reason()


@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")
def test_live_deepseek_produces_schema_valid_proposals(tmp_path: Path) -> None:
    env = _environment()
    profile = Path(
        env.get("UDA_LLM_PROFILE", "config/profiles/deepseek.yaml")
    )
    config = load_config(profile_path=profile, env=env)
    llm = build_llm_client(config)
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    proposals_root = tmp_path / "proposals"
    graph = build_discovery_graph(
        llm,
        NoopTracer(),
        registry=real_registry(),
        proposals_root=proposals_root,
        run_config=DiscoveryRunConfig(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        ),
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-live-deepseek",
    )
    result = graph.invoke(
        {"ddl_repository": str(ddl_root), "include_ddl": True}
    )
    assert result["status"] in {"completed", "no_proposals"}, result.get(
        "error"
    )
    validation = validate_proposal_repository(
        proposals_root, ddl_repository=ddl_root
    )
    assert validation.valid, validation.errors
