# UDA Vertical Slice - Architecture Decisions

- **Status:** Accepted for the vertical slice
- **Date:** 2026-11-20
- **Companion documents:** [requirements.md](requirements.md), [architecture.md](architecture.md)

Each decision records the context, the choice, its consequences, and the
alternatives that were considered.

---

## ADR-001: Fixture-first schema source with optional SQL Server

**Status:** Accepted

**Context**
The slice must run in a classroom and in offline tests, but must also demonstrate
optional real SQL Server metadata access. Requiring a database would make the default
path and the test suite fragile.

**Decision**
The default schema source is a bundled local JSON fixture containing at least
`Products` and `Categories`. SQL Server access is an optional provider behind the same
`SchemaProvider` contract, using SQLAlchemy catalog inspection only. Both providers
produce the same `TableSchema` shape.

**Consequences**
- The default demo and all default tests need no database or driver.
- Fixture and SQL Server paths share validation, versioning, and persistence.
- The fixture must stay representative of real catalog metadata, including SQL types,
  nullability, and primary-key flags.
- SQL Server-specific correctness is covered by pure mapping tests with fake
  inspectors, plus optional manual checks.

**Alternatives considered**
- Require a database for every run: rejected because it breaks offline testing.
- Use SQLite as the default: rejected because the product is SQL Server-oriented and
  SQLite metadata does not exercise the same types or catalog behavior.
- One fixture file per table: rejected because a multi-table fixture makes unknown-table
  selection and rejection testable without file-system tricks.

---

## ADR-002: Candidate identity, provenance, and immutability

**Status:** Accepted

**Context**
A candidate must be reviewable later. Without identity and provenance, files cannot be
distinguished or traced to the exact schema that produced them. The product forbids
approval and publication.

**Decision**
Every candidate contains:

- `candidate_id`: UUIDv4 string;
- `created_at`: UTC timestamp in RFC 3339 form;
- `source_table`: schema-qualified table name;
- `schema_version`: deterministic schema fingerprint;
- `status`: the literal `pending_review`;
- the validated concept.

The model is frozen and extra fields are forbidden. The finalizer accepts an optional
ID factory and clock so tests can produce deterministic candidates; production uses
UUIDv4 and UTC now.

**Consequences**
- Candidates are immutable and self-describing.
- There is no status transition, approval command, or publication path.
- Review tooling can rely on the envelope without reading the concept.
- ID and timestamp injection keeps tests deterministic without monkeypatching.

**Alternatives considered**
- Database sequence IDs: rejected because the slice is file-based and offline.
- File modification time as the timestamp: rejected because it is not portable or
  immutable.
- A mutable candidate document: rejected because it weakens the review/audit boundary.
- An `approved` status: rejected by the product constraints.

---

## ADR-003: Schema version as a canonical SHA-256 fingerprint

**Status:** Accepted

**Context**
Candidates must record which schema produced them. A hand-maintained version label can
drift from the physical metadata, especially when the fixture or database changes.

**Decision**
Compute `schema_version` from the selected table's canonical metadata:

- include schema name, table name, and every column;
- include column name, SQL type, nullability, and primary-key flag;
- sort columns by name;
- serialize canonical JSON with sorted object keys and UTF-8;
- hash with SHA-256 and prefix the result with `sha256:`.

**Consequences**
- Identical metadata produces an identical version regardless of provider or column
  order.
- Any physical change, including type, nullability, or PK status, changes the version.
- The candidate is traceable to a schema snapshot without storing the whole schema.
- SQL type strings are provider output; equivalent types written differently produce
  different versions. This is intentional and documented.

**Alternatives considered**
- Manual version labels: rejected because they can be forgotten or misapplied.
- Database object IDs or timestamps: rejected because they are not portable to the
  fixture and may change without schema changes.
- Storing the full schema on the candidate: rejected as duplication; the fingerprint is
  sufficient provenance for the slice.

---

## ADR-004: One or more exact physical columns per attribute

**Status:** Accepted

**Context**
Some domain attributes are naturally composite. For example, a shipping address may
span `Address`, `City`, `Region`, `PostalCode`, and `Country`. Requiring exactly one
column would force artificial splitting. Requiring exact physical references keeps the
candidate verifiable.

