"""Smoke tests for the repository layer.

Run OUTSIDE MCP — this is your first line of defense against schema/SQL bugs.
If these pass, plugging into Claude Desktop is a config problem, not a code one.

Usage:
    set NORTHWIND_CONN=Driver={ODBC Driver 18 for SQL Server};...
    python test_repository.py
"""

from __future__ import annotations

import json
import sys

from repository import (
    fetch_customer,
    fetch_employee,
    fetch_order,
    search_customers,
    top_customers,
)


def hr(title: str) -> None:
    print("\n" + "=" * 8 + f" {title} " + "=" * 8)


def main() -> int:
    hr("fetch_customer('ALFKI')")
    c = fetch_customer("ALFKI")
    assert c is not None, "ALFKI should exist in stock Northwind"
    assert c.company_name.startswith("Alfreds"), c.company_name
    assert len(c.orders) == 6, f"expected 6 orders, got {len(c.orders)}"
    print(f"  {c.company_name} — {len(c.orders)} orders, LTV ${c.lifetime_value:,.2f}")

    hr("fetch_customer('NOPEE') — unknown")
    missing = fetch_customer("NOPEE")
    assert missing is None
    print("  correctly returned None")

    hr("fetch_order(10248)")
    o = fetch_order(10248)
    assert o is not None
    assert len(o.lines) == 3, f"expected 3 lines, got {len(o.lines)}"
    print(f"  {o.customer_name} — {len(o.lines)} lines, total ${o.total:,.2f}")
    for line in o.lines:
        print(f"    - {line.product_name}: {line.quantity} @ ${line.unit_price}")

    hr("fetch_employee(2) — Andrew Fuller")
    e = fetch_employee(2)
    assert e is not None
    assert e.manager is None, "Fuller is the VP; no manager"
    assert len(e.direct_reports) > 0
    print(f"  {e.name} ({e.title})")
    print(f"    manager: {e.manager}")
    print(f"    direct reports: {[r.name for r in e.direct_reports]}")
    print(f"    YTD revenue: ${e.ytd_revenue:,.2f}")

    hr("search_customers(country='Germany')")
    de = search_customers(country="Germany")
    assert len(de) == 11, f"expected 11 German customers, got {len(de)}"
    print(f"  {len(de)} German customers:")
    for r in de[:3]:
        print(f"    - {r.customer_id}  {r.company_name}")
    print("    ...")

    hr("search_customers(name_like='rest') — LIKE guard")
    rest = search_customers(name_like="rest", limit=5)
    print(f"  matches: {[r.company_name for r in rest]}")

    hr("search_customers with a SQL-injection attempt")
    evil = search_customers(name_like="'; DROP TABLE Customers; --", limit=5)
    print(f"  result: {[r.company_name for r in evil]}  (should be empty, not an error)")

    hr("top_customers(limit=5)")
    top = top_customers(limit=5)
    print(json.dumps(top, indent=2))

    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\nASSERTION FAILED: {e}")
        sys.exit(1)
