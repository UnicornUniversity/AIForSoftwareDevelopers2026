from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uda.adapters.ddl import (
    PROVENANCE_TABLE,
    PROVENANCE_VIEW,
    DdlExtraction,
    DdlObject,
    normalize_ddl,
)
from uda.adapters.smo import SmoStatus
from uda.errors import RepositoryValidationError
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

FIXED_TIME = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
GIT = GitState(available=True, commit="c" * 40)
SMO = SmoStatus(available=True, version="17.0.0.0", mechanism="gac", detail="detected")

TABLE_DDL = (
    "SET ANSI_NULLS ON\n"
    "CREATE TABLE [dbo].[Customers] (\n"
    "    [CustomerID] int NOT NULL\n"
    ");\n"
)
VIEW_DDL = "create view Summary as select 1 as CustomerID\n"


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


def extraction(
    metadata: DatabaseMetadata,
    *,
    table_status: str = "extracted",
    view_status: str = "extracted",
    extra: tuple[DdlObject, ...] = (),
) -> DdlExtraction:
    objects: list[DdlObject] = []
    for item in metadata.objects:
        status = table_status if item.object_type == "table" else view_status
        if status == "extracted":
            if item.object_type == "table":
                objects.append(
                    DdlObject(
                        physical_id=item.physical_id,
                        kind="table",
                        status="extracted",
                        ddl=TABLE_DDL,
                        provenance=PROVENANCE_TABLE,
                        is_original_text=False,
                    )
                )
            else:
                objects.append(
                    DdlObject(
                        physical_id=item.physical_id,
                        kind="view",
                        status="extracted",
                        ddl=VIEW_DDL,
                        provenance=PROVENANCE_VIEW,
                        is_original_text=True,
                    )
                )
        else:
            objects.append(
                DdlObject(
                    physical_id=item.physical_id,
                    kind=item.object_type,
                    status=status,  # type: ignore[arg-type]
                    error=f"extraction {status}",
                )
            )
    objects.extend(extra)
    extracted = sum(1 for item in objects if item.status == "extracted")
    if extracted == len(objects):
        overall = "complete"
    elif extracted:
        overall = "partial"
    elif any(item.status == "failed" for item in objects):
        overall = "failed"
    else:
        overall = "unavailable"
    return DdlExtraction(
        status=overall,  # type: ignore[arg-type]
        mechanism="smo",
        version="17.0.0.0",
        detail="SMO extraction result.",
        objects=tuple(objects),
    )


def make_writer(root: Path, *, run_ids: tuple[str, ...] = ("run-1",)) -> DdlRepositoryWriter:
    iterator = iter(run_ids)
    return DdlRepositoryWriter(
        root,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: next(iterator),
        git_provider=lambda: GIT,
        smo_provider=lambda: SMO,
    )


def read_manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def test_ddl_artifacts_are_persisted_and_validated(tmp_path: Path) -> None:
    metadata = sample_metadata()
    result = make_writer(tmp_path).write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )

    assert result.ddl_status == "complete"
    assert result.ddl_extracted == 2
    assert result.ddl_object_count == 2
    assert (tmp_path / "ddl").is_dir()
    sql_files = sorted((tmp_path / "ddl").glob("*.sql"))
    assert len(sql_files) == 2
    manifest = read_manifest(tmp_path)
    ddl = manifest["extraction"]["ddl"]
    assert ddl["status"] == "complete"
    assert ddl["mechanism"] == "smo"
    assert ddl["version"] == "17.0.0.0"
    assert manifest["extraction"]["original_ddl"]["available"] is True
    assert len(ddl["objects"]) == 2
    for entry in ddl["objects"]:
        assert entry["status"] == "extracted"
        assert entry["path"].startswith("ddl/")
        assert entry["sha256"]
        assert entry["provenance"] in {PROVENANCE_TABLE, PROVENANCE_VIEW}
        assert "is_original_text" in entry
    validation = validate_repository(tmp_path)
    assert validation.valid is True, validation.errors


