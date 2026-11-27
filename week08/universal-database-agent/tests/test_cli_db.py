from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from uda.cli import main
from uda.errors import AdapterConnectionError
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    SchemaMetadata,
    TableMetadata,
)


def make_profile(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text("profile: test\n", encoding="utf-8")
    return path


def args(tmp_path: Path, *rest: str) -> list[str]:
    return ["--env-file", str(tmp_path / "no.env"), *rest]


def sample_metadata(issues: tuple[ExtractionIssue, ...] = ()) -> DatabaseMetadata:
    return DatabaseMetadata(
        identity=DatabaseIdentity(database="Northwind"),
        schemas=(SchemaMetadata(physical_id="sqlserver/Northwind/schema/dbo", name="dbo"),),
        objects=(
            TableMetadata(
                physical_id="sqlserver/Northwind/dbo/table/Customers",
                schema_name="dbo",
                name="Customers",
                object_type="table",
                columns=(
                    ColumnMetadata(
                        physical_id="sqlserver/Northwind/dbo/table/Customers/column/CustomerID",
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


class FakeAdapter:
    instance: FakeAdapter | None = None
    metadata = sample_metadata()
    fail = False

    def __init__(self, config: Any) -> None:
        self.config = config
        self.closed = False
        self.schemas: Any = None
        FakeAdapter.instance = self

    def connect(self) -> None:
        if FakeAdapter.fail:
            raise AdapterConnectionError("Could not connect to SQL Server (authentication failed).")

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


def test_db_check_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(args(tmp_path, "db", "check", "--profile", str(make_profile(tmp_path))))
    assert code == 0
    output = capsys.readouterr().out
    assert "Connection OK" in output
    assert "Northwind" in output
    assert FakeAdapter.instance is not None and FakeAdapter.instance.closed is True


def test_db_check_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAdapter.fail = True
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(args(tmp_path, "db", "check", "--profile", str(make_profile(tmp_path))))
    assert code == 1
    stderr = capsys.readouterr().err
    assert "authentication failed" in stderr


def test_db_introspect_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(args(tmp_path, "db", "introspect", "--profile", str(make_profile(tmp_path))))
    assert code == 0
    output = capsys.readouterr().out
    assert "Database: Northwind" in output
    assert "Tables: 1" in output
    assert "Columns: 1" in output


def test_db_introspect_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(
        args(
            tmp_path,
            "db",
            "introspect",
            "--profile",
            str(make_profile(tmp_path)),
            "--json",
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["database"] == "Northwind"
    assert payload["objects"][0]["schema"] == "dbo"


def test_db_introspect_partial_returns_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeAdapter.metadata = sample_metadata(
        issues=(ExtractionIssue(kind="permission", detail="columns unavailable"),)
    )
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(args(tmp_path, "db", "introspect", "--profile", str(make_profile(tmp_path))))
    assert code == 3
    assert "Partial extraction" in capsys.readouterr().err


def test_db_introspect_writes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    output = tmp_path / "metadata.json"
    code = main(
        args(
            tmp_path,
            "db",
            "introspect",
            "--profile",
            str(make_profile(tmp_path)),
            "--output",
            str(output),
        )
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schemas"][0]["name"] == "dbo"


def test_db_introspect_passes_schema_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("uda.cli.SqlServerAdapter", FakeAdapter)
    code = main(
        args(
            tmp_path,
            "db",
            "introspect",
            "--profile",
            str(make_profile(tmp_path)),
            "--schema",
            "dbo",
        )
    )
    assert code == 0
    assert FakeAdapter.instance is not None
    assert FakeAdapter.instance.schemas == ["dbo"]
