from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uda.adapters.smo import SmoStatus
from uda.errors import RepositoryPathError, RepositoryValidationError, RepositoryWriteError
from uda.metadata.models import (
    ColumnMetadata,
    DatabaseIdentity,
    DatabaseMetadata,
    ExtractionIssue,
    ForeignKeyMetadata,
    IndexMetadata,
    PrimaryKeyMetadata,
    SchemaMetadata,
    TableMetadata,
    child_id,
    make_physical_id,
)
from uda.repository import (
    DdlRepositoryWriter,
    GitState,
    validate_repository,
)
from uda.repository.naming import (
    artifact_filename,
    artifact_relative_path,
    resolve_within,
    safe_relative_path,
    slugify,
)

FIXED_TIME = datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC)
GIT = GitState(available=True, commit="a" * 40)
SMO = SmoStatus(
    available=True,
    version="17.0.0.0",
    mechanism="gac",
    detail="SMO assembly detected.",
)


def _column(
    object_id: str,
    name: str,
    ordinal: int,
    data_type: str = "int",
    normalized_type: str | None = "integer",
    **extra: object,
) -> ColumnMetadata:
    return ColumnMetadata(
        physical_id=child_id(object_id, "column", name),
        name=name,
        ordinal=ordinal,
        data_type=data_type,
        normalized_type=normalized_type,
        nullable=False,
        **extra,
    )


def sample_metadata(
    *,
    description: str | None = "Customer master",
    include_customers: bool = True,
    include_orders: bool = True,
    include_summary: bool = False,
    issues: tuple[ExtractionIssue, ...] = (),
    orders_schema: str = "sales",
    referred_schema: str = "dbo",
) -> DatabaseMetadata:
    identity = DatabaseIdentity(platform="sqlserver", database="Northwind")
    schema_models = [
        SchemaMetadata(
            physical_id=make_physical_id("sqlserver", "Northwind", "schema", "dbo"),
            name="dbo",
        ),
        SchemaMetadata(
            physical_id=make_physical_id("sqlserver", "Northwind", "schema", "sales"),
            name="sales",
        ),
    ]
    objects: list[TableMetadata] = []
    if include_customers:
        object_id = make_physical_id(
            "sqlserver", "Northwind", "dbo", "table", "Customers"
        )
        objects.append(
            TableMetadata(
                physical_id=object_id,
                schema_name="dbo",
                name="Customers",
                object_type="table",
                columns=(
                    _column(object_id, "CustomerID", 1, "nvarchar(5)", "string"),
                    _column(object_id, "CompanyName", 2, "nvarchar(40)", "string"),
                ),
                primary_key=PrimaryKeyMetadata(
                    name="PK_Customers", columns=("CustomerID",)
                ),
                indexes=(
                    IndexMetadata(
                        name="IX_Customers_CompanyName",
                        columns=("CompanyName",),
                    ),
                ),
                description=description,
            )
        )
    if include_orders:
        object_id = make_physical_id(
            "sqlserver", "Northwind", orders_schema, "table", "Orders"
        )
        objects.append(
            TableMetadata(
                physical_id=object_id,
                schema_name=orders_schema,
                name="Orders",
                object_type="table",
                columns=(
                    _column(object_id, "OrderID", 1),
                    _column(object_id, "LineNo", 2),
                    _column(object_id, "CustomerID", 3, "nvarchar(5)", "string"),
                    _column(
                        object_id,
                        "Total",
                        4,
                        "decimal(10, 2)",
                        "decimal",
                        is_computed=True,
                        computed_expression="Quantity * UnitPrice",
                    ),
                ),
                primary_key=PrimaryKeyMetadata(
                    name="PK_Orders", columns=("OrderID", "LineNo")
                ),
                foreign_keys=(
                    ForeignKeyMetadata(
                        name="FK_Orders_Customers",
                        columns=("CustomerID",),
                        referred_schema=referred_schema,
                        referred_table="Customers",
                        referred_columns=("CustomerID",),
                    ),
                ),
                indexes=(
                    IndexMetadata(name="IX_Orders_Customer", columns=("CustomerID",)),
                ),
            )
        )
        if orders_schema != "sales":
            schema_models.append(
                SchemaMetadata(
                    physical_id=make_physical_id(
                        "sqlserver", "Northwind", "schema", orders_schema
                    ),
                    name=orders_schema,
                )
            )
    if include_summary:
        object_id = make_physical_id(
            "sqlserver", "Northwind", "dbo", "view", "CustomerSummary"
        )
        objects.append(
            TableMetadata(
                physical_id=object_id,
                schema_name="dbo",
                name="CustomerSummary",
                object_type="view",
                columns=(_column(object_id, "CustomerID", 1, "nvarchar(5)", "string"),),
            )
        )
    return DatabaseMetadata(
        identity=identity,
        schemas=tuple(
            sorted(schema_models, key=lambda item: item.name)
        ),
        objects=tuple(objects),
        issues=issues,
    )