def test_ddl_content_is_preserved_not_synthesized(tmp_path: Path) -> None:
    metadata = sample_metadata()
    marker_table = TABLE_DDL.replace("CREATE TABLE", "-- PROVIDER-ORIGINAL\nCREATE TABLE")
    provider_extraction = extraction(metadata)
    provider_extraction = DdlExtraction(
        status="complete",
        mechanism="smo",
        version="17.0.0.0",
        detail="provider output",
        objects=tuple(
            DdlObject(
                physical_id=item.physical_id,
                kind=item.kind,
                status="extracted",
                ddl=(
                    marker_table
                    if item.kind == "table"
                    else VIEW_DDL
                ),
                provenance=item.provenance,
                is_original_text=item.is_original_text,
            )
            for item in provider_extraction.objects
        ),
    )
    make_writer(tmp_path).write(
        metadata, source="sqlserver", smo=SMO, ddl=provider_extraction
    )

    table_entry = next(
        item
        for item in read_manifest(tmp_path)["extraction"]["ddl"]["objects"]
        if item["kind"] == "table"
    )
    sql = (tmp_path / table_entry["path"]).read_text(encoding="utf-8")
    assert sql == normalize_ddl(marker_table)
    assert "PROVIDER-ORIGINAL" in sql
    json_artifact = next((tmp_path / "objects").glob("*table__Customers*.json"))
    assert "PROVIDER-ORIGINAL" not in json_artifact.read_text(encoding="utf-8")


def test_ddl_snapshot_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    metadata = sample_metadata()
    writer = make_writer(tmp_path, run_ids=("run-1", "run-2"))
    first = writer.write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    first_sql = {
        path.name: path.read_bytes() for path in sorted((tmp_path / "ddl").glob("*.sql"))
    }
    second = writer.write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    second_sql = {
        path.name: path.read_bytes() for path in sorted((tmp_path / "ddl").glob("*.sql"))
    }

    assert first.snapshot_id == second.snapshot_id
    assert first_sql == second_sql
    assert second.changes.added == ()
    assert second.changes.changed == ()
    assert second.changes.removed == ()


def test_snapshot_identity_changes_when_ddl_is_added(tmp_path: Path) -> None:
    metadata = sample_metadata()
    without = make_writer(tmp_path / "without").write(
        metadata, source="sqlserver", smo=SMO
    )
    with_ddl = make_writer(tmp_path / "with").write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    assert without.snapshot_id != with_ddl.snapshot_id


def test_partial_ddl_is_explicit_and_repository_stays_valid(tmp_path: Path) -> None:
    metadata = sample_metadata()
    result = make_writer(tmp_path).write(
        metadata,
        source="sqlserver",
        smo=SMO,
        ddl=extraction(metadata, table_status="extracted", view_status="failed"),
    )
    manifest = read_manifest(tmp_path)
    ddl = manifest["extraction"]["ddl"]

    assert result.status == "complete"
    assert result.ddl_status == "partial"
    assert result.ddl_extracted == 1
    assert manifest["snapshot"]["status"] == "complete"
    assert manifest["extraction"]["original_ddl"]["available"] is True
    view = next(item for item in ddl["objects"] if item["kind"] == "view")
    assert view["status"] == "failed"
    assert view["path"] is None
    assert view["sha256"] is None
    assert view["error"]
    assert validate_repository(tmp_path).valid is True


def test_unsupported_ddl_object_is_preserved_and_valid(tmp_path: Path) -> None:
    metadata = sample_metadata()
    result = make_writer(tmp_path).write(
        metadata,
        source="sqlserver",
        smo=SMO,
        ddl=extraction(
            metadata, table_status="unsupported", view_status="extracted"
        ),
    )
    manifest = read_manifest(tmp_path)
    assert result.ddl_status == "partial"
    table = next(
        item
        for item in manifest["extraction"]["ddl"]["objects"]
        if item["kind"] == "table"
    )
    assert table["status"] == "unsupported"
    assert table["path"] is None
    assert table["error"]
    assert validate_repository(tmp_path).valid is True


def test_unavailable_ddl_keeps_repository_valid(tmp_path: Path) -> None:
    metadata = sample_metadata()
    result = make_writer(tmp_path).write(
        metadata,
        source="sqlserver",
        smo=SMO,
        ddl=extraction(
            metadata, table_status="unavailable", view_status="unavailable"
        ),
    )
    manifest = read_manifest(tmp_path)
    assert result.ddl_status == "unavailable"
    assert result.ddl_extracted == 0
    assert not list((tmp_path / "ddl").glob("*.sql"))
    assert manifest["extraction"]["original_ddl"]["available"] is False
    assert all(
        item["status"] == "unavailable" for item in manifest["extraction"]["ddl"]["objects"]
    )
    assert validate_repository(tmp_path).valid is True


