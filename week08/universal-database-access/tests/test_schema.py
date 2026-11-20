import json
import re
from pathlib import Path

import pytest

from uda.schema import (
    FixtureSchemaProvider,
    UnknownTableError,
    load_fixture_catalog,
    schema_version,
)


def test_fixture_provider_loads_products() -> None:
    schema = FixtureSchemaProvider().load("Products")

    assert schema.qualified_name == "dbo.Products"
    assert len(schema.columns) == 10
    primary_keys = [column.name for column in schema.columns if column.is_primary_key]
    assert primary_keys == ["ProductID"]
    assert all(column.is_primary_key is not None for column in schema.columns)


def test_fixture_lookup_is_case_insensitive_and_qualified() -> None:
    provider = FixtureSchemaProvider()

    assert provider.load("products").qualified_name == "dbo.Products"
    assert provider.load("dbo.products").qualified_name == "dbo.Products"


def test_unknown_table_is_rejected() -> None:
    with pytest.raises(UnknownTableError, match="not present"):
        FixtureSchemaProvider().load("Missing")


def test_empty_table_reference_is_rejected() -> None:
    with pytest.raises(UnknownTableError, match="empty"):
        FixtureSchemaProvider().load("   ")


def test_custom_fixture_path_is_used(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "fixture_version": 1,
                "tables": [
                    {
                        "schema_name": "dbo",
                        "table_name": "Thing",
                        "columns": [
                            {
                                "name": "thing_id",
                                "sql_type": "int",
                                "nullable": False,
                                "is_primary_key": True,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    schema = FixtureSchemaProvider(fixture).load("Thing")

    assert schema.qualified_name == "dbo.Thing"
    assert schema.columns[0].sql_type == "int"


def test_catalog_is_loaded_from_package_data() -> None:
    catalog = load_fixture_catalog()

    assert catalog.fixture_version == 1
    assert [table.table_name for table in catalog.tables] == [
        "Products",
        "Categories",
        "Customer",
    ]


def test_schema_version_is_deterministic_and_well_formed() -> None:
    schema = FixtureSchemaProvider().load("Products")

    first = schema_version(schema)
    second = schema_version(schema)

    assert first == second
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first)


def test_schema_version_ignores_column_order() -> None:
    schema = FixtureSchemaProvider().load("Products")
    reordered = schema.model_copy(
        update={"columns": tuple(reversed(schema.columns))}
    )

    assert schema_version(reordered) == schema_version(schema)


def test_schema_version_changes_with_physical_details() -> None:
    schema = FixtureSchemaProvider().load("Products")
    base = schema_version(schema)
    first = schema.columns[0]
    rest = schema.columns[1:]

    changed_type = schema.model_copy(
        update={
            "columns": (
                first.model_copy(update={"sql_type": "bigint"}),
                *rest,
            )
        }
    )
    changed_nullability = schema.model_copy(
        update={
            "columns": (
                first.model_copy(update={"nullable": not first.nullable}),
                *rest,
            )
        }
    )
    changed_primary_key = schema.model_copy(
        update={
            "columns": (
                first.model_copy(update={"is_primary_key": None}),
                *rest,
            )
        }
    )

    assert schema_version(changed_type) != base
    assert schema_version(changed_nullability) != base
    assert schema_version(changed_primary_key) != base