def make_writer(
    root: Path,
    *,
    run_ids: tuple[str, ...] = ("run-1",),
    git: GitState = GIT,
) -> DdlRepositoryWriter:
    iterator = iter(run_ids)

    def next_run_id() -> str:
        return next(iterator)

    return DdlRepositoryWriter(
        root,
        clock=lambda: FIXED_TIME,
        run_id_factory=next_run_id,
        git_provider=lambda: git,
        smo_provider=lambda: SMO,
    )


def read_manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def strip_run_metadata(manifest: dict[str, object]) -> dict[str, object]:
    data = json.loads(json.dumps(manifest))
    snapshot = data["snapshot"]
    extraction = data["extraction"]
    snapshot.pop("run_id")
    snapshot.pop("created_at")
    extraction.pop("started_at")
    extraction.pop("completed_at")
    return data


def artifact_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
        if path.name != "manifest.json"
    }


def test_write_creates_manifest_issues_and_validates(tmp_path: Path) -> None:
    result = make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)

    assert result.status == "complete"
    assert result.issue_count == 0
    assert result.snapshot_id.startswith("sha256:")
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "issues.json").read_text(encoding="utf-8").strip() == "[]"
    assert result.counts == {
        "schemas": 2,
        "tables": 2,
        "views": 0,
        "columns": 6,
        "primary_keys": 2,
        "foreign_keys": 1,
        "indexes": 2,
    }
    validation = validate_repository(tmp_path)
    assert validation.valid is True
    assert validation.errors == ()
    assert validation.status == "complete"


def test_consecutive_runs_change_only_run_metadata(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, run_ids=("run-1", "run-2"))
    first = writer.write(sample_metadata(), source="sqlserver", smo=SMO)
    first_artifacts = artifact_bytes(tmp_path)
    first_manifest = read_manifest(tmp_path)

    second = writer.write(sample_metadata(), source="sqlserver", smo=SMO)
    second_artifacts = artifact_bytes(tmp_path)
    second_manifest = read_manifest(tmp_path)

    assert first.snapshot_id == second.snapshot_id
    assert first.run_id != second.run_id
    assert first_artifacts == second_artifacts
    assert strip_run_metadata(first_manifest) == strip_run_metadata(second_manifest)
    assert second.changes.added == ()
    assert second.changes.changed == ()
    assert second.changes.removed == ()


def test_input_ordering_does_not_change_artifacts(tmp_path: Path) -> None:
    metadata = sample_metadata()
    scrambled = metadata.model_copy(update={"objects": tuple(reversed(metadata.objects))})

    left = tmp_path / "left"
    right = tmp_path / "right"
    make_writer(left).write(metadata, source="fixture", smo=SMO)
    make_writer(right).write(scrambled, source="fixture", smo=SMO)

    assert artifact_bytes(left) == artifact_bytes(right)
    assert strip_run_metadata(read_manifest(left)) == strip_run_metadata(
        read_manifest(right)
    )