**Decision**
Each attribute has a `column_names` list with at least one physical column. Every name
must resolve to a column of the selected table. Lookup is case-insensitive, matching
SQL Server's default collation, and accepted names are canonicalized to the schema's
exact spelling before saving. Within one attribute, duplicate names are rejected. In
this slice, the same physical column may not be reused by two different attributes.

**Consequences**
- Composite attributes are expressible without free text.
- The saved candidate always uses the schema's exact column spelling.
- The no-reuse rule removes ambiguity about which attribute owns a column; it can be
  revisited if a legitimate shared-column use case appears.
- Validation is independent of the model's casing.

**Alternatives considered**
- Exactly one column per attribute: rejected because it cannot represent composite
  attributes cleanly.
- Free-text column descriptions: rejected because they cannot be validated.
- Strict case-sensitive matching: rejected because SQL Server is commonly
  case-insensitive; canonicalization preserves exactness in the saved output.
- Allowing column reuse: deferred; the stricter rule is easier to audit.

---

## ADR-005: LangChain structured output, independent physical validation

**Status:** Accepted

**Context**
The LLM must return a structured concept, and the product must not trust model output.
Using a free-text prompt with ad-hoc JSON extraction would make shape errors and
provider differences part of application logic.

**Decision**
Use LangChain's structured-output capability with the `ConceptProposal` Pydantic model,
wrapped behind a small `ProposalGenerator` protocol. The workflow depends on the
protocol, not a concrete provider. The structured proposal is still untrusted: a
separate validator checks every physical reference and mapping invariant. A proposal
that fails validation is never built into a candidate.

**Consequences**
- Shape errors are reported at the model boundary.
- The model cannot bypass physical validation by returning a well-formed object.
- Tests inject a fake generator and never need a key or network.
- Providers must support the structured-output mechanism used by the adapter; provider
  limitations are isolated in the adapter.
- The prompt and adapter remain replaceable without changing the graph or validator.

**Alternatives considered**
- Prompt-only JSON plus manual parsing: rejected because it duplicates structured-output
  handling and is provider-fragile.
- Let the model validate its own output: rejected because it violates the trust boundary.
- Parse into a permissive dictionary: rejected because malformed output would reach
  deeper layers.

---

## ADR-006: LangGraph for orchestration; LangChain is not a substitute

**Status:** Accepted

**Context**
Both libraries are required by the product constraints. They solve different problems,
and treating one as a replacement for the other would either lose workflow guarantees
or reimplement model integration.

**Decision**
Use LangGraph for the `propose -> validate -> finalize` workflow with explicit state,
nodes, and conditional edges. Use LangChain inside the `propose` node for prompts and
structured output. Keep physical validation in application code, not in either library.

**Consequences**
- Workflow state and failure routing are explicit and testable.
- The model integration can change providers without changing the graph.
- Validation policy is not conflated with orchestration or model parsing.
- The graph is intentionally small; if the slice had a single unconditional call,
  LangGraph would add overhead without benefit.

**Alternatives considered**
- LangChain only, with branching in a chain or imperative code: rejected because it
  hides state transitions and makes checkpointing or retries harder to add safely.
- LangGraph only, with custom HTTP/model clients: rejected because it reimplements
  message formatting, provider adapters, and structured-output parsing.
- No framework, plain functions: viable for this size, but rejected because the product
  mandates LangChain and LangGraph and the graph makes trust boundaries explicit.

**Why the libraries are not interchangeable**
LangChain is a model-integration layer: messages, prompts, provider clients, and
structured output. LangGraph is an orchestration layer: shared state, nodes, edges,
conditional routing, cycles, and checkpointing. LangGraph does not call models, and
LangChain does not provide a durable workflow state machine. Replacing one with the
other sacrifices a distinct capability; composing them preserves both.

---

## ADR-007: SQLAlchemy confined to the optional SQL Server metadata adapter

**Status:** Accepted

**Context**
The product permits SQLAlchemy only for optional SQL Server metadata inspection and
forbids arbitrary SQL execution.

