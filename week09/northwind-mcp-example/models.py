"""Pydantic models for Northwind entity aggregates.

These models define the *shape* that MCP tools return. The whole point of the
entity-MCP pattern is that the LLM sees these nouns — Customer, Order,
Employee — instead of the raw Customers/Orders/[Order Details] tables.
"""

from datetime import datetime
from pydantic import BaseModel


class OrderLine(BaseModel):
    product_id: int
    product_name: str
    unit_price: float
    quantity: int
    discount: float
    line_total: float


class OrderSummary(BaseModel):
    order_id: int
    order_date: datetime
    ship_country: str | None
    total: float


class Order(BaseModel):
    order_id: int
    order_date: datetime
    customer_id: str
    customer_name: str
    employee_name: str
    ship_country: str | None
    lines: list[OrderLine]
    total: float


class Customer(BaseModel):
    customer_id: str
    company_name: str
    contact_name: str | None
    country: str | None
    phone: str | None
    orders: list[OrderSummary]
    lifetime_value: float


class EmployeeSummary(BaseModel):
    employee_id: int
    name: str


class Employee(BaseModel):
    employee_id: int
    name: str
    title: str | None
    hire_date: datetime | None
    manager: EmployeeSummary | None
    direct_reports: list[EmployeeSummary]
    ytd_revenue: float


class CustomerSearchResult(BaseModel):
    customer_id: str
    company_name: str
    country: str | None
