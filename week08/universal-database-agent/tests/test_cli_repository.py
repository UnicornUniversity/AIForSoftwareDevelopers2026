from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from uda.adapters.ddl import PROVENANCE_TABLE, DdlExtraction, DdlObject
from uda.adapters.readonly import ReadOnlyVerification
from uda.adapters.smo import SmoStatus
from uda.cli import main
from uda.errors import AdapterConnectionError
from uda.metadata.fixtures import fixture_payload
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from uda.repository import DdlRepositoryWriter, GitState

FIXED_TIME = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)


def make_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text("profile: test\n", encoding="utf-8")
    return path


def args(tmp_path: Path, *rest: str) -> list[str]:
    return ["--env-file", str(tmp_path / "no.env"), *rest]


def sample_metadata(issues: tuple[ExtractionIssue, ...] = ()) -> DatabaseMetadata:
    table_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Customers")
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
                        data_type="nvarchar(5)",
                        normalized_type="string",
                        nullable=False,
                    ),
                ),
            ),
        ),
        issues=issues,
    )


def write_fixture(tmp_path: Path, issues: tuple[ExtractionIssue, ...] = ()) -> Path:
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(fixture_payload(sample_metadata(issues=issues)), indent=2),
        encoding="utf-8",
    )
    return path


def make_writer(root: Path) -> DdlRepositoryWriter:
    return DdlRepositoryWriter(
        root,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-cli",
        git_provider=lambda: GitState(True, "b" * 40),
        smo_provider=lambda: SmoStatus(available=False, detail="SMO not found."),
    )


class FakeAdapter:
    instance: FakeAdapter | None = None
    metadata = sample_metadata()
    fail = False

    def __init__(self, config: Any) -> None:
        self.config = config
        self.schemas: Any = None
        self.closed = False
        FakeAdapter.instance = self

    def connect(self) -> None:
        if FakeAdapter.fail:
            raise AdapterConnectionError(
                "Could not connect to SQL Server (authentication failed)."
            )

    def introspect(self, schemas: Any = None) -> DatabaseMetadata:
        self.schemas = schemas
        return FakeAdapter.metadata

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_adapter() -> None:
    FakeAdapter.fail = False
    FakeAdapter.metadata = sample_metadata()
    FakeAdapter.instance = None


def test_snapshot_from_fixture_writes_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = write_fixture(tmp_path)
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--fixture",
            str(fixture),
            "--repo",
            str(repository),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["source"] == "fixture"
    assert payload["counts"]["tables"] == 1
    assert (repository / "manifest.json").is_file()
    assert (repository / "issues.json").is_file()


def test_snapshot_from_live_adapter_passes_schema_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    monkeypatch.setattr(
        "uda.cli.detect_smo_availability",
        lambda: SmoStatus(available=True, version="17.0.0.0", mechanism="gac"),
    )
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--profile",
            str(make_profile(tmp_path)),
            "--schema",
            "dbo",
            "--repo",
            str(repository),
            "--json",
        )
    )
    assert code == 0
    assert FakeAdapter.instance is not None
    assert FakeAdapter.instance.schemas == ["dbo"]
    assert FakeAdapter.instance.closed is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "sqlserver"
    assert payload["smo"]["available"] is True


def test_snapshot_partial_extraction_returns_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = write_fixture(
        tmp_path,
        issues=(ExtractionIssue(kind="permission", detail="columns unavailable"),),
    )
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--fixture",
            str(fixture),
            "--repo",
            str(repository),
        )
    )
    assert code == 3
    captured = capsys.readouterr()
    assert "Partial extraction" in captured.err
    manifest = json.loads((repository / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["snapshot"]["status"] == "partial"


def test_snapshot_fixture_honors_schema_filter(tmp_path: Path) -> None:
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--fixture",
            str(write_fixture(tmp_path)),
            "--repo",
            str(repository),
            "--schema",
            "absent",
        )
    )
    assert code == 0
    manifest = json.loads((repository / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["database"]["schemas"] == []
    assert manifest["counts"]["tables"] == 0


def test_snapshot_failure_is_reported_without_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAdapter.fail = True
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--profile",
            str(make_profile(tmp_path)),
            "--repo",
            str(tmp_path / "ddl"),
        )
    )
    assert code == 1
    stderr = capsys.readouterr().err
    assert "authentication failed" in stderr
    assert "password" not in stderr.lower()


def test_validate_reports_valid_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "ddl"
    make_writer(repository).write(sample_metadata(), source="fixture")
    code = main(args(tmp_path, "db", "validate", "--repo", str(repository)))
    assert code == 0
    assert "Repository valid: yes" in capsys.readouterr().out


def test_validate_reports_invalid_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "ddl"
    make_writer(repository).write(sample_metadata(), source="fixture")
    (repository / "objects" / "extra.json").write_text("{}", encoding="utf-8")
    code = main(args(tmp_path, "db", "validate", "--repo", str(repository)))
    assert code == 1
    captured = capsys.readouterr()
    assert "Repository valid: no" in captured.err
    assert "Unreferenced artifact" in captured.err