def test_failed_ddl_keeps_repository_valid(tmp_path: Path) -> None:
    metadata = sample_metadata()
    result = make_writer(tmp_path).write(
        metadata,
        source="sqlserver",
        smo=SMO,
        ddl=extraction(metadata, table_status="failed", view_status="failed"),
    )
    assert result.ddl_status == "failed"
    assert validate_repository(tmp_path).valid is True


def test_unknown_ddl_object_is_rejected_before_writing(tmp_path: Path) -> None:
    metadata = sample_metadata()
    extra = DdlObject(
        physical_id="sqlserver/Northwind/dbo/table/Ghost",
        kind="table",
        status="extracted",
        ddl="CREATE TABLE [dbo].[Ghost] (Id int);",
        provenance=PROVENANCE_TABLE,
    )
    with pytest.raises(RepositoryValidationError, match="not in the snapshot"):
        make_writer(tmp_path).write(
            metadata,
            source="sqlserver",
            smo=SMO,
            ddl=extraction(metadata, extra=(extra,)),
        )
    assert not (tmp_path / "manifest.json").exists()


def test_ddl_kind_mismatch_is_rejected(tmp_path: Path) -> None:
    metadata = sample_metadata()
    table = next(item for item in metadata.objects if item.object_type == "table")
    wrong = DdlObject(
        physical_id=table.physical_id,
        kind="view",
        status="extracted",
        ddl=VIEW_DDL,
        provenance=PROVENANCE_VIEW,
        is_original_text=True,
    )
    result = DdlExtraction(
        status="failed",
        mechanism="smo",
        version="17.0.0.0",
        detail="mismatch",
        objects=(wrong,),
    )
    with pytest.raises(RepositoryValidationError, match="does not match"):
        make_writer(tmp_path).write(
            metadata, source="sqlserver", smo=SMO, ddl=result
        )


def test_tampered_ddl_artifact_invalidates_repository(tmp_path: Path) -> None:
    metadata = sample_metadata()
    make_writer(tmp_path).write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    artifact = next((tmp_path / "ddl").glob("*.sql"))
    artifact.write_text(
        artifact.read_text(encoding="utf-8") + "-- tampered\n", encoding="utf-8"
    )
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("DDL artifact hash mismatch" in error for error in validation.errors)


def test_unreferenced_ddl_artifact_invalidates_repository(tmp_path: Path) -> None:
    metadata = sample_metadata()
    make_writer(tmp_path).write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    (tmp_path / "ddl" / "extra.sql").write_text("select 1;\n", encoding="utf-8")
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("Unreferenced artifact" in error for error in validation.errors)


def test_missing_ddl_entry_invalidates_repository(tmp_path: Path) -> None:
    metadata = sample_metadata()
    make_writer(tmp_path).write(
        metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata)
    )
    manifest = read_manifest(tmp_path)
    manifest["extraction"]["ddl"]["objects"] = manifest["extraction"]["ddl"]["objects"][:1]
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("missing" in error.lower() for error in validation.errors)


def test_legacy_manifest_without_ddl_section_still_validates(tmp_path: Path) -> None:
    metadata = sample_metadata()
    make_writer(tmp_path).write(metadata, source="sqlserver", smo=SMO)
    manifest = read_manifest(tmp_path)
    manifest["extraction"].pop("ddl")
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert validate_repository(tmp_path).valid is True


def test_ddl_files_are_removed_when_not_requested(tmp_path: Path) -> None:
    metadata = sample_metadata()
    writer = make_writer(tmp_path, run_ids=("run-1", "run-2"))
    writer.write(metadata, source="sqlserver", smo=SMO, ddl=extraction(metadata))
    assert list((tmp_path / "ddl").glob("*.sql"))
    result = writer.write(metadata, source="sqlserver", smo=SMO)
    assert result.ddl_status == "not_requested"
    assert not list((tmp_path / "ddl").glob("*.sql"))
    assert validate_repository(tmp_path).valid is True