**Decision**
Only `sqlserver.py` imports SQLAlchemy. It uses the Inspector API to read columns and
primary-key constraints. It does not build SQL strings, use `text()`, execute
user-supplied statements, or write to the database. The provider is selected only when
`--source sqlserver` is requested. A read-only login is recommended.

**Consequences**
- Fixture-only installs and tests need no SQLAlchemy or driver.
- The metadata path is small and auditable.
- Database permissions, not application code, enforce read-only access at the server.
- SQL Server-specific tests use pure mapping functions and fake inspectors.

**Alternatives considered**
- Query `INFORMATION_SCHEMA` with hand-written SQL: rejected as arbitrary SQL and
  provider-specific.
- Use SQLAlchemy ORM models or sessions: rejected as unnecessary and broader than
  metadata inspection.
- Put SQLAlchemy imports at package import time: rejected because it would make the
  optional dependency mandatory.

---

## ADR-008: Write-once JSON candidate files

**Status:** Accepted

**Context**
The slice needs a simple, inspectable persistence format with no approval or update
path. Candidate files must not be partially written or silently replaced.

**Decision**
Write one UTF-8 JSON file per candidate, named `<candidate_id>.json`, in the configured
candidate directory. The store revalidates the candidate against the schema, writes to a
temporary file in the same directory, and publishes exclusively; an existing target is
an error. No update, delete, approve, or publish operation exists.

**Consequences**
- Candidates are easy to inspect, diff, and archive.
- A failed write leaves no partial candidate.
- Repeated runs create distinct candidates rather than overwriting history.
- The directory grows without an automatic retention policy; retention is out of scope.
- Concurrent writers rely on exclusive creation; cross-process locking is out of scope.

**Alternatives considered**
- Append to one JSONL file: rejected because a single corrupt or partial line affects the
  whole file.
- SQLite storage: rejected as unnecessary for a small, offline slice.
- Overwrite by candidate ID: rejected because it weakens auditability.
- In-memory only: rejected because the user story requires a saved candidate.

---

## ADR-009: Environment-based configuration and offline test mode

**Status:** Accepted

**Context**
The slice needs real provider and SQL Server credentials for live use, but tests and
demos must run without either. Credentials must not enter source, fixtures, prompts,
logs, or committed files.

**Decision**
CLI flags select the table, source, fixture, output directory, and offline replay.
Environment variables provide model and SQL Server settings, with documented defaults.
Secrets are read only from the environment and are never printed or embedded in
candidates. Offline mode injects a fake proposal generator; the test suite never resolves
provider credentials. `.env` is local and gitignored; `.env.example` contains
placeholders only.

**Consequences**
- The same code supports live and offline runs.
- Tests are deterministic and credential-free.
- Missing settings produce clear errors naming the variable, not its value.
- Values with spaces or backslashes in `.env` require single quotes.
- Secret handling depends on the operator not committing a filled `.env`.

**Alternatives considered**
- Credentials in a configuration file: rejected because configuration files are easier
  to commit accidentally and harder to rotate.
- Password CLI arguments: rejected because they leak through shell history and process
  listings.
- A separate test settings module: unnecessary; dependency injection covers it.

---

## ADR-010: CLI exit-code contract

**Status:** Accepted

**Context**
The CLI is the only user interface in the slice. Automation and tests need to
distinguish a saved candidate from a rejected proposal and a configuration failure.

**Decision**
Use three exit codes:

- `0`: a candidate was validated and saved;
- `1`: the proposal was rejected by physical validation;
- `2`: unknown table, configuration/model/storage error.

No candidate file is written for `1` or `2`. Errors go to standard error; successful
runs print the candidate ID and path.

**Consequences**
- Scripts can branch on the outcome without parsing prose.
- Validation rejection is distinguishable from infrastructure failure.
- The contract is small enough to test exhaustively offline.

**Alternatives considered**
- Always exit `0` and print an error: rejected because it hides failures from automation.
- One code per issue type: rejected as unnecessary for the slice.
- Include storage failures under `1`: rejected because rejection and infrastructure
  failure have different remediation.
