from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uda.adapters.smo import SmoStatus
from uda.errors import FixtureError
from uda.metadata.fixtures import (
    FIXTURE_VERSION,
    filter_metadata_schemas,
    fixture_payload,
    load_metadata_fixture,
)
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from uda.repository import DdlRepositoryWriter, GitState, validate_repository


def sample_metadata() -> DatabaseMetadata:
    dbo_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", "Customers")
    sales_id = make_physical_id("sqlserver", "Northwind", "sales", "table", "Orders")
    return DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        schemas=(
            SchemaMetadata(
                physical_id=make_physical_id("sqlserver", "Northwind", "schema", "dbo"),
                name="dbo",
            ),
            SchemaMetadata(
                physical_id=make_physical_id(
                    "sqlserver", "Northwind", "schema", "sales"
                ),
                name="sales",
            ),
        ),
        objects=(
            TableMetadata(
                physical_id=dbo_id,
                schema_name="dbo",
                name="Customers",
                object_type="table",
                columns=(
                    ColumnMetadata(
                        physical_id=child_id(dbo_id, "column", "CustomerID"),
                        name="CustomerID",
                        ordinal=1,
                        data_type="nvarchar(5)",
                        normalized_type="string",
                        nullable=False,
                    ),
                ),
            ),
            TableMetadata(
                physical_id=sales_id,
                schema_name="sales",
                name="Orders",
                object_type="table",
                columns=(
                    ColumnMetadata(
                        physical_id=child_id(sales_id, "column", "OrderID"),
                        name="OrderID",
                        ordinal=1,
                        data_type="int",
                        normalized_type="integer",
                        nullable=False,
                    ),
                ),
            ),
        ),
    )


def test_fixture_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(fixture_payload(sample_metadata()), indent=2),
        encoding="utf-8",
    )
    loaded = load_metadata_fixture(path)
    assert loaded == sample_metadata()
    assert fixture_payload(loaded)["fixture_version"] == FIXTURE_VERSION


def test_raw_metadata_json_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "raw.json"
    path.write_text(
        json.dumps(sample_metadata().model_dump(mode="json", by_alias=True)),
        encoding="utf-8",
    )
    assert load_metadata_fixture(path) == sample_metadata()


def test_schema_filter_keeps_selected_schemas_and_objects() -> None:
    filtered = filter_metadata_schemas(sample_metadata(), ["sales"])
    assert [schema.name for schema in filtered.schemas] == ["sales"]
    assert [item.name for item in filtered.objects] == ["Orders"]


def test_unsupported_fixture_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(
            {
                "fixture_version": "99",
                "metadata": sample_metadata().model_dump(mode="json", by_alias=True),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FixtureError, match="Unsupported fixture version"):
        load_metadata_fixture(path)


def test_invalid_fixture_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FixtureError, match="not valid JSON"):
        load_metadata_fixture(path)


def test_wrong_fixture_shape_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"metadata": {"identity": {}}}), encoding="utf-8")
    with pytest.raises(FixtureError, match="does not match"):
        load_metadata_fixture(path)


def test_recorded_northwind_fixture_writes_repository_offline(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "northwind-metadata.json"
    metadata = load_metadata_fixture(fixture)
    assert metadata.identity.database == "Northwind"
    assert metadata.table_count == 13
    assert metadata.view_count == 16
    assert metadata.column_count == 190

    result = DdlRepositoryWriter(
        tmp_path / "ddl",
        clock=lambda: datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC),
        run_id_factory=lambda: "fixture-run",
        git_provider=lambda: GitState(available=False, detail="fixture run"),
        smo_provider=lambda: SmoStatus(available=False, detail="SMO not available."),
    ).write(metadata, source="fixture")

    assert result.status == "complete"
    assert result.counts["tables"] == 13
    assert result.counts["views"] == 16
    assert validate_repository(tmp_path / "ddl").valid is True
