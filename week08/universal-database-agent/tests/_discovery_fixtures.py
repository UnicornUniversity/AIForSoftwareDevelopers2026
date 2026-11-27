"""Shared deterministic fixtures for Phase 3 discovery tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from uda.adapters.ddl import DdlExtraction, DdlObject
from uda.adapters.smo import SmoStatus
from uda.discovery.evidence import StructuralEvidence, load_ddl_repository
from uda.discovery.models import DiscoveryOutput
from uda.discovery.prompt import PromptBundle, build_discovery_prompt
from uda.discovery.proposals import ProposalRepositoryWriter
from uda.discovery.validation import build_proposals
from uda.metadata.identity import ensure_physical_ids
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
from uda.prompts import PromptRegistry
from uda.repository import DdlRepositoryWriter, GitState

FIXED_TIME = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config" / "prompts" / "registry.yaml"


def sample_metadata(
    issues: tuple[ExtractionIssue, ...] = (),
) -> DatabaseMetadata:
    schema_id = make_physical_id("sqlserver", "Northwind", "schema", "dbo")
    customers_id = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Customers"
    )
    orders_id = make_physical_id(
        "sqlserver", "Northwind", "dbo", "table", "Orders"
    )
    view_id = make_physical_id(
        "sqlserver", "Northwind", "dbo", "view", "CustomerOrders"
    )

    def column(
        object_id: str, name: str, ordinal: int, data_type: str, **extra: Any
    ) -> ColumnMetadata:
        return ColumnMetadata(
            physical_id=child_id(object_id, "column", name),
            name=name,
            ordinal=ordinal,
            data_type=data_type,
            normalized_type=extra.pop("normalized_type", "string"),
            nullable=extra.pop("nullable", False),
            default=extra.pop("default", None),
            is_identity=extra.pop("is_identity", False),
            is_computed=extra.pop("is_computed", False),
            computed_expression=extra.pop("computed_expression", None),
        )

    customers = TableMetadata(
        physical_id=customers_id,
        schema_name="dbo",
        name="Customers",
        object_type="table",
        description="Customer master data.",
        columns=(
            column(
                customers_id,
                "CustomerID",
                1,
                "INTEGER",
                normalized_type="integer",
                is_identity=True,
            ),
            column(customers_id, "CustomerName", 2, "NVARCHAR(100)"),
            column(customers_id, "Country", 3, "NVARCHAR(50)", nullable=True),
        ),
        primary_key=PrimaryKeyMetadata(
            name="PK_Customers", columns=("CustomerID",)
        ),
    )
    orders = TableMetadata(
        physical_id=orders_id,
        schema_name="dbo",
        name="Orders",
        object_type="table",
        description="Order headers.",
        columns=(
            column(
                orders_id,
                "OrderID",
                1,
                "INTEGER",
                normalized_type="integer",
                is_identity=True,
            ),
            column(
                orders_id,
                "CustomerID",
                2,
                "INTEGER",
                normalized_type="integer",
            ),
            column(
                orders_id,
                "OrderDate",
                3,
                "DATETIME",
                normalized_type="datetime",
            ),
            column(
                orders_id,
                "Freight",
                4,
                "DECIMAL(10,2)",
                normalized_type="decimal",
                nullable=True,
            ),
        ),
        primary_key=PrimaryKeyMetadata(name="PK_Orders", columns=("OrderID",)),
        foreign_keys=(
            ForeignKeyMetadata(
                name="FK_Orders_Customers",
                columns=("CustomerID",),
                referred_schema="dbo",
                referred_table="Customers",
                referred_columns=("CustomerID",),
            ),
        ),
        indexes=(
            IndexMetadata(
                name="IX_Orders_CustomerID", columns=("CustomerID",)
            ),
        ),
    )
    view = TableMetadata(
        physical_id=view_id,
        schema_name="dbo",
        name="CustomerOrders",
        object_type="view",
        description="Customer and order projection.",
        columns=(
            column(
                view_id,
                "CustomerID",
                1,
                "INTEGER",
                normalized_type="integer",
            ),
            column(view_id, "CustomerName", 2, "NVARCHAR(100)"),
            column(
                view_id,
                "OrderID",
                3,
                "INTEGER",
                normalized_type="integer",
            ),
            column(
                view_id,
                "OrderDate",
                4,
                "DATETIME",
                normalized_type="datetime",
            ),
        ),
    )
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        schemas=(SchemaMetadata(physical_id=schema_id, name="dbo"),),
        objects=(customers, orders, view),
        issues=issues,
    )
    return ensure_physical_ids(metadata)


def _find(metadata: DatabaseMetadata, name: str) -> TableMetadata:
    for table in metadata.objects:
        if table.name == name:
            return table
    raise AssertionError(f"missing fixture object {name}")


def sample_ddl(metadata: DatabaseMetadata) -> DdlExtraction:
    objects: list[DdlObject] = []
    for table in metadata.objects:
        if table.object_type == "table":
            objects.append(
                DdlObject(
                    physical_id=table.physical_id,
                    kind="table",
                    status="extracted",
                    ddl=(
                        f"CREATE TABLE [dbo].[{table.name}] (\n"
                        f"    [Id] INT NOT NULL\n);\n"
                    ),
                    provenance="smo_scripter",
                    is_original_text=False,
                )
            )
        else:
            objects.append(
                DdlObject(
                    physical_id=table.physical_id,
                    kind="view",
                    status="extracted",
                    ddl=(
                        f"CREATE VIEW [dbo].[{table.name}] AS\n"
                        "SELECT 1 AS [Value];\n"
                    ),
                    provenance="server_module_definition",
                    is_original_text=True,
                )
            )
    return DdlExtraction(
        status="complete",
        mechanism="smo",
        version="17.0.0.0",
        detail="Deterministic test extraction.",
        objects=tuple(objects),
    )


def write_repository(
    root: Path,
    *,
    ddl: bool = True,
    issues: tuple[ExtractionIssue, ...] = (),
) -> Any:
    metadata = sample_metadata(issues=issues)
    return DdlRepositoryWriter(
        root,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-ddl-test",
        git_provider=lambda: GitState(True, "a" * 40),
        smo_provider=lambda: SmoStatus(
            available=True,
            version="17.0.0.0",
            mechanism="gac",
            detail="SMO test double.",
        ),
    ).write(
        metadata,
        source="fixture",
        ddl=sample_ddl(metadata) if ddl else None,
    )


def write_empty_repository(root: Path) -> Any:
    schema_id = make_physical_id("sqlserver", "Northwind", "schema", "dbo")
    metadata = DatabaseMetadata(
        identity=DatabaseIdentity(platform="sqlserver", database="Northwind"),
        schemas=(SchemaMetadata(physical_id=schema_id, name="dbo"),),
        objects=(),
    )
    return DdlRepositoryWriter(
        root,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-empty-test",
        git_provider=lambda: GitState(True, "a" * 40),
        smo_provider=lambda: SmoStatus(available=False, detail="No SMO."),
    ).write(metadata, source="fixture", ddl=None)


def reference(
    physical_id: str,
    kind: str,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "physical_id": physical_id,
        "kind": kind,
        "detail": detail,
    }
    payload.update(extra)
    return payload


def valid_payload() -> dict[str, Any]:
    metadata = sample_metadata()
    customers = _find(metadata, "Customers")
    orders = _find(metadata, "Orders")
    view = _find(metadata, "CustomerOrders")
    customer_id = child_id(customers.physical_id, "column", "CustomerID")
    customer_name = child_id(customers.physical_id, "column", "CustomerName")
    country = child_id(customers.physical_id, "column", "Country")
    orders_customer_id = child_id(orders.physical_id, "column", "CustomerID")
    foreign_key = orders.foreign_keys[0]
    assert foreign_key.physical_id is not None

    object_ref = reference(
        customers.physical_id,
        "object",
        "Table dbo.Customers stores customer master data.",
    )
    order_ref = reference(
        orders.physical_id,
        "object",
        "Table dbo.Orders stores order headers.",
    )
    customer_column_ref = reference(
        customer_id,
        "column",
        "Column Customers.CustomerID is the primary key.",
    )
    customer_name_ref = reference(
        customer_name,
        "column",
        "Column Customers.CustomerName stores the display name.",
    )
    country_ref = reference(
        country,
        "column",
        "Column Customers.Country stores the customer's country.",
    )
    orders_customer_ref = reference(
        orders_customer_id,
        "column",
        "Column Orders.CustomerID references the customer.",
    )
    foreign_key_ref = reference(
        foreign_key.physical_id,
        "foreign_key",
        "Foreign key Orders.CustomerID references Customers.CustomerID.",
    )
    customers_ddl_ref = reference(
        customers.physical_id,
        "ddl",
        "SMO-generated table definition for Customers.",
        ddl_provenance="smo_scripter",
        is_original_text=False,
    )
    view_ref = reference(
        view.physical_id,
        "object",
        "View dbo.CustomerOrders projects customer and order data.",
    )
    view_ddl_ref = reference(
        view.physical_id,
        "ddl",
        "Stored server module definition for the CustomerOrders view.",
        ddl_provenance="server_module_definition",
        is_original_text=True,
    )

    return {
        "concepts": [
            {
                "ref": "customer",
                "name": "Customer",
                "definition": "A party that purchases products from the business.",
                "domain": "Sales",
                "attributes": [
                    {
                        "name": "Customer name",
                        "definition": "The customer's display name.",
                        "source_references": [customer_name_ref],
                        "rationale": (
                            "The CustomerName column provides the display name for "
                            "a customer."
                        ),
                        "confidence": "medium",
                    }
                ],
                "source_references": [
                    object_ref,
                    customer_column_ref,
                    customers_ddl_ref,
                ],
                "rationale": (
                    "The Customers table and its CustomerID primary key identify a "
                    "party that places orders."
                ),
                "confidence": "high",
            },
            {
                "ref": "order",
                "name": "Order",
                "definition": "A request by a customer to purchase products.",
                "source_references": [
                    order_ref,
                    foreign_key_ref,
                    view_ddl_ref,
                ],
                "rationale": (
                    "The Orders table and its foreign key to Customers record "
                    "purchase requests made by a customer."
                ),
                "confidence": "high",
            },
            {
                "ref": "location",
                "name": "Customer Location",
                "definition": "The country associated with a customer.",
                "source_references": [country_ref],
                "rationale": (
                    "The Country column on Customers records where the customer is "
                    "located."
                ),
                "confidence": "low",
            },
        ],
        "mappings": [
            {
                "level": "object",
                "source_physical_id": customers.physical_id,
                "concept_ref": "customer",
                "source_references": [object_ref],
                "rationale": (
                    "The Customers table stores one row per customer, so it maps to "
                    "the Customer concept."
                ),
                "confidence": "high",
            },
            {
                "level": "column",
                "source_physical_id": customer_id,
                "concept_ref": "customer",
                "source_references": [customer_column_ref],
                "rationale": (
                    "The CustomerID primary key identifies each Customer concept "
                    "instance."
                ),
                "confidence": "high",
            },
            {
                "level": "column",
                "source_physical_id": country,
                "concept_ref": "customer",
                "source_references": [country_ref],
                "rationale": (
                    "The Country column is a descriptive attribute of a customer."
                ),
                "confidence": "medium",
            },
            {
                "level": "column",
                "source_physical_id": country,
                "concept_ref": "location",
                "source_references": [country_ref],
                "rationale": (
                    "The Country column also carries the reusable Customer Location "
                    "concept."
                ),
                "confidence": "low",
            },
            {
                "level": "object",
                "source_physical_id": orders.physical_id,
                "concept_ref": "order",
                "source_references": [order_ref],
                "rationale": (
                    "The Orders table stores order headers, so it maps to the Order "
                    "concept."
                ),
                "confidence": "high",
            },
            {
                "level": "column",
                "source_physical_id": orders_customer_id,
                "concept_ref": "customer",
                "source_references": [orders_customer_ref],
                "rationale": (
                    "The Orders.CustomerID column refers to a customer, so it maps "
                    "to the Customer concept."
                ),
                "confidence": "medium",
            },
            {
                "level": "object",
                "source_physical_id": view.physical_id,
                "concept_ref": "order",
                "source_references": [view_ref, view_ddl_ref],
                "rationale": (
                    "The CustomerOrders view exposes order rows joined with customer "
                    "data, so it also supports the Order concept."
                ),
                "confidence": "medium",
            },
        ],
        "relationships": [
            {
                "relationship_type": "places",
                "source_concept_ref": "customer",
                "target_concept_ref": "order",
                "source_references": [foreign_key_ref],
                "rationale": (
                    "The Orders.CustomerID foreign key indicates that a customer "
                    "places orders."
                ),
                "confidence": "high",
            }
        ],
    }


def valid_output() -> DiscoveryOutput:
    return DiscoveryOutput.model_validate(valid_payload())


def valid_json() -> str:
    return json.dumps(valid_payload(), indent=2)


def real_registry() -> PromptRegistry:
    return PromptRegistry.load(REGISTRY_PATH)


def load_evidence(root: Path) -> StructuralEvidence:
    return load_ddl_repository(root)


def prompt_bundle(evidence: StructuralEvidence, **kwargs: Any) -> PromptBundle:
    return build_discovery_prompt(evidence, real_registry(), **kwargs)


def proposal_writer(root: Path) -> ProposalRepositoryWriter:
    return ProposalRepositoryWriter(
        root,
        project_root=PROJECT_ROOT,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-proposal-test",
    )


def write_valid_proposals(root: Path, evidence: StructuralEvidence) -> Any:
    return proposal_writer(root).write(
        build_proposals(valid_output(), evidence),
        ddl_repository=str(evidence.root),
        snapshot_id=evidence.snapshot_id,
        prompt_version="2",
        prompt_sha256="a" * 64,
        provider="fake",
        model="fixture",
        temperature=0.0,
        max_tokens=1024,
    )


class StaticLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        self.calls += 1
        return self.response


class FailingLLM:
    @property
    def provider_name(self) -> str:
        return "failing"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        raise RuntimeError("provider unavailable")


class TimeoutLLM:
    @property
    def provider_name(self) -> str:
        return "timeout"

    def invoke(self, messages: Sequence[BaseMessage]) -> str:
        raise TimeoutError("provider timed out")


class NonTextLLM:
    @property
    def provider_name(self) -> str:
        return "non-text"

    def invoke(self, messages: Sequence[BaseMessage]) -> Any:
        return {"not": "text"}
