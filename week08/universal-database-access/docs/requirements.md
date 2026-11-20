# UDA Vertical Slice - Requirements

- **Status:** Approved design baseline (Stage 1)
- **Date:** 2026-11-20
- **Scope:** one selected table, one LLM proposal, physical validation, one saved
  `pending_review` candidate

## 1. Purpose

This slice proves one complete path of Universal Database Access (UDA):

1. a data engineer selects one table (initially `Products`);
2. an LLM proposes one domain concept and attributes mapped to physical columns;
3. every physical reference is validated;
4. the result is saved as an unapproved candidate.

The slice is deliberately narrow. It does not approve, publish, edit, or reconcile
candidates. It exists to make the trust boundaries between schema metadata, model
output, validation, and persistence explicit and testable.

## 2. User story

> As a data engineer, I select one table, ask an LLM to propose a domain concept
> and its attributes mapped to that table's columns, have every physical reference
> validated, and save the proposal as an unapproved candidate for later review.

## 3. Goals and non-goals

### Goals

- One-table vertical slice with a local fixture as the default schema source.
- Deterministic, provider-independent schema versioning.
- Structured LLM output that is never trusted before validation.
- Explicit rejection of unknown tables, unknown columns, and ambiguous mappings.
- A reviewable candidate file with identity, provenance, and `pending_review` status.
- Fully offline tests using fakes and temporary directories.

### Non-goals

- Approval, publication, or status transitions.
- Editing or merging candidates after they are written.
- Multi-table concepts, joins, or cross-table mappings.
- Vector search, embeddings, ontology reasoning, or a web UI.
- Arbitrary SQL generation or execution.
- Authentication, authorization, or production deployment.

## 4. Functional requirements

| ID | Requirement |
|---|---|
| **FR-1** | The CLI accepts a table name. The initial example table is `Products`; the default schema source is a local JSON fixture. |
| **FR-2** | A schema contains the schema-qualified table name, columns, SQL type per column, nullability per column, and a primary-key flag when known. |
| **FR-3** | The selected table receives a deterministic schema version derived from its canonical metadata. |
| **FR-4** | The LLM returns structured output: exactly one concept, a description, and at least one attribute. Each attribute references one or more physical columns. |
| **FR-5** | Every proposed table and column reference is validated against the selected schema. Unknown references are rejected. |
| **FR-6** | A valid proposal is saved with a candidate ID, UTC timestamp, source table, schema version, `pending_review` status, and the concept. |
| **FR-7** | Candidate files are written once, atomically, and never overwritten. A failed run writes no candidate. |
| **FR-8** | No approval or publication exists. `pending_review` is the only constructible and persistable status. |
| **FR-9** | The CLI reports success, validation rejection, and configuration/model/storage errors with distinct exit codes. |
| **FR-10** | The test suite runs offline with no API key, database, network, or Langfuse. |

## 5. Data contracts

### 5.1 Table schema

| Field | Required | Description |
|---|---|---|
| `schema_name` | yes | Database schema, for example `dbo`. |
| `table_name` | yes | Physical table name, for example `Products`. |
| `columns` | yes | Ordered, non-empty list of column definitions; names are unique. |

### 5.2 Column

| Field | Required | Description |
|---|---|---|
| `name` | yes | Exact physical column name, for example `ProductID`. |
| `sql_type` | yes | SQL type as reported by the source, for example `int`, `nvarchar(40)`, `money`. |
| `nullable` | yes | `true` or `false`. |
| `is_primary_key` | yes | `true`, `false`, or `null` when primary-key metadata is unavailable. |

The fixture must provide `true` or `false`. The optional SQL Server provider uses
catalog metadata and sets `null` only when primary-key information cannot be read.

### 5.3 Concept proposal

| Field | Required | Description |
|---|---|---|
| `concept_name` | yes | One domain concept for the table, for example `Product`. |
| `description` | yes | Short natural-language description of the concept. |
| `attributes` | yes | Non-empty list of attribute mappings. |

### 5.4 Attribute mapping

| Field | Required | Description |
|---|---|---|
| `attribute` | yes | Semantic attribute name, unique within the concept (case-insensitive). |
| `column_names` | yes | One or more physical column names; each must resolve to a column of the selected table. |

A mapping may cover a composite attribute, for example
`{"attribute": "shipping address", "column_names": ["Address", "City", "Region", "PostalCode", "Country"]}`.
The vertical slice does not allow the same physical column to be reused by two
different attributes.

### 5.5 Candidate

| Field | Required | Description |
|---|---|---|
| `candidate_id` | yes | UUIDv4 string, unique per saved candidate. |
| `created_at` | yes | UTC timestamp in RFC 3339 form. |
| `source_table` | yes | Schema-qualified table, for example `dbo.Products`. |
| `schema_version` | yes | `sha256:<64 lowercase hex characters>` fingerprint of the schema used. |
| `status` | yes | Literal `pending_review`. No other value is valid. |
| `concept` | yes | The validated concept proposal. |

Example shape:

```json
{
  "candidate_id": "6f1c2c1e-6c2f-4d6b-9f0e-1c2a3b4c5d6e",
  "created_at": "2026-11-20T10:15:30Z",
  "source_table": "dbo.Products",
  "schema_version": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "status": "pending_review",
  "concept": {
    "concept_name": "Product",
    "description": "An item offered for sale.",
    "attributes": [
      {"attribute": "identifier", "column_names": ["ProductID"]},
      {"attribute": "name", "column_names": ["ProductName"]},
      {"attribute": "price", "column_names": ["UnitPrice"]}
    ]
  }
}
```

