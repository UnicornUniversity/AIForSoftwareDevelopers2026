from __future__ import annotations

from pathlib import Path

import pytest
from _discovery_fixtures import (
    write_empty_repository,
    write_repository,
)

from uda.discovery.evidence import load_ddl_repository
from uda.errors import DiscoveryInputError
from uda.metadata.models import ExtractionIssue, make_physical_id


def test_loads_valid_repository_and_structural_counts(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_ddl_repository(root)
    assert evidence.database.database == "Northwind"
    assert evidence.database.platform == "sqlserver"
    assert evidence.object_count == 3
    assert evidence.table_count == 2
    assert evidence.view_count == 1
    assert evidence.ddl_status == "complete"
    assert evidence.warnings == ()


def test_known_ids_cover_every_supported_evidence_kind(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_ddl_repository(root)
    customers = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers"
    )
    customer_id = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers", "column", "CustomerID"
    )
    assert customers in evidence.known_ids("object")
    assert customer_id in evidence.known_ids("column")
    assert evidence.known_ids("primary_key")
    assert evidence.known_ids("foreign_key")
    assert evidence.known_ids("index")
    assert evidence.known_ids("ddl") == evidence.object_ids


def test_ddl_provenance_is_preserved_per_object(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_ddl_repository(root)
    customers = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers"
    )
    view = make_physical_id(
        "sqlserver", "Northwind", "dbo", "view", "CustomerOrders"
    )
    table_ddl = evidence.ddl[customers]
    assert table_ddl.provenance == "smo_scripter"
    assert table_ddl.is_original_text is False
    assert "CREATE TABLE" in table_ddl.text
    view_ddl = evidence.ddl[view]
    assert view_ddl.provenance == "server_module_definition"
    assert view_ddl.is_original_text is True
    assert "CREATE VIEW" in view_ddl.text


def test_missing_ddl_is_reported_as_a_warning(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root, ddl=False)
    evidence = load_ddl_repository(root)
    assert evidence.ddl == {}
    assert evidence.ddl_status == "not_requested"
    assert any("DDL" in warning for warning in evidence.warnings)


def test_partial_snapshot_and_issue_are_reported(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(
        root,
        issues=(ExtractionIssue(kind="permission", detail="columns unavailable"),),
    )
    evidence = load_ddl_repository(root)
    assert len(evidence.metadata.issues) == 1
    assert any("partial" in warning for warning in evidence.warnings)


def test_invalid_repository_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    object_file = sorted((root / "objects").glob("*.json"))[0]
    object_file.write_text(
        object_file.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    with pytest.raises(DiscoveryInputError, match="invalid"):
        load_ddl_repository(root)


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    root.mkdir()
    with pytest.raises(DiscoveryInputError, match="invalid|Manifest"):
        load_ddl_repository(root)


def test_empty_repository_loads_but_warns(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_empty_repository(root)
    evidence = load_ddl_repository(root)
    assert evidence.object_count == 0
    assert any("no tables or views" in warning for warning in evidence.warnings)