def test_validate_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "ddl"
    make_writer(repository).write(sample_metadata(), source="fixture")
    code = main(
        args(tmp_path, "db", "validate", "--repo", str(repository), "--json")
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["status"] == "complete"
    assert payload["manifest"]["repository"] == "ddl"


def test_status_prints_manifest_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "ddl"
    make_writer(repository).write(sample_metadata(), source="fixture")
    code = main(args(tmp_path, "db", "status", "--repo", str(repository)))
    assert code == 0
    output = capsys.readouterr().out
    assert "Database: Northwind (sqlserver)" in output
    assert "Status: complete" in output
    assert "Valid: yes" in output
    assert "Original DDL: unavailable" in output
    assert "DDL: not_requested" in output


def test_status_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = tmp_path / "ddl"
    make_writer(repository).write(sample_metadata(), source="fixture")
    code = main(args(tmp_path, "db", "status", "--repo", str(repository), "--json"))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["snapshot_id"] == payload["manifest"]["snapshot"]["id"]


def test_status_missing_manifest_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(args(tmp_path, "db", "status", "--repo", str(tmp_path / "missing")))
    assert code == 1
    assert "missing or invalid" in capsys.readouterr().err


def test_smo_command_reports_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "uda.cli.detect_smo_availability",
        lambda: SmoStatus(
            available=True,
            version="17.0.0.0",
            mechanism="gac",
            detail="SMO assembly detected.",
        ),
    )
    code = main(args(tmp_path, "db", "smo"))
    assert code == 0
    output = capsys.readouterr().out
    assert "SMO: available (17.0.0.0)" in output
    assert "SMO assembly detected." in output


def test_smo_command_reports_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "uda.cli.detect_smo_availability",
        lambda: SmoStatus(available=False, detail="SMO assemblies were not found."),
    )
    code = main(args(tmp_path, "db", "smo"))
    assert code == 1
    output = capsys.readouterr().out
    assert "SMO: unavailable" in output
    assert "SQLAlchemy Inspector" in output


def _extraction_for(metadata: DatabaseMetadata) -> DdlExtraction:
    return DdlExtraction(
        status="complete",
        mechanism="smo",
        version="17.0.0.0",
        detail="SMO extraction result.",
        objects=tuple(
            DdlObject(
                physical_id=item.physical_id,
                kind=item.object_type,
                status="extracted",
                ddl=f"CREATE TABLE [dbo].[{item.name}] (Id int);\n",
                provenance=PROVENANCE_TABLE,
            )
            for item in metadata.objects
        ),
    )


class FakeExtractor:
    instance: FakeExtractor | None = None
    called = False

    def __init__(self, config: Any, *, timeout_seconds: float = 120.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        FakeExtractor.instance = self

    def extract(self, metadata: DatabaseMetadata) -> DdlExtraction:
        FakeExtractor.called = True
        return _extraction_for(metadata)


@pytest.fixture(autouse=True)
def reset_fake_extractor() -> None:
    FakeExtractor.called = False
    FakeExtractor.instance = None


def test_snapshot_from_live_adapter_includes_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    monkeypatch.setattr("uda.cli.SmoDdlExtractor", FakeExtractor)
    monkeypatch.setattr(
        "uda.cli.detect_smo_availability",
        lambda: SmoStatus(available=True, version="17.0.0.0", mechanism="gac"),
    )
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--profile",
            str(make_profile(tmp_path)),
            "--repo",
            str(repository),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ddl"] == {"status": "complete", "extracted": 1, "objects": 1}
    assert FakeExtractor.called is True
    assert list((repository / "ddl").glob("*.sql"))
    manifest = json.loads((repository / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["extraction"]["ddl"]["status"] == "complete"


def test_snapshot_no_ddl_skips_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_extractor(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SMO extractor must not run with --no-ddl")

    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    monkeypatch.setattr("uda.cli.SmoDdlExtractor", forbidden_extractor)
    repository = tmp_path / "ddl"
    code = main(
        args(
            tmp_path,
            "db",
            "snapshot",
            "--profile",
            str(make_profile(tmp_path)),
            "--no-ddl",
            "--repo",
            str(repository),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ddl"] == {
        "status": "not_requested",
        "extracted": 0,
        "objects": 0,
    }
    assert not list((repository / "ddl").glob("*.sql"))


class FakeEngineContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *args: Any) -> bool:
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self) -> FakeEngineContext:
        return FakeEngineContext()

    def dispose(self) -> None:
        self.disposed = True


def _patch_readonly_cli(
    monkeypatch: pytest.MonkeyPatch,
    verification: ReadOnlyVerification,
) -> FakeEngine:
    engine = FakeEngine()
    monkeypatch.setattr("uda.cli.build_connection_url", lambda config: "dummy")
    monkeypatch.setattr("uda.cli.create_engine", lambda url: engine)
    monkeypatch.setattr(
        "uda.cli.verify_read_only", lambda connection, secret="": verification
    )
    return engine


def test_readonly_check_reports_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = _patch_readonly_cli(
        monkeypatch,
        ReadOnlyVerification(
            status="verified_read_only",
            detail="No write permission detected.",
        ),
    )
    code = main(
        args(
            tmp_path,
            "db",
            "readonly-check",
            "--profile",
            str(make_profile(tmp_path)),
        )
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "Read-only verification: verified_read_only" in output
    assert "Write probe attempted: no" in output
    assert engine.disposed is True


def test_readonly_check_reports_non_read_only_without_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_readonly_cli(
        monkeypatch,
        ReadOnlyVerification(
            status="failed_not_read_only",
            detail="The configured login has write permissions.",
            granted_permissions=("object_insert", "database_control"),
        ),
    )
    code = main(
        args(
            tmp_path,
            "db",
            "readonly-check",
            "--profile",
            str(make_profile(tmp_path)),
        )
    )
    assert code == 1
    output = capsys.readouterr().out
    assert "failed_not_read_only" in output
    assert "object_insert" in output
    assert "Write probe attempted: no" in output


def test_readonly_check_reports_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_readonly_cli(
        monkeypatch,
        ReadOnlyVerification(
            status="unavailable",
            detail="Permitted read check failed (OperationalError).",
        ),
    )
    code = main(
        args(
            tmp_path,
            "db",
            "readonly-check",
            "--profile",
            str(make_profile(tmp_path)),
            "--json",
        )
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unavailable"
    assert payload["write_probe_attempted"] is False
