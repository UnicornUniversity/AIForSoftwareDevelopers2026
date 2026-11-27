from __future__ import annotations

from pathlib import Path

import pytest
from _discovery_fixtures import (
    load_evidence,
    prompt_bundle,
    real_registry,
    write_empty_repository,
    write_repository,
)

from uda.discovery.evidence import load_ddl_repository
from uda.discovery.prompt import build_discovery_prompt
from uda.errors import DiscoveryInputError
from uda.metadata.models import make_physical_id

# Snapshot fingerprint for the three-object fixture in ``_discovery_fixtures``.
# Update only when an intentional prompt or fixture change is reviewed.
PROMPT_SNAPSHOT_SHA256 = (
    "0fb8440ee6d360b8fccd862ef0b5cf88d994c952554acf13f43f714660b01244"
)


def _human_text(prompt: object) -> str:
    return str(prompt.messages[1].content)  # type: ignore[attr-defined]


def test_prompt_contains_physical_ids_constraints_and_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    prompt = prompt_bundle(evidence)
    text = _human_text(prompt)
    customers = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers"
    )
    customer_id = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers", "column", "CustomerID"
    )
    assert customers in text
    assert customer_id in text
    assert "dbo" in text
    assert "PK_Customers" in text
    assert "FK_Orders_Customers" in text
    assert "IX_Orders_CustomerID" in text
    assert "smo_scripter" in text
    assert "server_module_definition" in text
    assert '"is_original_text": false' in text
    assert '"is_original_text": true' in text
    assert "CREATE TABLE" in text
    assert "CREATE VIEW" in text
    assert prompt.prompt_version == "2"
    assert prompt.object_count == 3
    assert prompt.ddl_included == 3


def test_prompt_is_deterministic_and_matches_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    first = prompt_bundle(evidence)
    second = prompt_bundle(evidence)
    assert first.prompt_sha256 == second.prompt_sha256
    assert first.evidence_sha256 == second.evidence_sha256
    assert first.prompt_sha256 == PROMPT_SNAPSHOT_SHA256


def test_prompt_can_exclude_ddl(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    prompt = prompt_bundle(evidence, include_ddl=False)
    text = _human_text(prompt)
    assert prompt.ddl_included == 0
    assert "CREATE TABLE" not in text
    assert "smo_scripter" not in text
    assert '"ddl": null' in text


def test_prompt_truncates_large_ddl_and_warns(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    prompt = prompt_bundle(
        evidence,
        max_ddl_chars_per_object=20,
        max_total_ddl_chars=1000,
    )
    assert prompt.truncated_ddl
    assert any("truncated" in warning for warning in prompt.warnings)
    assert "[truncated:" in _human_text(prompt)


def test_prompt_total_budget_omits_later_ddl(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    prompt = prompt_bundle(
        evidence,
        max_ddl_chars_per_object=1000,
        max_total_ddl_chars=50,
    )
    assert prompt.ddl_included == 1
    assert any("total prompt DDL budget" in warning for warning in prompt.warnings)
    assert '"included": false' in _human_text(prompt)


def test_prompt_marks_missing_ddl_as_null(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root, ddl=False)
    evidence = load_evidence(root)
    prompt = prompt_bundle(evidence)
    assert prompt.ddl_included == 0
    assert any("No per-object SQL DDL" in warning for warning in prompt.warnings)
    assert '"ddl": null' in _human_text(prompt)


def test_prompt_contains_no_configuration_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UDA_DB_PASSWORD", "super-secret-password")
    monkeypatch.setenv("UDA_LLM_API_KEY", "super-secret-key")
    root = tmp_path / "ddl"
    write_repository(root)
    prompt = prompt_bundle(load_evidence(root))
    combined = "\n".join(str(message.content) for message in prompt.messages)
    assert "super-secret-password" not in combined
    assert "super-secret-key" not in combined


def test_prompt_rejects_empty_repository(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_empty_repository(root)
    evidence = load_ddl_repository(root)
    with pytest.raises(DiscoveryInputError, match="no tables or views"):
        build_discovery_prompt(evidence, real_registry())