def test_stable_physical_ids_are_persisted(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)
    manifest = read_manifest(tmp_path)
    object_entry = next(
        item
        for item in manifest["artifacts"]["objects"]
        if item["physical_id"].endswith("/sales/table/Orders")
    )
    artifact = json.loads(
        (tmp_path / object_entry["path"]).read_text(encoding="utf-8")
    )

    object_id = artifact["physical_id"]
    assert object_id == "sqlserver/Northwind/sales/table/Orders"
    assert artifact["columns"][0]["physical_id"] == f"{object_id}/column/OrderID"
    assert artifact["primary_key"]["physical_id"] == (
        f"{object_id}/primary_key/PK_Orders"
    )
    assert artifact["primary_key"]["column_ids"] == [
        f"{object_id}/column/OrderID",
        f"{object_id}/column/LineNo",
    ]
    foreign_key = artifact["foreign_keys"][0]
    assert foreign_key["physical_id"] == f"{object_id}/foreign_key/FK_Orders_Customers"
    assert foreign_key["referred_object_id"] == (
        "sqlserver/Northwind/dbo/table/Customers"
    )
    assert foreign_key["referred_column_ids"] == [
        "sqlserver/Northwind/dbo/table/Customers/column/CustomerID"
    ]
    assert artifact["indexes"][0]["physical_id"] == (
        f"{object_id}/index/IX_Orders_Customer"
    )


def test_manifest_records_required_fields(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="sqlserver", smo=SMO)
    manifest = read_manifest(tmp_path)

    assert manifest["manifest_version"] == "1.0"
    assert manifest["repository"] == "ddl"
    assert manifest["schema_version"] == "1.0"
    assert manifest["generator"]["name"] == "uda"
    assert manifest["generator"]["version"]
    assert manifest["snapshot"]["id"].startswith("sha256:")
    assert manifest["snapshot"]["run_id"] == "run-1"
    assert manifest["snapshot"]["status"] == "complete"
    assert manifest["git"] == {"available": True, "commit": "a" * 40, "detail": None}
    assert manifest["database"]["name"] == "Northwind"
    assert manifest["database"]["schemas"] == ["dbo", "sales"]
    assert manifest["extraction"]["source"] == "sqlserver"
    assert manifest["extraction"]["smo"]["version"] == "17.0.0.0"
    assert manifest["extraction"]["original_ddl"]["available"] is False
    assert len(manifest["artifacts"]["schemas"]) == 2
    assert len(manifest["artifacts"]["objects"]) == 2


def test_git_unavailable_is_recorded_explicitly(tmp_path: Path) -> None:
    make_writer(
        tmp_path,
        git=GitState(available=False, detail="Git commit unavailable."),
    ).write(sample_metadata(), source="fixture", smo=SMO)
    manifest = read_manifest(tmp_path)
    assert manifest["git"] == {
        "available": False,
        "commit": None,
        "detail": "Git commit unavailable.",
    }


def test_smo_unavailable_is_recorded_without_failing_snapshot(tmp_path: Path) -> None:
    unavailable = SmoStatus(available=False, detail="SMO not found.")
    result = make_writer(tmp_path).write(
        sample_metadata(), source="fixture", smo=unavailable
    )
    manifest = read_manifest(tmp_path)
    assert result.status == "complete"
    assert manifest["extraction"]["smo"]["available"] is False
    assert manifest["extraction"]["smo"]["detail"] == "SMO not found."


def test_partial_extraction_is_never_presented_as_complete(tmp_path: Path) -> None:
    issue = ExtractionIssue(
        kind="permission",
        object_id="sqlserver/Northwind/dbo/table/Hidden",
        detail="read columns unavailable (OperationalError)",
    )
    result = make_writer(tmp_path).write(
        sample_metadata(issues=(issue,)), source="sqlserver", smo=SMO
    )
    manifest = read_manifest(tmp_path)
    issues = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))

    assert result.status == "partial"
    assert result.issue_count == 1
    assert manifest["snapshot"]["status"] == "partial"
    assert manifest["extraction"]["issue_count"] == 1
    assert manifest["extraction"]["issues"]["count"] == 1
    assert issues[0]["kind"] == "permission"
    validation = validate_repository(tmp_path)
    assert validation.valid is True
    assert validation.status == "partial"


