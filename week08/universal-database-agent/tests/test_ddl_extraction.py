from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

from uda.adapters.ddl import (
    PROVENANCE_TABLE,
    PROVENANCE_VIEW,
    ProcessResult,
    SmoDdlExtractor,
    normalize_ddl,
)
from uda.adapters.smo import SmoStatus
from uda.config import DatabaseConfig
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)

DETECTED = SmoStatus(
    available=True, version="17.0.0.0", mechanism="gac", detail="detected"
)


def sample_metadata() -> DatabaseMetadata:
    table_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Customers")
    view_id = make_physical_id("sqlserver", "Northwind", "dbo", "view", "Summary")
    return DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        schemas=(
            SchemaMetadata(
                physical_id=make_physical_id("sqlserver", "Northwind", "schema", "dbo"),
                name="dbo",
            ),
        ),
        objects=(
            TableMetadata(
                physical_id=table_id,
                schema_name="dbo",
                name="Customers",
                object_type="table",
                columns=(
                    ColumnMetadata(
                        physical_id=child_id(table_id, "column", "CustomerID"),
                        name="CustomerID",
                        ordinal=1,
                        data_type="int",
                        normalized_type="integer",
                        nullable=False,
                    ),
                ),
            ),
            TableMetadata(
                physical_id=view_id,
                schema_name="dbo",
                name="Summary",
                object_type="view",
                columns=(
                    ColumnMetadata(
                        physical_id=child_id(view_id, "column", "CustomerID"),
                        name="CustomerID",
                        ordinal=1,
                        data_type="int",
                        normalized_type="integer",
                        nullable=False,
                    ),
                ),
            ),
        ),
    )


def make_config(**overrides: Any) -> DatabaseConfig:
    values = {
        "host": "localhost",
        "name": "Northwind",
        "username": "reader",
        "password": "super-secret",
        "trusted_connection": False,
    }
    values.update(overrides)
    return DatabaseConfig(**values)


def success_payload(metadata: DatabaseMetadata) -> dict[str, Any]:
    objects = []
    for item in metadata.objects:
        if item.object_type == "table":
            objects.append(
                {
                    "physical_id": item.physical_id,
                    "kind": "table",
                    "status": "extracted",
                    "ddl": "CREATE TABLE [dbo].[Customers] (\r\n  [CustomerID] int\r\n);\r\nGO\r\n",
                    "provenance": PROVENANCE_TABLE,
                    "is_original_text": False,
                }
            )
        else:
            objects.append(
                {
                    "physical_id": item.physical_id,
                    "kind": "view",
                    "status": "extracted",
                    "ddl": "create view Summary as select 1 as CustomerID",
                    "provenance": PROVENANCE_VIEW,
                    "is_original_text": True,
                }
            )
    return {
        "status": "ok",
        "smo_version": "17.0.0.0",
        "server_version": "16.0.1000.6",
        "objects": objects,
    }


def runner_for(payload: dict[str, Any], captured: dict[str, Any] | None = None):
    def run(env: Mapping[str, str], timeout: float) -> ProcessResult:
        if captured is not None:
            captured.update(env)
            captured["_timeout"] = timeout  # type: ignore[assignment]
        return ProcessResult(0, json.dumps(payload), "")

    return run


def test_normalize_ddl_only_normalizes_line_endings() -> None:
    assert normalize_ddl("a\r\nb\rc") == "a\nb\nc\n"
    assert normalize_ddl("a  \n") == "a  \n"
    assert normalize_ddl("") == ""


def test_non_windows_returns_unavailable() -> None:
    called = False

    def runner(env: Mapping[str, str], timeout: float) -> ProcessResult:
        nonlocal called
        called = True
        return ProcessResult(0, "{}", "")

    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner,
        platform="linux",
    ).extract(sample_metadata())

    assert extraction.status == "unavailable"
    assert extraction.extracted_count == 0
    assert all(item.status == "unavailable" for item in extraction.objects)
    assert called is False


def test_unavailable_smo_does_not_invoke_a_process() -> None:
    called = False

    def runner(env: Mapping[str, str], timeout: float) -> ProcessResult:
        nonlocal called
        called = True
        return ProcessResult(0, "{}", "")

    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: SmoStatus(
            available=False, detail="SMO assemblies were not found."
        ),
        process_runner=runner,
        platform="win32",
    ).extract(sample_metadata())

    assert extraction.status == "unavailable"
    assert "SMO assemblies were not found" in extraction.detail
    assert called is False


