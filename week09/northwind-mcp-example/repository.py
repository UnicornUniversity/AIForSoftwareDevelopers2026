"""Repository layer: one function per entity fetch.

Rules of the house:
- Parameterised queries only (`?` placeholders, never f-strings or `%`).
- Read-only connection (`readonly=True`) — belt-and-braces on top of the
  read-only SQL login the server is configured to use.
- Return typed Pydantic models, not raw rows.
- Small, self-contained SQL. Two queries stitched together in Python beats one
  clever query nobody can debug.
"""

from __future__ import annotations

import os
import pyodbc

from models import (
    Customer,
    CustomerSearchResult,
    Employee,
    EmployeeSummary,
    Order,
    OrderLine,
    OrderSummary,
)


def _conn_string() -> str:
    try:
        return os.environ["NORTHWIND_CONN"]
    except KeyError as e:
        raise RuntimeError(
            "NORTHWIND_CONN env var is not set. See README.md for the format."
        ) from e


def _cx() -> pyodbc.Connection:
    return pyodbc.connect(_conn_string(), readonly=True)


# ---------- Customer ----------

def fetch_customer(customer_id: str) -> Customer | None:
    with _cx() as cx:
        cust = cx.execute(
            """
            SELECT CustomerID, CompanyName, ContactName, Country, Phone
            FROM Customers WHERE CustomerID = ?
            """,
            customer_id,
        ).fetchone()
        if cust is None:
            return None

        orders = cx.execute(
            """
            SELECT o.OrderID, o.OrderDate, o.ShipCountry,
                   SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)) AS Total
            FROM Orders o
            JOIN [Order Details] od ON od.OrderID = o.OrderID
            WHERE o.CustomerID = ?
            GROUP BY o.OrderID, o.OrderDate, o.ShipCountry
            ORDER BY o.OrderDate DESC
            """,
            customer_id,
        ).fetchall()

    summaries = [
        OrderSummary(
            order_id=o.OrderID,
            order_date=o.OrderDate,
            ship_country=o.ShipCountry,
            total=float(o.Total or 0),
        )
        for o in orders
    ]

    return Customer(
        customer_id=cust.CustomerID,
        company_name=cust.CompanyName,
        contact_name=cust.ContactName,
        country=cust.Country,
        phone=cust.Phone,
        orders=summaries,
        lifetime_value=sum(s.total for s in summaries),
    )