def test_unsupported_type_issue_is_preserved(tmp_path: Path) -> None:
    issue = ExtractionIssue(
        kind="unsupported_type",
        object_id="sqlserver/Northwind/dbo/table/Customers/column/Shape",
        detail="Unmapped SQL Server type: geography",
    )
    make_writer(tmp_path).write(
        sample_metadata(issues=(issue,)), source="sqlserver", smo=SMO
    )
    issues = json.loads((tmp_path / "issues.json").read_text(encoding="utf-8"))
    assert issues == [
        {
            "kind": "unsupported_type",
            "object_id": "sqlserver/Northwind/dbo/table/Customers/column/Shape",
            "detail": "Unmapped SQL Server type: geography",
        }
    ]


def test_added_changed_and_removed_objects(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, run_ids=("run-1", "run-2"))
    writer.write(sample_metadata(), source="fixture", smo=SMO)
    first_manifest = read_manifest(tmp_path)
    removed_path = next(
        item["path"]
        for item in first_manifest["artifacts"]["objects"]
        if item["physical_id"].endswith("/sales/table/Orders")
    )

    result = writer.write(
        sample_metadata(
            description="Customer master (revised)",
            include_orders=False,
            include_summary=True,
        ),
        source="fixture",
        smo=SMO,
    )

    customers_id = "sqlserver/Northwind/dbo/table/Customers"
    summary_id = "sqlserver/Northwind/dbo/view/CustomerSummary"
    orders_id = "sqlserver/Northwind/sales/table/Orders"
    assert result.changes.changed == (customers_id,)
    assert result.changes.added == (summary_id,)
    assert result.changes.removed == (orders_id,)
    assert not (tmp_path / removed_path).exists()
    assert validate_repository(tmp_path).valid is True


def test_empty_database_is_valid(tmp_path: Path) -> None:
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="EmptyDb")
    )
    result = make_writer(tmp_path).write(metadata, source="sqlserver", smo=SMO)
    manifest = read_manifest(tmp_path)
    assert result.counts == {
        "schemas": 0,
        "tables": 0,
        "views": 0,
        "columns": 0,
        "primary_keys": 0,
        "foreign_keys": 0,
        "indexes": 0,
    }
    assert manifest["artifacts"] == {"objects": [], "schemas": []}
    assert validate_repository(tmp_path).valid is True


def test_empty_schema_is_valid(tmp_path: Path) -> None:
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="EmptyDb"),
        schemas=(
            SchemaMetadata(
                physical_id="sqlserver/EmptyDb/schema/dbo", name="dbo"
            ),
        ),
    )
    make_writer(tmp_path).write(metadata, source="sqlserver", smo=SMO)
    assert validate_repository(tmp_path).valid is True


def test_missing_internal_foreign_key_target_rejects_snapshot(tmp_path: Path) -> None:
    with pytest.raises(RepositoryValidationError, match="missing from the snapshot"):
        make_writer(tmp_path).write(
            sample_metadata(include_customers=False), source="fixture", smo=SMO
        )
    assert not (tmp_path / "manifest.json").exists()


def test_external_cross_schema_reference_is_recorded(tmp_path: Path) -> None:
    metadata = sample_metadata(referred_schema="archive")
    result = make_writer(tmp_path).write(metadata, source="fixture", smo=SMO)
    manifest = read_manifest(tmp_path)
    assert result.status == "complete"
    assert manifest["external_references"] == [
        {
            "source_id": (
                "sqlserver/Northwind/sales/table/Orders/foreign_key/"
                "FK_Orders_Customers"
            ),
            "target_id": "sqlserver/Northwind/archive/table/Customers",
        }
    ]
    assert validate_repository(tmp_path).valid is True


