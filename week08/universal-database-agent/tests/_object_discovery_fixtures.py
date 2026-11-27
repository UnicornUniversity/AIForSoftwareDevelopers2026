"""Deterministic fixtures for object-level discovery tests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from _discovery_fixtures import sample_metadata
from langchain_core.messages import BaseMessage

from uda.metadata.models import TableMetadata, child_id


def _table(name: str) -> TableMetadata:
    for table in sample_metadata().objects:
        if table.name == name:
            return table
    raise AssertionError(f"missing fixture table {name}")


def reference(physical_id: str, kind: str, detail: str) -> dict[str, Any]:
    return {"physical_id": physical_id, "kind": kind, "detail": detail}


def object_payload(table_name: str = "Customers") -> dict[str, Any]:
    """Return a valid object-level response for a fixture table."""

    table = _table(table_name)
    if table_name == "Customers":
        customer_id = child_id(table.physical_id, "column", "CustomerID")
        customer_name = child_id(table.physical_id, "column", "CustomerName")
        country = child_id(table.physical_id, "column", "Country")
        object_ref = reference(
            table.physical_id,
            "object",
            "Table dbo.Customers stores one row per customer.",
        )
        customer_id_ref = reference(
            customer_id,
            "column",
            "CustomerID is the identity primary key.",
        )
        name_ref = reference(
            customer_name,
            "column",
            "CustomerName stores the customer's display name.",
        )
        country_ref = reference(
            country,
            "column",
            "Country stores the customer's country.",
        )
        return {
            "object_physical_id": table.physical_id,
            "object_kind": "table",
            "object_role": "entity",
            "concepts": [
                {
                    "ref": "c1",
                    "name": "Customer",
                    "definition": "A party that purchases products.",
                    "domain": "Sales",
                    "attributes": [
                        {
                            "name": "Customer name",
                            "definition": "The customer's display name.",
                            "source_references": [name_ref],
                            "rationale": (
                                "CustomerName supplies a human-readable label for "
                                "each customer."
                            ),
                            "confidence": "high",
                        },
                        {
                            "name": "Country",
                            "definition": "The country where the customer is located.",
                            "source_references": [country_ref],
                            "rationale": (
                                "The Country column records the customer's location."
                            ),
                            "confidence": "medium",
                        },
                    ],
                    "source_references": [object_ref, customer_id_ref],
                    "rationale": (
                        "The Customers table has one row per party and an identity "
                        "primary key, which identifies a customer entity."
                    ),
                    "confidence": "high",
                }
            ],
            "mappings": [
                {
                    "level": "object",
                    "source_physical_id": table.physical_id,
                    "concept_ref": "c1",
                    "attribute_name": None,
                    "source_references": [object_ref],
                    "rationale": (
                        "The Customers table is the physical realization of the "
                        "Customer concept."
                    ),
                    "confidence": "high",
                },
                {
                    "level": "column",
                    "source_physical_id": customer_name,
                    "concept_ref": "c1",
                    "attribute_name": "Customer name",
                    "source_references": [name_ref],
                    "rationale": (
                        "CustomerName is the physical column behind the Customer "
                        "name attribute."
                    ),
                    "confidence": "high",
                },
                {
                    "level": "column",
                    "source_physical_id": country,
                    "concept_ref": "c1",
                    "attribute_name": "Country",
                    "source_references": [country_ref],
                    "rationale": (
                        "Country is the physical column behind the Country attribute."
                    ),
                    "confidence": "medium",
                },
            ],
        }
    if table_name == "Orders":
        order_id = child_id(table.physical_id, "column", "OrderID")
        order_date = child_id(table.physical_id, "column", "OrderDate")
        freight = child_id(table.physical_id, "column", "Freight")
        object_ref = reference(
            table.physical_id,
            "object",
            "Table dbo.Orders stores order headers.",
        )
        order_id_ref = reference(
            order_id, "column", "OrderID is the identity primary key."
        )
        date_ref = reference(
            order_date, "column", "OrderDate stores when the order was placed."
        )
        freight_ref = reference(
            freight, "column", "Freight stores the order's shipping charge."
        )
        return {
            "object_physical_id": table.physical_id,
            "object_kind": "table",
            "object_role": "entity",
            "concepts": [
                {
                    "ref": "c1",
                    "name": "Order",
                    "definition": "A request by a customer to purchase products.",
                    "domain": "Sales",
                    "attributes": [
                        {
                            "name": "Order date",
                            "definition": "The date the order was placed.",
                            "source_references": [date_ref],
                            "rationale": (
                                "OrderDate records when the purchase request was made."
                            ),
                            "confidence": "high",
                        },
                        {
                            "name": "Freight",
                            "definition": "The shipping charge for the order.",
                            "source_references": [freight_ref],
                            "rationale": (
                                "Freight is a monetary charge attached to the order."
                            ),
                            "confidence": "medium",
                        },
                    ],
                    "source_references": [object_ref, order_id_ref],
                    "rationale": (
                        "The Orders table has one row per purchasing event and an "
                        "identity key, which identifies an order."
                    ),
                    "confidence": "high",
                }
            ],
            "mappings": [
                {
                    "level": "object",
                    "source_physical_id": table.physical_id,
                    "concept_ref": "c1",
                    "attribute_name": None,
                    "source_references": [object_ref],
                    "rationale": (
                        "The Orders table is the physical realization of the Order "
                        "concept."
                    ),
                    "confidence": "high",
                },
                {
                    "level": "column",
                    "source_physical_id": order_date,
                    "concept_ref": "c1",
                    "attribute_name": "Order date",
                    "source_references": [date_ref],
                    "rationale": (
                        "OrderDate is the physical column behind the Order date "
                        "attribute."
                    ),
                    "confidence": "high",
                },
                {
                    "level": "column",
                    "source_physical_id": freight,
                    "concept_ref": "c1",
                    "attribute_name": "Freight",
                    "source_references": [freight_ref],
                    "rationale": (
                        "Freight is the physical column behind the Freight attribute."
                    ),
                    "confidence": "medium",
                },
            ],
        }
    raise AssertionError(f"no object fixture for {table_name}")


def object_json(table_name: str = "Customers") -> str:
    return json.dumps(object_payload(table_name), indent=2)


def responses_by_table() -> dict[str, str]:
    """Return one valid response keyed by table Physical ID."""

    return {
        _table("Customers").physical_id: object_json("Customers"),
        _table("Orders").physical_id: object_json("Orders"),
    }


class RoutingObjectLLM:
    """Return the response matching the object Physical ID in the prompt."""

    def __init__(self, responses: Mapping[str, str]) -> None:
        self.responses = dict(responses)
        self.calls = 0
        self.prompts: list[str] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        self.calls += 1
        human = str(messages[-1].content)
        self.prompts.append(human)
        marker = "OBJECT EVIDENCE (JSON):\n"
        if marker not in human:
            raise AssertionError("prompt does not contain object evidence")
        payload = json.loads(human.split(marker, 1)[1])
        physical_id = payload["object"]["physical_id"]
        if physical_id not in self.responses:
            raise AssertionError(f"no response configured for {physical_id}")
        return self.responses[physical_id]