def search_customers(
    country: str | None = None,
    name_like: str | None = None,
    limit: int = 20,
) -> list[CustomerSearchResult]:
    limit = max(1, min(limit, 100))

    where: list[str] = []
    params: list[object] = []
    if country:
        where.append("Country = ?")
        params.append(country)
    if name_like:
        where.append("CompanyName LIKE ?")
        params.append(f"%{name_like}%")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT TOP ({limit}) CustomerID, CompanyName, Country
        FROM Customers
        {where_sql}
        ORDER BY CompanyName
    """

    with _cx() as cx:
        rows = cx.execute(sql, *params).fetchall()

    return [
        CustomerSearchResult(
            customer_id=r.CustomerID,
            company_name=r.CompanyName,
            country=r.Country,
        )
        for r in rows
    ]


# ---------- Order ----------

def fetch_order(order_id: int) -> Order | None:
    with _cx() as cx:
        header = cx.execute(
            """
            SELECT o.OrderID, o.OrderDate, o.ShipCountry,
                   c.CustomerID, c.CompanyName AS CustomerName,
                   (e.FirstName + ' ' + e.LastName) AS EmployeeName
            FROM Orders o
            JOIN Customers c ON c.CustomerID = o.CustomerID
            JOIN Employees e ON e.EmployeeID = o.EmployeeID
            WHERE o.OrderID = ?
            """,
            order_id,
        ).fetchone()
        if header is None:
            return None

        lines = cx.execute(
            """
            SELECT od.ProductID, p.ProductName,
                   od.UnitPrice, od.Quantity, od.Discount,
                   (od.UnitPrice * od.Quantity * (1 - od.Discount)) AS LineTotal
            FROM [Order Details] od
            JOIN Products p ON p.ProductID = od.ProductID
            WHERE od.OrderID = ?
            ORDER BY p.ProductName
            """,
            order_id,
        ).fetchall()

    order_lines = [
        OrderLine(
            product_id=l.ProductID,
            product_name=l.ProductName,
            unit_price=float(l.UnitPrice),
            quantity=int(l.Quantity),
            discount=float(l.Discount),
            line_total=float(l.LineTotal),
        )
        for l in lines
    ]

    return Order(
        order_id=header.OrderID,
        order_date=header.OrderDate,
        customer_id=header.CustomerID,
        customer_name=header.CustomerName,
        employee_name=header.EmployeeName,
        ship_country=header.ShipCountry,
        lines=order_lines,
        total=sum(l.line_total for l in order_lines),
    )


# ---------- Employee ----------

def fetch_employee(employee_id: int) -> Employee | None:
    with _cx() as cx:
        emp = cx.execute(
            """
            SELECT EmployeeID, FirstName, LastName, Title, HireDate, ReportsTo
            FROM Employees WHERE EmployeeID = ?
            """,
            employee_id,
        ).fetchone()
        if emp is None:
            return None

        manager = None
        if emp.ReportsTo is not None:
            m = cx.execute(
                """
                SELECT EmployeeID, FirstName, LastName
                FROM Employees WHERE EmployeeID = ?
                """,
                emp.ReportsTo,
            ).fetchone()
            if m is not None:
                manager = EmployeeSummary(
                    employee_id=m.EmployeeID,
                    name=f"{m.FirstName} {m.LastName}",
                )

        reports = cx.execute(
            """
            SELECT EmployeeID, FirstName, LastName
            FROM Employees WHERE ReportsTo = ?
            ORDER BY LastName
            """,
            employee_id,
        ).fetchall()

        # Northwind's most-recent order year is 1998. "YTD" is unhelpful against
        # historical data — use "the most recent year present" as the anchor.
        year_row = cx.execute(
            "SELECT MAX(YEAR(OrderDate)) AS y FROM Orders"
        ).fetchone()
        anchor_year = int(year_row.y) if year_row and year_row.y else 1998

        rev_row = cx.execute(
            """
            SELECT COALESCE(SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)), 0) AS rev
            FROM Orders o
            JOIN [Order Details] od ON od.OrderID = o.OrderID
            WHERE o.EmployeeID = ? AND YEAR(o.OrderDate) = ?
            """,
            employee_id,
            anchor_year,
        ).fetchone()

    return Employee(
        employee_id=emp.EmployeeID,
        name=f"{emp.FirstName} {emp.LastName}",
        title=emp.Title,
        hire_date=emp.HireDate,
        manager=manager,
        direct_reports=[
            EmployeeSummary(
                employee_id=r.EmployeeID,
                name=f"{r.FirstName} {r.LastName}",
            )
            for r in reports
        ],
        ytd_revenue=float(rev_row.rev if rev_row else 0),
    )


# ---------- Analytics ----------

def top_customers(limit: int = 10) -> list[dict]:
    """Top customers by lifetime revenue. Returns thin summaries."""
    limit = max(1, min(limit, 50))
    with _cx() as cx:
        rows = cx.execute(
            f"""
            SELECT TOP ({limit})
                   c.CustomerID, c.CompanyName, c.Country,
                   SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)) AS Revenue
            FROM Customers c
            JOIN Orders o ON o.CustomerID = c.CustomerID
            JOIN [Order Details] od ON od.OrderID = o.OrderID
            GROUP BY c.CustomerID, c.CompanyName, c.Country
            ORDER BY Revenue DESC
            """
        ).fetchall()

    return [
        {
            "customer_id": r.CustomerID,
            "company_name": r.CompanyName,
            "country": r.Country,
            "revenue": float(r.Revenue),
        }
        for r in rows
    ]