## 6. Schema version

The schema version is a SHA-256 fingerprint of the canonical selected table:

- schema name, table name, and every column;
- column name, SQL type, nullability, and primary-key flag;
- columns sorted by name for provider-independent determinism;
- canonical JSON with sorted object keys, UTF-8 encoding;
- prefixed with `sha256:`.

The fingerprint changes when any physical detail changes. It is not a hand-maintained
label. It is computed at schema-load time and copied into the candidate.

## 7. Validation rules

| ID | Rule | Outcome |
|---|---|---|
| **V-1** | The requested table must exist in the selected schema source. | Unknown table: reject before any LLM call. |
| **V-2** | Table and column lookup is case-insensitive, matching SQL Server's default collation. | Accepted names are canonicalized to the schema's exact spelling. |
| **V-3** | Every name in every `column_names` list must resolve to a column of the selected table. | Unknown column: reject. |
| **V-4** | An attribute must reference at least one column; no duplicate names inside one mapping. | Malformed mapping: reject. |
| **V-5** | Two different attributes must not reuse the same physical column in this slice. | Duplicate physical usage: reject. |
| **V-6** | Attribute names must be unique within the concept, case-insensitively. | Duplicate attribute: reject. |
| **V-7** | The concept has exactly one name, one description, and at least one attribute; extra model fields are forbidden. | Malformed proposal: reject. |
| **V-8** | Only `pending_review` is constructible and persistable; storage revalidates before writing. | Any other status is impossible. |
| **V-9** | No rule may be bypassed by retrying or by direct persistence. | Every candidate passes the same validator. |

If any rule fails, no candidate file is written.

## 8. CLI contract

```text
uda propose --table <name> [options]

Options:
  --table <name>        Required. Table to describe.
  --source <source>     fixture (default) or sqlserver.
  --fixture <path>      Fixture file; defaults to the bundled fixture.
  --out-dir <path>      Candidate directory; defaults to candidates/.
  --response-file <p>   Offline mode: replay a local structured model response.
  --help                Show usage.
```

For `--source sqlserver`, `--table` may be `table` or `schema.table`; the default
schema is `dbo`. Missing connection settings are a configuration error, not a crash.

| Exit code | Meaning | Candidate file |
|---|---|---|
| `0` | Valid candidate saved. | Written once. |
| `1` | Proposal rejected by physical validation. | None. |
| `2` | Unknown table, missing/invalid configuration, model failure, or storage failure. | None. |

On success the CLI prints the candidate ID and file path. On rejection it prints
each issue code and message. Errors go to standard error. No credentials are printed.

## 9. Configuration requirements

- Default schema source: bundled local JSON fixture.
- The fixture may be overridden by a CLI flag or environment variable.
- SQL Server settings are optional and environment-based; the provider is read-only.
- The LLM provider is optional for offline runs; tests inject a fake proposal generator.
- Secrets are read from the environment, never from source, fixtures, prompts, or logs.
- Candidate output is runtime data and must not be committed.

Full precedence and variable names are in `docs/architecture.md`.

## 10. Offline test requirements

The default test suite must pass with:

- no API key;
- no database server or driver;
- no network access;
- no Langfuse or other tracing service;
- no real model call.

Tests use the bundled fixture, temporary output directories, a fake proposal
generator, and fake catalog inspectors. The optional SQL Server provider is tested
through its pure mapping functions without opening a connection.

## 11. Non-functional requirements and constraints

- Python 3.12, managed with `uv`.
- LangChain for model interaction and structured output.
- LangGraph for workflow orchestration and state.
- Pydantic for all contracts and validation.
- SQLAlchemy only inside the optional SQL Server metadata provider.
- Read-only metadata access; no generated or executed arbitrary SQL.
- Deterministic schema version; UUIDv4 candidate ID; UTC timestamps.
- Small, CLI-first, single-process, no background services.
- No credentials in source, fixtures, logs, prompts, or committed `.env`.
- Candidate output is exclusive and write-once; no partial files.

## 12. Out of scope

- Approval, publication, review UI, or status changes.
- Candidate updates, merges, or deletion commands.
- Multi-table concepts, joins, foreign-key reasoning, or lineage.
- Embeddings, vector databases, ontology reasoners, or semantic search.
- Arbitrary SQL or write access to the source database.
- Authentication and authorization.
- Production deployment, concurrency control across processes, and retention policy.

## 13. Acceptance criteria

- [ ] `uda propose --table Products` against the fixture produces a valid candidate
      with `candidate_id`, `created_at`, `source_table`, `schema_version`,
      `pending_review`, and the concept.
- [ ] The candidate's columns use the schema's exact spelling.
- [ ] An unknown table exits `2` and makes no model call.
- [ ] An unknown column or duplicate mapping exits `1` and writes no file.
- [ ] A malformed or failed model response exits `2` and writes no file.
- [ ] No code path can create a candidate with a status other than `pending_review`.
- [ ] Storage refuses to overwrite an existing candidate file.
- [ ] `uv run pytest` passes with no key, database, network, or Langfuse.
- [ ] `uv run ruff check .` passes.

## 14. Glossary

| Term | Meaning |
|---|---|
| **Candidate** | A saved, unapproved concept proposal with provenance and status. |
| **Concept** | One domain idea inferred for a table, with named attributes. |
| **Physical reference** | A table or column name that exists in the selected schema. |
| **Schema version** | Deterministic fingerprint of the table metadata used for a proposal. |
| **Proposal** | Untrusted structured output from the LLM before physical validation. |
| **Vertical slice** | The smallest end-to-end path through selection, proposal, validation, and storage. |
