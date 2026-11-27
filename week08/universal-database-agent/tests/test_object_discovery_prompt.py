from __future__ import annotations

from pathlib import Path

from _discovery_fixtures import load_evidence, real_registry, sample_metadata, write_repository

from uda.discovery.object_prompt import build_object_discovery_prompt


def _tables():
    return {
        table.name: table
        for table in sample_metadata().objects
        if table.object_type == "table"
    }


def _prompt_text(bundle) -> str:
    return "\n".join(str(message.content) for message in bundle.messages)


def test_each_table_gets_its_own_bounded_prompt(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    tables = _tables()
    registry = real_registry()

    customers = build_object_discovery_prompt(
        evidence, tables["Customers"], registry
    )
    orders = build_object_discovery_prompt(evidence, tables["Orders"], registry)

    customers_text = _prompt_text(customers)
    orders_text = _prompt_text(orders)

    assert "CREATE TABLE [dbo].[Customers]" in customers_text
    assert "CREATE TABLE [dbo].[Orders]" not in customers_text
    assert "CREATE TABLE [dbo].[Orders]" in orders_text
    assert "CREATE TABLE [dbo].[Customers]" not in orders_text
    assert customers.object_physical_id != orders.object_physical_id
    assert customers.prompt_sha256 != orders.prompt_sha256
    assert customers.evidence_sha256 != orders.evidence_sha256
    assert customers.ddl_included is True
    assert customers.prompt_version == "3"
    assert "Prefer exactly ONE primary concept" in customers_text
    assert "character-for-character identical" in customers_text
    assert "MUST include an" in customers_text


def test_prompt_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    table = _tables()["Customers"]
    registry = real_registry()

    first = build_object_discovery_prompt(evidence, table, registry)
    second = build_object_discovery_prompt(evidence, table, registry)
    assert first.prompt_sha256 == second.prompt_sha256
    assert first.evidence_sha256 == second.evidence_sha256


def test_prompt_can_exclude_ddl(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    bundle = build_object_discovery_prompt(
        evidence, _tables()["Customers"], real_registry(), include_ddl=False
    )
    assert bundle.ddl_included is False
    assert "CREATE TABLE" not in _prompt_text(bundle)


def test_prompt_records_ddl_truncation(tmp_path: Path) -> None:
    root = tmp_path / "ddl"
    write_repository(root)
    evidence = load_evidence(root)
    bundle = build_object_discovery_prompt(
        evidence,
        _tables()["Customers"],
        real_registry(),
        max_ddl_chars_per_object=10,
    )
    assert bundle.ddl_included is True
    assert bundle.truncated_ddl is True
    assert any("truncated" in warning for warning in bundle.warnings)
