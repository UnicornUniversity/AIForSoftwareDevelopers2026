from __future__ import annotations

import pytest

from uda.adapters import FakeAdapter
from uda.errors import AdapterError


def connected_adapter() -> FakeAdapter:
    adapter = FakeAdapter()
    adapter.connect()
    return adapter


def test_fake_adapter_satisfies_contract() -> None:
    adapter = connected_adapter()
    assert adapter.dialect == "tsql"
    assert adapter.list_schemas() == ("dbo",)
    objects = adapter.list_objects()
    assert [item.name for item in objects] == ["Customers", "Orders"]
    columns = adapter.describe_object(objects[0].physical_id)
    assert columns[0].name == "CustomerID"
    assert "CREATE TABLE" in adapter.extract_ddl(objects[0].physical_id)
    result = adapter.execute_read("SELECT 1", timeout_seconds=5, row_limit=10)
    assert result.rows == ((1,),)
    adapter.close()


def test_adapter_requires_connection() -> None:
    with pytest.raises(AdapterError, match="not connected"):
        FakeAdapter().list_schemas()


def test_fake_adapter_rejects_writes() -> None:
    adapter = connected_adapter()
    with pytest.raises(AdapterError, match="only accepts SELECT"):
        adapter.execute_read("DROP TABLE Customers", timeout_seconds=5, row_limit=10)


def test_operations_after_close_fail() -> None:
    adapter = connected_adapter()
    adapter.close()
    with pytest.raises(AdapterError, match="not connected"):
        adapter.list_schemas()
    with pytest.raises(AdapterError, match="not connected"):
        adapter.execute_read("SELECT 1", timeout_seconds=5, row_limit=10)


def test_close_is_idempotent() -> None:
    adapter = connected_adapter()
    adapter.close()
    adapter.close()


def test_unknown_object_errors() -> None:
    adapter = connected_adapter()
    with pytest.raises(AdapterError, match="Unknown object"):
        adapter.describe_object("sqlserver/Northwind/dbo/table/Missing")
    with pytest.raises(AdapterError, match="Unsupported object"):
        adapter.extract_ddl("sqlserver/Northwind/dbo/table/Missing")


def test_unknown_schema_returns_empty_for_the_fake() -> None:
    adapter = connected_adapter()
    assert adapter.list_objects("missing") == ()


def test_fake_does_not_model_row_limits_or_truncation() -> None:
    adapter = connected_adapter()
    result = adapter.execute_read("SELECT 1", timeout_seconds=1, row_limit=1)
    assert result.rows == ((1,),)
    assert result.truncated is False


def test_fake_introspect_contract() -> None:
    adapter = connected_adapter()
    metadata = adapter.introspect()
    assert metadata.identity.database == "Northwind"
    assert metadata.table_count == 2
    assert metadata.schemas[0].name == "dbo"
    assert metadata.objects[0].primary_key is not None
    assert metadata.objects[1].foreign_keys[0].referred_table == "Customers"


def test_fake_introspect_schema_filter() -> None:
    adapter = connected_adapter()
    assert adapter.introspect(schemas=["other"]).objects == ()
