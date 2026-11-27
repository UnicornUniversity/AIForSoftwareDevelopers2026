"""Contrast server for Exercise 9.5: the *raw-SQL* MCP variant.

Exposes one tool — `run_query` — that runs arbitrary SELECT statements.
This is the "wrong" way, deliberately. Compare its behaviour against server.py
on the same domain questions and see the entity-vs-table trade-off in action.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyodbc
from mcp.server.fastmcp import FastMCP


LOG_PATH = Path(__file__).with_name("northwind-raw-mcp.log")
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("northwind-raw-mcp")


mcp = FastMCP("northwind-raw")


def _default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"unserialisable type: {type(obj).__name__}")


@mcp.tool()
def run_query(sql: str) -> str:
    """Run a read-only SELECT against the Northwind database.

    Only SELECT statements are permitted. Results are capped at 200 rows.
    Returns a JSON array of objects.

    Args:
        sql: A single SELECT statement. Do not include a trailing semicolon.
    """
    log.info("run_query: %s", sql)

    stripped = sql.strip().lower()
    if not stripped.startswith("select"):
        return json.dumps({"error": "only SELECT statements are allowed"})
    # Cheap belt-and-braces against multi-statement injection.
    if ";" in sql.rstrip(";"):
        return json.dumps({"error": "multi-statement SQL is not allowed"})

    try:
        with pyodbc.connect(os.environ["NORTHWIND_CONN"], readonly=True) as cx:
            cursor = cx.execute(sql)
            rows = cursor.fetchmany(200)
            cols = [c[0] for c in cursor.description or []]
    except pyodbc.Error as e:
        return json.dumps({"error": f"SQL error: {e}"})

    return json.dumps(
        [dict(zip(cols, r)) for r in rows],
        default=_default,
    )


@mcp.resource("northwind://schema")
def schema() -> str:
    """A brief hint about the schema — deliberately terse, unlike server.py."""
    return """Northwind is the classic Microsoft sample database.
Tables include: Customers, Orders, [Order Details], Employees, Products,
Categories, Suppliers, Shippers, Region, Territories, EmployeeTerritories.

Line item join: Orders.OrderID = [Order Details].OrderID.
Revenue per line: UnitPrice * Quantity * (1 - Discount).
"""


if __name__ == "__main__":
    log.info("northwind-raw MCP server starting")
    mcp.run()
