"""Northwind MCP server — entity-shaped tools over MS SQL Server.

Design principle: the LLM sees domain aggregates (Customer, Order, Employee),
not database tables. See ../theory/09-northwind-mcp-server.md.

Run:
    python server.py

Or plug into Claude Desktop via claude_desktop_config.json:
    {
      "mcpServers": {
        "northwind": {
          "command": "python",
          "args": ["C:\\\\absolute\\\\path\\\\to\\\\server.py"]
        }
      }
    }
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from repository import (
    fetch_customer,
    fetch_employee,
    fetch_order,
    search_customers,
    top_customers,
)


# Log to a file next to the server. MCP servers run as subprocesses; stdout is
# claimed by the JSON-RPC protocol, so never print() from a tool.
LOG_PATH = Path(__file__).with_name("northwind-mcp.log")
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("northwind-mcp")


mcp = FastMCP("northwind")


@mcp.tool()
def get_customer(customer_id: str) -> dict:
    """Fetch a customer with their full order history and lifetime value.

    Returns the customer's company info plus a list of OrderSummary objects
    (order_id, date, ship_country, total) — use get_order to expand any one.

    Args:
        customer_id: The 5-letter Northwind customer code, e.g. 'ALFKI', 'QUICK'.
    """
    log.info("get_customer(%s)", customer_id)
    result = fetch_customer(customer_id)
    if result is None:
        return {"error": f"unknown customer: {customer_id}"}
    return result.model_dump(mode="json")


@mcp.tool()
def get_order(order_id: int) -> dict:
    """Fetch a single order with its line items, customer, and employee.

    Line items include product names (resolved from ProductID) and per-line
    totals. Order totals include discounts.

    Args:
        order_id: The numeric Northwind OrderID (10248..11077 in stock data).
    """
    log.info("get_order(%s)", order_id)
    result = fetch_order(order_id)
    if result is None:
        return {"error": f"unknown order: {order_id}"}
    return result.model_dump(mode="json")


@mcp.tool()
def get_employee(employee_id: int) -> dict:
    """Fetch an employee with their manager, direct reports, and YTD revenue.

    YTD is anchored on the most recent year present in the Northwind data
    (Northwind orders end in 1998), not the calendar year.

    Args:
        employee_id: The numeric Northwind EmployeeID (1..9 in stock data).
    """
    log.info("get_employee(%s)", employee_id)
    result = fetch_employee(employee_id)
    if result is None:
        return {"error": f"unknown employee: {employee_id}"}
    return result.model_dump(mode="json")


@mcp.tool()
def find_customers(
    country: str | None = None,
    name_like: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search customers by country and/or partial company name.

    Returns compact search results ({customer_id, company_name, country}).
    Use get_customer to fetch full details for a specific match.

    Args:
        country: Country name as stored in Northwind ('Germany', 'USA', 'France', ...).
        name_like: Case-insensitive substring of the company name.
        limit: Max rows to return, clamped to 1..100. Default 20.
    """
    log.info("find_customers(country=%s, name_like=%s, limit=%s)", country, name_like, limit)
    results = search_customers(country=country, name_like=name_like, limit=limit)
    return [r.model_dump(mode="json") for r in results]


@mcp.tool()
def get_top_customers(limit: int = 10) -> list[dict]:
    """Top customers by all-time revenue.

    Returns {customer_id, company_name, country, revenue}, sorted descending.
    Use get_customer to expand any of them.

    Args:
        limit: How many customers to return, clamped to 1..50. Default 10.
    """
    log.info("get_top_customers(limit=%s)", limit)
    return top_customers(limit=limit)


@mcp.resource("northwind://schema")
def schema() -> str:
    """Northwind entity map — attach this to a conversation for context."""
    return """Northwind entities exposed by this server:

- Customer (root): fetched by 5-letter code (e.g. 'ALFKI').
  Includes: contact info, order history (summaries), lifetime value.
- Order (root): fetched by numeric OrderID (10248..11077 in stock data).
  Includes: header, customer summary, employee, line items with product names.
- Employee (root): fetched by EmployeeID (1..9 in stock data).
  Includes: manager (nullable), direct reports, YTD revenue.

Search / analytics:
- find_customers(country, name_like, limit) — narrow filter, returns summaries.
- get_top_customers(limit) — top customers by all-time revenue.

Line items are NOT a separate entity — they live inside Order.
Northwind orders are historical (1996-07 to 1998-05). Treat 'this year' as
'the most recent year present in the data' (1998).
"""


if __name__ == "__main__":
    log.info("northwind MCP server starting (pid=%s)", __import__("os").getpid())
    try:
        mcp.run()
    except Exception:
        log.exception("server crashed")
        sys.exit(1)
