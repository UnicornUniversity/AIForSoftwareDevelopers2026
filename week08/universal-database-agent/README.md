# Universal Database Agent (UDA)

UDA is a reusable, extensible agent that translates natural-language questions into safe,
read-only SQL and explains the result. The repository currently contains the **Phase 1
offline skeleton**, **Phase 2 SQL Server connectivity, schema introspection, and the DDL
Repository**, **Phase 3 structure-first semantic discovery**, and a **minimal Phase 7
query path**: configuration, CLI, adapter and LLM contracts with fakes, tracing
abstractions, compact LangGraph workflows, a SQLAlchemy-based SQL Server adapter, a
deterministic structural snapshot writer, and a validated proposal repository under
`data/knowledge/proposals/`. `uda ask` generates SQL from the DDL Repository, validates it
with SQLGlot, executes one read-only statement within a timeout and row cap, and explains
the result. The approved Semantic Repository and the approval workflow are not implemented
yet, so `uda ask` uses physical schema context rather than approved business concepts.

## Requirements

- Python 3.12 (managed by `uv`)
- [uv](https://docs.astral.sh/uv/)

## Install

```powershell
cd week08/universal-database-agent
uv venv --python 3.12
uv sync
```

`uv sync` creates `.venv/` and resolves `uv.lock`. Python 3.12 may be downloaded automatically
if it is not already installed.

## Configuration

Configuration precedence is:

```text
CLI arguments > environment variables > YAML profile > built-in defaults
```

Profiles live in `config/profiles/` and contain **non-secret** values only:

- `deepseek.yaml` — default provider (`https://api.deepseek.com/v1`, `deepseek-chat`).
- `ollama.yaml` — optional local profile (`http://localhost:11434/v1`); the model name is a
  candidate and must match an installed Ollama model.

Secrets belong in `.env` (Git-ignored). Copy the placeholders:

```powershell
Copy-Item .env.example .env
```

Environment prefixes:

- `UDA_DB_*` — database configuration and credentials.
- `UDA_LLM_*` — provider, endpoint, model, parameters, and API key.
- `LANGFUSE_*` — Langfuse public key, secret key, and host.
- `UDA_TRACER` — `noop` (default) or `langfuse`.

Secrets in YAML profiles are rejected. Configuration errors never echo secret values.

## Commands

```powershell
uv run uda --help
uv run uda config validate --profile config/profiles/deepseek.yaml
uv run uda config show --profile config/profiles/deepseek.yaml
uv run uda graph --output docs/reports/phase-1-graph.mmd
uv run uda demo --question "How many customers are there?"
uv run uda ask --question "Which products sold best in 1997?" --profile config/profiles/deepseek.yaml
uv run uda ask --question "How many customers are there?" --json
uv run uda provider check --profile config/profiles/ollama.yaml
uv run uda trace-demo --message "phase-1 smoke"

# SQL Server (requires .env database configuration)
uv run uda db check --profile config/profiles/deepseek.yaml
uv run uda db introspect --profile config/profiles/deepseek.yaml --schema dbo
uv run uda db introspect --profile config/profiles/deepseek.yaml --json

# DDL Repository: write, inspect, validate
uv run uda db snapshot --profile config/profiles/deepseek.yaml --schema dbo --repo data/knowledge/ddl
uv run uda db status --repo data/knowledge/ddl
uv run uda db validate --repo data/knowledge/ddl
uv run uda db smo
uv run uda db readonly-check --profile config/profiles/deepseek.yaml

# Normalized metadata only (skip SMO DDL extraction)
uv run uda db snapshot --profile config/profiles/deepseek.yaml --no-ddl --repo data/knowledge/ddl

# Offline extraction from a recorded fixture (no SQL Server or SMO required)
uv run uda db snapshot --fixture tests/fixtures/northwind-metadata.json --repo data/knowledge/ddl

# Structure-first semantic discovery (Phase 3)
uv run uda discover run --repo data/knowledge/ddl --proposals data/knowledge/proposals --profile config/profiles/deepseek.yaml
uv run uda discover run --repo data/knowledge/ddl --dry-run --show-prompt
uv run uda discover validate --repo data/knowledge/proposals --ddl-repo data/knowledge/ddl

# Object-level semantic discovery (one independent LLM request per table)
uv run uda discover run --strategy object-level --repo data/knowledge/ddl-live-subset --max-tables 3 --dry-run --show-prompt
uv run uda discover run --strategy object-level --repo data/knowledge/ddl-live-subset --max-tables 3 --candidates data/knowledge/discovery-runs --profile config/profiles/deepseek.yaml
```

- `config show` prints the effective configuration with secrets redacted.
- `graph` prints the LangGraph `StateGraph` as Mermaid and optionally writes it to a file.
- `demo` runs the graph with a deterministic fake LLM; it does not call a model or database.
- `ask` runs the live natural-language query path: it loads schema context from the DDL
  Repository, classifies the question (ambiguity produces a clarification request, not a
  guessed query), generates one T-SQL `SELECT`, validates it with SQLGlot against the
  object allowlist, executes it with the read-only login under the configured timeout and
  row limit, and explains the rows. Only validation failures can re-enter the bounded
  two-attempt repair loop; execution failures terminate the attempt. Results are bounded;
  truncation is reported, never silent. `--json` emits the question, status, SQL, columns,
  rows, truncation flag, answer, and warnings. `--repo` selects another validated DDL
  Repository.
- `provider check` checks whether the Ollama service is reachable without calling a model.
- `trace-demo` emits a redacted span through the configured tracer.
- `db check` validates database connectivity without reading table rows.
- `db introspect` extracts normalized schema metadata; `--json`/`--output` exports metadata.
  Exit code `3` indicates partial extraction.
- `db snapshot` extracts metadata and writes a DDL Repository snapshot. It writes normalized
  JSON artifacts, per-object SQL DDL artifacts through installed SMO when available, and
  `manifest.json`; it reports added/changed/removed objects and returns exit code `3` when
  metadata extraction is partial. Use `--no-ddl` to skip DDL extraction or `--fixture` to run
  fully offline. DDL unavailability never invalidates the normalized snapshot.
- `db status` prints the current snapshot identity, completeness, versions, Git commit, DDL
  status/provenance, and counts. `db validate` re-checks artifacts, hashes, references,
  counts, DDL status, and the snapshot ID.
- `db smo` reports SMO availability and its version; the SQLAlchemy Inspector plus catalog
  fallback works whether or not SMO is installed.
- `db readonly-check` performs a permitted read and a non-mutating effective-permission probe.
  It never attempts a write; a login with write permission reports `failed_not_read_only` and
  exits `1`.
- `discover run` loads a validated DDL Repository, assembles a deterministic evidence prompt,
  calls the configured provider **once**, validates the response with JSON Schema and
  evidence checks, and writes YAML proposals under `data/knowledge/proposals/`. Proposals are
  always `proposed`; nothing is auto-approved. Existing records are never overwritten: an
  identical record is unchanged, and a differing record is a conflict (exit code `3`).
- `discover run --dry-run` assembles the prompt without calling an LLM; `--show-prompt` writes
  it to stderr for inspection. `--no-ddl` omits per-object SQL from the prompt. The command
  reports the input snapshot, object count, prompt version/fingerprint, proposal counts,
  validation outcome, destination, warnings, and errors. Use `--json` for a machine-readable
  summary.
- `discover validate` checks the proposal manifest, record hashes, `proposed` status,
  identities, and relationship/mapping endpoints. `--ddl-repo` additionally cross-checks every
  source reference against the physical DDL Repository.
- `discover run --strategy object-level` processes tables sequentially, making one independent
  LLM request per table. It writes immutable, validated candidates under
  `data/knowledge/discovery-runs/` (request, status, result, and response hash per execution
  key, plus `runs/<run_id>/run.json`). Candidates are never published into the canonical
  proposal repository and are never auto-approved. Use `--max-tables` to bound a
  demonstration, `--candidates` to choose the candidate root, and `--dry-run`/`--show-prompt`
  to inspect the per-table prompts without calling a model. Re-running with unchanged inputs
  reuses successful candidates and makes no LLM call for them.
- DDL omission/truncation and partial snapshots are reported as explicit warnings. Increase
  `UDA_LLM_MAX_TOKENS` if a large schema needs a larger structured response.

`UDA_LLM_INTEGRATION` is a **test-only** guard for the opt-in pytest test; `uda discover run`
does not read it. Production live inference uses `UDA_LLM_PROVIDER`, `UDA_LLM_BASE_URL`,
`UDA_LLM_MODEL`, `UDA_LLM_API_KEY`, `UDA_LLM_TEMPERATURE`, `UDA_LLM_MAX_TOKENS`, and
`UDA_LLM_TIMEOUT`, plus profile and CLI overrides. `--dry-run` is the explicit no-inference
mode; a valid API key is required for non-Ollama providers.

See [docs/database-setup.md](docs/database-setup.md) for SQL Server prerequisites, authentication
modes, read-only permissions, and integration test commands.

## Tracing

Core code depends only on the `Tracer` protocol. `NoopTracer` is the default;
`LangfuseTracer` is selected by configuration and lazily imports the Langfuse SDK. Tracing is
deny-by-default: only allowlisted metadata is submitted, and credentials, connection strings,
raw rows, PII, confidential business data, and sensitive schema details are never sent.

`result_ref` is an opaque synthetic identifier, not arbitrary user-provided text. Redaction is
heuristic (credential patterns, connection strings, and obvious email addresses) and cannot
guarantee detection of every personal or confidential value.

To emit a Langfuse trace, set `observability.tracer: langfuse` in a profile (or
`UDA_TRACER=langfuse`) and provide `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and
`LANGFUSE_HOST`.

## Tests

The default suite is offline and requires no database, model, or Langfuse instance:

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
```

Optional integration markers are `db`, `llm`, and `langfuse`; they are excluded by default.
SQL Server integration tests are opt-in and skip unless a test database is configured:

```powershell
$env:UDA_DB_INTEGRATION = "1"
uv run pytest -m db
```

The live DeepSeek discovery check is opt-in and also requires a real API key:

```powershell
$env:UDA_LLM_INTEGRATION = "1"
uv run pytest -m llm
```

It skips when `UDA_LLM_INTEGRATION` is unset or `UDA_LLM_API_KEY` is missing or still
`change-me`. This flag guards only the pytest test; it is not read by `uda discover run`.
Never use production credentials for integration tests.

## Current scope

Implemented: package skeleton, Pydantic configuration, CLI, adapter/LLM protocols with fakes,
prompt registry scaffold, tracing abstraction and redaction, compact LangGraph workflows with
visualization, SQL Server connectivity and normalized schema introspection through SQLAlchemy
Inspector and supplementary SQL Server catalog queries, a deterministic DDL Repository writer
with a validated `data/knowledge/ddl/manifest.json`, per-object SQL DDL extraction through
installed SMO, a non-mutating read-only credential check, structure-first semantic
discovery with a validated proposal repository under `data/knowledge/proposals/` (status
`proposed` only), and a minimal live query path: DDL-derived schema context, LLM SQL
generation, SQLGlot validation (single read-only statement, object allowlist), bounded
read execution, and result explanation.

The repository records the extracted physical structure (schemas, tables, views, columns,
keys, indexes, descriptions, computed columns, and extraction issues) plus per-object SQL DDL
artifacts. It never stores table rows and never contains semantic concepts or approvals. Table
definitions are generated by SMO from live metadata (`smo_scripter`); view definitions use the
stored server module text (`server_module_definition`). The manifest records provenance
explicitly. SMO is never installed or loaded into the Python process, and DDL unavailability
leaves the normalized snapshot valid.

The `demo` graph's `demo_validate_sql` node remains a demonstration-only placeholder and is
not a SQL safety boundary. The live `ask` path uses the separate `uda.query` graph, whose
validator is SQLGlot-based and whose execution path is bounded by the read-only credential,
a statement timeout, and a row cap.

The live query path currently derives context from the physical DDL Repository only; it does
not yet consume the approved Semantic Repository or its concept mappings. The `ask` path is
the minimal Phase 7 implementation; semantic-repository-backed mapping, cancellation,
result-by-reference state management, and the full security corpus remain roadmap work.

Deferred: the approved Semantic Repository, the semantic approval workflow,
semantic-repository-backed NL-to-SQL, Level 2 evaluation, PostgreSQL, and web UI.
