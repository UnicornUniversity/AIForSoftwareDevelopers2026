from __future__ import annotations

import pytest

from uda.query.sql_safety import validate_read_query

ALLOWED = frozenset({"dbo.customers", "dbo.orders", "dbo.products"})


def validate(sql: str) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    result = validate_read_query(
        sql, allowed_objects=ALLOWED, default_schema="dbo", database="Northwind"
    )
    return result.valid, result.errors, result.tables


def test_single_select_is_accepted() -> None:
    valid, errors, tables = validate("SELECT TOP (5) * FROM dbo.Customers ORDER BY CustomerID")
    assert valid
    assert errors == ()
    assert tables == ("dbo.customers",)


def test_join_is_accepted() -> None:
    valid, _, tables = validate(
        "SELECT c.CustomerID, o.OrderID FROM dbo.Customers c "
        "JOIN dbo.Orders o ON o.CustomerID = c.CustomerID"
    )
    assert valid
    assert set(tables) == {"dbo.customers", "dbo.orders"}


def test_bare_table_name_uses_default_schema() -> None:
    valid, _, tables = validate("SELECT * FROM Orders")
    assert valid
    assert tables == ("dbo.orders",)


def test_cte_reference_is_not_treated_as_a_table() -> None:
    valid, errors, tables = validate(
        "WITH ranked AS (SELECT TOP (3) * FROM dbo.Products) SELECT * FROM ranked"
    )
    assert valid
    assert errors == ()
    assert tables == ("dbo.products",)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dbo.Orders",
        "UPDATE dbo.Orders SET CustomerID = 'X'",
        "INSERT INTO dbo.Orders (OrderID) VALUES (1)",
        "CREATE TABLE dbo.Evil (id int)",
        "DROP TABLE dbo.Orders",
        "EXEC sp_who",
    ],
)
def test_non_select_statements_are_rejected(sql: str) -> None:
    valid, errors, _ = validate(sql)
    assert not valid
    assert errors


def test_statement_stacking_is_rejected() -> None:
    valid, errors, _ = validate("SELECT 1; DROP TABLE dbo.Orders")
    assert not valid
    assert "Statement stacking" in errors[0]


def test_select_into_is_rejected() -> None:
    valid, errors, _ = validate("SELECT * INTO #copy FROM dbo.Orders")
    assert not valid
    assert "disallowed operation" in errors[0]


def test_object_outside_allowlist_is_rejected() -> None:
    valid, errors, _ = validate("SELECT * FROM sys.tables")
    assert not valid
    assert "not in the approved query scope" in errors[0]


def test_unparsable_sql_is_rejected() -> None:
    valid, errors, _ = validate("SELEC * FRO dbo.Orders")
    assert not valid
    assert "does not parse" in errors[0]


def test_empty_sql_is_rejected() -> None:
    valid, errors, _ = validate("   ")
    assert not valid
    assert errors == ("The SQL statement is empty.",)
