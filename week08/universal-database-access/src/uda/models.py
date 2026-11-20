"""Pydantic domain contract for the Universal Database Access demo.

The physical side describes exactly one relational table. The semantic side is a
proposal: it has not been reviewed or published, and no code here contacts a
database or a language model.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

SchemaVersionStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sha256:[0-9a-f]{64}$",
    ),
]

CandidateStatus = Literal["pending_review"]


class Column(BaseModel):
    """One physical column as reported by the database catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonEmptyStr
    sql_type: NonEmptyStr = Field(
        validation_alias=AliasChoices("sql_type", "data_type")
    )
    nullable: bool = True
    is_primary_key: bool | None = None

    @property
    def data_type(self) -> str:
        """Legacy accessor; the canonical field is ``sql_type``."""
        return self.sql_type


class TableSchema(BaseModel):
    """One relational table. Column names must be unique within the table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_name: NonEmptyStr = "dbo"
    table_name: NonEmptyStr
    columns: tuple[Column, ...]

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, columns: tuple[Column, ...]) -> tuple[Column, ...]:
        if not columns:
            raise ValueError("table must have at least one column")

        seen: set[str] = set()
        duplicates: set[str] = set()
        for column in columns:
            if column.name in seen:
                duplicates.add(column.name)
            seen.add(column.name)

        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate column names: {joined}")
        return columns

    @property
    def qualified_name(self) -> str:
        """Return the schema-qualified table name, for example ``dbo.Customer``."""
        return f"{self.schema_name}.{self.table_name}"

    def column_names(self) -> set[str]:
        """Return the set of physical column names this table exposes."""
        return {column.name for column in self.columns}


class AttributeMapping(BaseModel):
    """One semantic attribute mapped to one or more physical columns.

    Column names must be unique within the mapping, compared case-insensitively.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: NonEmptyStr
    column_names: tuple[NonEmptyStr, ...] = Field(
        validation_alias=AliasChoices("column_names", "column")
    )

    @field_validator("column_names", mode="before")
    @classmethod
    def _normalize_column_names(cls, value: object) -> object:
        if isinstance(value, str):
            return (value,)
        return value

    @field_validator("column_names")
    @classmethod
    def _validate_column_names(
        cls, names: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not names:
            raise ValueError("attribute must map at least one column")

        seen: set[str] = set()
        duplicates: set[str] = set()
        for name in names:
            key = name.casefold()
            if key in seen:
                duplicates.add(key)
            seen.add(key)

        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate column names: {joined}")
        return names

    @property
    def column(self) -> str:
        """Legacy accessor; only valid for a single-column mapping."""
        if len(self.column_names) != 1:
            raise ValueError("legacy column accessor requires exactly one column")
        return self.column_names[0]


class ConceptProposal(BaseModel):
    """The single concept an LLM proposes for a table.

    Attribute names must be unique when compared case-insensitively.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    concept_name: NonEmptyStr
    description: NonEmptyStr
    attributes: tuple[AttributeMapping, ...]

    @field_validator("attributes")
    @classmethod
    def _validate_attributes(
        cls, attributes: tuple[AttributeMapping, ...]
    ) -> tuple[AttributeMapping, ...]:
        if not attributes:
            raise ValueError("concept must map at least one attribute")

        seen: set[str] = set()
        duplicates: set[str] = set()
        for mapping in attributes:
            key = mapping.attribute.casefold()
            if key in seen:
                duplicates.add(key)
            seen.add(key)

        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate attribute names: {joined}")
        return attributes


class Candidate(BaseModel):
    """A reviewable, never auto-approved semantic candidate for one table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    source_table: NonEmptyStr = Field(
        validation_alias=AliasChoices("source_table", "physical_table")
    )
    schema_version: SchemaVersionStr
    status: CandidateStatus = "pending_review"
    concept: ConceptProposal

    @field_validator("candidate_id")
    @classmethod
    def _validate_candidate_id(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("candidate_id must be a UUIDv4")
        return value

    @field_validator("created_at")
    @classmethod
    def _normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def physical_table(self) -> str:
        """Legacy accessor; the canonical field is ``source_table``."""
        return self.source_table