def test_validation_detects_hash_tampering(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)
    artifact = next((tmp_path / "objects").glob("*.json"))
    artifact.write_text(artifact.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("hash mismatch" in error for error in validation.errors)


def test_validation_detects_unreferenced_artifact(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)
    (tmp_path / "objects" / "extra.json").write_text("{}", encoding="utf-8")
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("Unreferenced artifact" in error for error in validation.errors)


def test_validation_detects_snapshot_identity_mismatch(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)
    manifest = read_manifest(tmp_path)
    manifest["snapshot"]["id"] = "sha256:" + "0" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("Snapshot identity" in error for error in validation.errors)


def test_validation_detects_complete_snapshot_with_issues(tmp_path: Path) -> None:
    issue = ExtractionIssue(kind="permission", detail="columns unavailable")
    make_writer(tmp_path).write(
        sample_metadata(issues=(issue,)), source="fixture", smo=SMO
    )
    manifest = read_manifest(tmp_path)
    manifest["snapshot"]["status"] = "complete"
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any("marked complete" in error for error in validation.errors)


def test_write_failure_is_reported_and_no_manifest_is_written(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    calls = {"count": 0}
    original = writer._write_if_changed  # noqa: SLF001 - fault injection

    def failing_write(path: Path, content: bytes) -> bool:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RepositoryWriteError("Injected write failure.")
        return original(path, content)

    writer._write_if_changed = failing_write  # type: ignore[method-assign]

    with pytest.raises(RepositoryWriteError, match="Injected write failure"):
        writer.write(sample_metadata(), source="fixture", smo=SMO)
    assert not (tmp_path / "manifest.json").exists()


def test_validation_of_missing_repository(tmp_path: Path) -> None:
    validation = validate_repository(tmp_path / "missing")
    assert validation.valid is False
    assert any("Manifest not found" in error for error in validation.errors)


def test_manifest_path_traversal_is_rejected(tmp_path: Path) -> None:
    make_writer(tmp_path).write(sample_metadata(), source="fixture", smo=SMO)
    manifest = read_manifest(tmp_path)
    manifest["artifacts"]["objects"][0]["path"] = "../outside.json"
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation = validate_repository(tmp_path)
    assert validation.valid is False
    assert any(
        "relative" in error.lower() or "escape" in error.lower()
        for error in validation.errors
    )


def test_naming_is_windows_safe_and_case_distinct(tmp_path: Path) -> None:
    risky_names = (
        "A/B",
        "A:B",
        "A*B",
        "CON",
        " leading ",
        "." * 3,
        "x" * 300,
        "Customers",
        "customers",
    )
    paths: list[str] = []
    for name in risky_names:
        physical_id = make_physical_id("sqlserver", "Northwind", "dbo", "table", name)
        filename = artifact_filename(physical_id)
        assert not any(character in filename for character in '<>:"/\\|?*')
        assert filename.endswith(".json")
        assert len(filename) < 150
        assert filename.split("--", 1)[0].upper() not in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
        }
        path = artifact_relative_path("table", physical_id)
        assert str(path).startswith("objects/")
        paths.append(str(path).lower())
    assert len(set(paths)) == len(paths)


def test_slugify_handles_reserved_and_blank_values() -> None:
    assert slugify("CON") == "_CON"
    assert slugify("   ") == "unnamed"
    assert slugify("a b") == "a_b"


def test_safe_paths_reject_escapes(tmp_path: Path) -> None:
    with pytest.raises(RepositoryPathError):
        safe_relative_path("../outside.json")
    with pytest.raises(RepositoryPathError):
        safe_relative_path("C:/outside.json")
    with pytest.raises(RepositoryPathError):
        resolve_within(tmp_path, "../outside.json")
    with pytest.raises(RepositoryPathError):
        artifact_relative_path("routine", "sqlserver/db/dbo/routine/usp")
