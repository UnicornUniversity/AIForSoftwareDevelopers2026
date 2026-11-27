"""Opt-in SQL Server integration tests.

Run with:
    $env:UDA_DB_INTEGRATION = "1"
    uv run pytest -m db

The tests skip when integration is not enabled. They never use production credentials.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from _db_probe import WRITE_PROBE_SQL, verify_read_only
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

from uda.adapters.ddl import SmoDdlExtractor
from uda.adapters.sqlserver import SqlServerAdapter, build_connection_url
from uda.config import AppConfig, load_config
from uda.repository import DdlRepositoryWriter, GitState, validate_repository

# The autouse test fixture clears UDA_* variables during ordinary tests, so capture the
# opt-in integration environment before the fixture runs.
_ENV_SNAPSHOT = {
    key: value
    for key, value in os.environ.items()
    if key.startswith(("UDA_", "LANGFUSE_"))
}

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        _ENV_SNAPSHOT.get("UDA_DB_INTEGRATION") != "1",
        reason="Set UDA_DB_INTEGRATION=1 and configure a read-only test database.",
    ),
]


@pytest.fixture
def config() -> AppConfig:
    env = {**dotenv_values(".env"), **_ENV_SNAPSHOT}
    profile = Path(env.get("UDA_DB_PROFILE", "config/profiles/deepseek.yaml"))
    return load_config(profile_path=profile, env=env)


@pytest.fixture
def adapter(config: AppConfig) -> Iterator[SqlServerAdapter]:
    instance = SqlServerAdapter(config.database)
    instance.connect()
    try:
        yield instance
    finally:
        instance.close()


def test_connection_and_identity(adapter: SqlServerAdapter, config: AppConfig) -> None:
    metadata = adapter.introspect()
    assert metadata.identity.database == config.database.name
    assert metadata.schemas


def test_objects_columns_keys_and_indexes(adapter: SqlServerAdapter) -> None:
    metadata = adapter.introspect()
    assert metadata.objects
    tables = [item for item in metadata.objects if item.object_type == "table"]
    assert any(item.columns for item in metadata.objects)
    assert any(item.primary_key is not None for item in tables)
    assert any(item.foreign_keys for item in tables)
    assert any(item.indexes for item in tables)


def _repository_artifacts(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _without_run_metadata(manifest: dict[str, object]) -> dict[str, object]:
    data = json.loads(json.dumps(manifest))
    data["snapshot"].pop("run_id")
    data["snapshot"].pop("created_at")
    data["extraction"].pop("started_at")
    data["extraction"].pop("completed_at")
    return data


def test_repository_generation_and_consecutive_idempotency(
    adapter: SqlServerAdapter, config: AppConfig, tmp_path: Path
) -> None:
    metadata = adapter.introspect()
    ddl = SmoDdlExtractor(config.database).extract(metadata)
    if ddl.status == "unavailable":
        pytest.skip(f"SMO DDL extraction unavailable: {ddl.detail}")
    assert ddl.status == "complete"
    assert ddl.extracted_count == len(metadata.objects)

    writer = DdlRepositoryWriter(
        tmp_path,
        git_provider=lambda: GitState(
            available=False, detail="Integration test uses an explicit stand-in."
        ),
    )

    first = writer.write(metadata, source="sqlserver", ddl=ddl)
    first_artifacts = _repository_artifacts(tmp_path)
    first_manifest = json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )

    second = writer.write(metadata, source="sqlserver", ddl=ddl)
    second_artifacts = _repository_artifacts(tmp_path)
    second_manifest = json.loads(
        (tmp_path / "manifest.json").read_text(encoding="utf-8")
    )

    assert first.snapshot_id == second.snapshot_id
    assert first_artifacts == second_artifacts
    assert _without_run_metadata(first_manifest) == _without_run_metadata(
        second_manifest
    )
    assert second.changes.added == ()
    assert second.changes.changed == ()
    assert second.changes.removed == ()
    assert first.counts["tables"] == metadata.table_count
    assert first.counts["views"] == metadata.view_count
    assert first.ddl_status == "complete"
    assert first.ddl_extracted == len(metadata.objects)
    assert len(list((tmp_path / "ddl").glob("*.sql"))) == len(metadata.objects)
    validation = validate_repository(tmp_path)
    assert validation.valid is True, validation.errors


def test_live_smo_ddl_provenance_and_determinism(
    adapter: SqlServerAdapter, config: AppConfig
) -> None:
    metadata = adapter.introspect()
    first = SmoDdlExtractor(config.database).extract(metadata)
    if first.status == "unavailable":
        pytest.skip(f"SMO DDL extraction unavailable: {first.detail}")
    assert first.status == "complete"
    assert first.version
    tables = [item for item in first.objects if item.kind == "table"]
    views = [item for item in first.objects if item.kind == "view"]
    assert tables and views
    assert all(item.is_original_text is False for item in tables)
    assert all(item.provenance == "smo_scripter" for item in tables)
    assert all(item.is_original_text is True for item in views)
    assert all(item.provenance == "server_module_definition" for item in views)
    assert all("CREATE TABLE" in (item.ddl or "").upper() for item in tables)
    assert all("VIEW" in (item.ddl or "").upper() for item in views)

    second = SmoDdlExtractor(config.database).extract(metadata)
    assert [(item.physical_id, item.ddl) for item in first.objects] == [
        (item.physical_id, item.ddl) for item in second.objects
    ]


def test_read_only_write_rejection(config: AppConfig) -> None:
    """Prove the configured credential cannot write; fail safely if it can.

    No write is attempted unless the permission probe proves that INSERT is denied. A
    write probe is wrapped in an uncommitted transaction and rolled back. The probe is
    attempted exactly once and is never retried.
    """

    engine = create_engine(build_connection_url(config.database))
    try:
        with engine.connect() as connection:
            table_present = connection.execute(
                text("SELECT OBJECT_ID('dbo.Region', 'U')")
            ).scalar()
            if table_present is None:
                pytest.skip(
                    "Northwind dbo.Region is not available for the write probe."
                )
            assert connection.execute(
                text("SELECT COUNT_BIG(*) FROM dbo.Region")
            ).scalar() is not None

            verification = verify_read_only(
                connection,
                table_name="[dbo].[Region]",
                write_probe_sql=WRITE_PROBE_SQL,
                secret=config.database.password,
            )

            if verification.status == "failed_not_read_only":
                pytest.fail(
                    verification.detail
                    + " Write rejection through the credential is NOT VERIFIED. "
                    "Configure a dedicated read-only login."
                )
            if verification.status == "unavailable":
                pytest.fail(
                    "Read-only verification is unavailable: " + verification.detail
                )
            assert verification.status == "verified_read_only"
            assert verification.write_probe_attempted is True
            assert verification.write_probe_rejected is True
            assert config.database.password not in verification.detail
    finally:
        engine.dispose()