def test_successful_extraction_records_provenance_and_normalizes_ddl() -> None:
    metadata = sample_metadata()
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner_for(success_payload(metadata)),
        platform="win32",
    ).extract(metadata)

    assert extraction.status == "complete"
    assert extraction.extracted_count == 2
    assert extraction.version == "17.0.0.0"
    table = next(item for item in extraction.objects if item.kind == "table")
    view = next(item for item in extraction.objects if item.kind == "view")
    assert table.provenance == PROVENANCE_TABLE
    assert table.is_original_text is False
    assert "\r" not in (table.ddl or "")
    assert (table.ddl or "").endswith(";\nGO\n")
    assert view.provenance == PROVENANCE_VIEW
    assert view.is_original_text is True


def test_request_environment_excludes_unrelated_secrets(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("UDA_LLM_API_KEY", "llm-secret")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "langfuse-secret")
    captured: dict[str, Any] = {}
    metadata = sample_metadata()
    SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner_for(success_payload(metadata), captured),
        platform="win32",
        timeout_seconds=7,
    ).extract(metadata)

    assert "UDA_LLM_API_KEY" not in captured
    assert "LANGFUSE_SECRET_KEY" not in captured
    assert captured["UDA_SMO_PASSWORD"] == "super-secret"
    assert captured["_timeout"] == 7
    request = json.loads(captured["UDA_SMO_REQUEST"])
    assert {item["kind"] for item in request["objects"]} == {"table", "view"}


def test_process_error_displayed_without_password() -> None:
    payload = {
        "status": "error",
        "detail": "Login failed for reader with password super-secret",
        "objects": [],
    }
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner_for(payload),
        platform="win32",
    ).extract(sample_metadata())

    assert extraction.status == "failed"
    assert "super-secret" not in extraction.detail
    assert "***" in extraction.detail
    assert all(item.status == "failed" for item in extraction.objects)


def test_timeout_is_reported_as_failure() -> None:
    def runner(env: Mapping[str, str], timeout: float) -> ProcessResult:
        raise subprocess.TimeoutExpired("powershell", timeout)

    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner,
        platform="win32",
    ).extract(sample_metadata())

    assert extraction.status == "failed"
    assert "timed out" in extraction.detail


def test_malformed_output_is_reported_as_failure() -> None:
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=lambda env, timeout: ProcessResult(0, "not json", "boom"),
        platform="win32",
    ).extract(sample_metadata())

    assert extraction.status == "failed"
    assert all(item.status == "failed" for item in extraction.objects)


def test_unsupported_object_status_is_preserved() -> None:
    metadata = sample_metadata()
    payload = success_payload(metadata)
    payload["objects"][0] = {
        "physical_id": metadata.objects[0].physical_id,
        "kind": metadata.objects[0].object_type,
        "status": "unsupported",
        "error": "Unsupported object type for DDL extraction.",
    }
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner_for(payload),
        platform="win32",
    ).extract(metadata)

    assert extraction.status == "partial"
    unsupported = next(
        item for item in extraction.objects if item.status == "unsupported"
    )
    assert unsupported.error
    assert unsupported.ddl is None


def test_partial_results_are_explicit() -> None:
    metadata = sample_metadata()
    payload = success_payload(metadata)
    payload["objects"] = [
        item for item in payload["objects"] if item["kind"] == "table"
    ]
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=runner_for(payload),
        platform="win32",
    ).extract(metadata)

    assert extraction.status == "partial"
    assert extraction.extracted_count == 1
    view = next(item for item in extraction.objects if item.kind == "view")
    assert view.status == "failed"
    assert view.error


def test_configuration_error_returns_unavailable() -> None:
    config = make_config(trusted_connection=True)
    extraction = SmoDdlExtractor(
        config,
        smo_provider=lambda: DETECTED,
        process_runner=lambda env, timeout: ProcessResult(0, "{}", ""),
        platform="win32",
    ).extract(sample_metadata())

    assert extraction.status == "unavailable"
    assert "Trusted connection" in extraction.detail


def test_empty_metadata_is_complete_without_a_process() -> None:
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Empty")
    )
    extraction = SmoDdlExtractor(
        make_config(),
        smo_provider=lambda: DETECTED,
        process_runner=lambda env, timeout: ProcessResult(0, "{}", ""),
        platform="win32",
    ).extract(metadata)

    assert extraction.status == "complete"
    assert extraction.objects == ()
    assert extraction.extracted_count == 0
