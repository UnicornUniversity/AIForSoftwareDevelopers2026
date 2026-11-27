"""Parse-level read-only SQL validation with SQLGlot.

This is the first production safety layer for the query path. It is not the only boundary:
the database credential is read-only, and execution applies a timeout and row cap. A
rejection ends the attempt; the pipeline never tries another phrasing around a failed check.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_SQL_LENGTH = 20_000

_READ_ROOTS: tuple[type[exp.Expression], ...] = tuple(
    cls
    for cls in (
        getattr(exp, "Select", None),
        getattr(exp, "Union", None),
        getattr(exp, "Intersect", None),
        getattr(exp, "Except", None),
    )
    if isinstance(cls, type)
)

_DENIED_NODES: tuple[type[exp.Expression], ...] = tuple(
    cls
    for cls in (
        getattr(exp, "Insert", None),
        getattr(exp, "Update", None),
        getattr(exp, "Delete", None),
        getattr(exp, "Merge", None),
        getattr(exp, "Create", None),
        getattr(exp, "Drop", None),
        getattr(exp, "Alter", None),
        getattr(exp, "TruncateTable", None),
        getattr(exp, "Command", None),
        getattr(exp, "Execute", None),
        getattr(exp, "Grant", None),
        getattr(exp, "Revoke", None),
        getattr(exp, "Use", None),
        getattr(exp, "Into", None),
    )
    if isinstance(cls, type)
)

_DENIED_FUNCTIONS = frozenset(
    {
        "xp_cmdshell",
        "openrowset",
        "openquery",
        "opendatasource",
        "openxml",
        "sp_executesql",
    }
)


@dataclass(frozen=True)
class SqlValidationResult:
    """Outcome of parse-level validation."""

    valid: bool
    errors: tuple[str, ...]
    tables: tuple[str, ...] = ()


def _fail(errors: list[str]) -> SqlValidationResult:
    return SqlValidationResult(valid=False, errors=tuple(errors))


def _normalize_identifier(value: str | None) -> str:
    return (value or "").strip().lower()


def _table_references(root: exp.Expression) -> list[exp.Table]:
    """Return real table references, excluding CTE aliases."""

    cte_names = {
        _normalize_identifier(cte.alias_or_name)
        for cte in root.find_all(exp.CTE)
        if cte.alias_or_name
    }
    references: list[exp.Table] = []
    for table in root.find_all(exp.Table):
        schema = _normalize_identifier(table.db)
        name = _normalize_identifier(table.name)
        if not schema and name in cte_names:
            continue
        references.append(table)
    return references


def validate_read_query(
    sql: str,
    *,
    allowed_objects: AbstractSet[str],
    default_schema: str = "dbo",
    database: str | None = None,
    dialect: str = "tsql",
) -> SqlValidationResult:
    """Validate one candidate statement for safe read-only execution.

    ``allowed_objects`` contains lower-case ``schema.object`` names. Only CTE references and
    objects in that allowlist may appear in the statement.
    """

    candidate = sql.strip()
    if not candidate:
        return _fail(["The SQL statement is empty."])
    if len(candidate) > MAX_SQL_LENGTH:
        return _fail([f"The SQL statement exceeds {MAX_SQL_LENGTH} characters."])

    try:
        statements = sqlglot.parse(candidate, read=dialect)
    except sqlglot.errors.ParseError as exc:
        message = " ".join(str(exc).split())
        if len(message) > 200:
            message = message[:200] + "..."
        return _fail([f"The SQL statement does not parse as {dialect}: {message}"])

    parsed = [statement for statement in statements if statement is not None]
    if len(parsed) != 1:
        return _fail(
            [
                "Exactly one SQL statement may be executed; "
                f"received {len(parsed)} statements. Statement stacking is rejected."
            ]
        )

    root = parsed[0]
    if not isinstance(root, _READ_ROOTS):
        return _fail(
            [
                "Only a single read-only SELECT (or UNION/INTERSECT/EXCEPT of SELECTs) "
                f"is allowed; received {type(root).__name__}."
            ]
        )

    denied = sorted(
        {
            type(node).__name__
            for node in root.walk()
            if isinstance(node, _DENIED_NODES)
        }
    )
    if denied:
        return _fail(
            [
                "The statement contains a disallowed operation: "
                + ", ".join(denied)
                + ". Only read-only SELECT statements are allowed."
            ]
        )

    denied_functions = sorted(
        {
            node.name.lower()
            for node in root.find_all(exp.Anonymous)
            if node.name and node.name.lower() in _DENIED_FUNCTIONS
        }
    )
    if denied_functions:
        return _fail(
            [
                "The statement calls a disallowed function: "
                + ", ".join(denied_functions)
                + "."
            ]
        )

    schema_default = _normalize_identifier(default_schema)
    tables: list[str] = []
    errors: list[str] = []
    for table in _table_references(root):
        catalog = _normalize_identifier(table.catalog)
        schema = _normalize_identifier(table.db) or schema_default
        name = _normalize_identifier(table.name)
        if not name:
            continue
        if table.args.get("temporary"):
            errors.append("Temporary tables are not allowed.")
            continue
        if catalog and database and catalog != database.strip().lower():
            errors.append(
                f"Cross-database reference is not allowed: {table.sql(dialect=dialect)}."
            )
            continue
        reference = f"{schema}.{name}"
        tables.append(reference)
        if reference not in allowed_objects:
            errors.append(
                f"Object '{schema}.{name}' is not in the approved query scope."
            )

    if errors:
        return SqlValidationResult(valid=False, errors=tuple(errors), tables=tuple(tables))
    return SqlValidationResult(valid=True, errors=(), tables=tuple(tables))
