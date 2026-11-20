# Universal Database Access (UDA) - classroom demo

A deliberately small, CLI-first pipeline that turns **one relational table schema**
into a **reviewable semantic candidate**:

1. read a table schema (bundled fixture by default, or optional SQL Server metadata);
2. ask an LLM for one concept and its attribute-to-column mappings;
3. validate every physical reference;
4. write a `pending_review` JSON candidate.

The LLM proposes. Nothing is auto-approved or published. Database access is read-only,
and arbitrary SQL is never generated or executed.

## Status

Complete - domain contract, demo fixture, validation, LangGraph workflow, CLI,
candidate persistence, the optional DeepSeek provider, and optional read-only
SQL Server metadata inspection.

## Layout

```
pyproject.toml                  uv project (Python 3.12)
src/uda/models.py               Pydantic domain contract
src/uda/fixtures/               bundled demo schema + loader
src/uda/validation.py           physical-reference issues
src/uda/candidate.py            pending_review candidate builder
src/uda/prompt.py               deterministic proposal prompt
src/uda/workflow.py             LangGraph workflow and WorkflowResult
src/uda/storage.py              validated candidate JSON writer
src/uda/provider.py             optional DeepSeek chat model
src/uda/sqlserver.py            optional read-only metadata inspection
src/uda/cli.py                  `uda propose` entry point
tests/                          offline tests
```

## CLI

```bash
# real provider (DeepSeek via its OpenAI-compatible endpoint)
uv sync --extra llm
cp .env.example .env                 # fill DEEPSEEK_API_KEY locally; never commit
uv run --env-file .env --extra llm uda propose --out out/candidate.json

# offline: replay a canned model response, no key or network
uv run uda propose --response-file tests/fixtures/response.json --out out/candidate.json

# optional SQL Server metadata source (read-only login recommended)
uv sync --extra llm --extra sqlserver
cp .env.example .env                 # fill UDA_DB_SERVER/DATABASE/USER/PASSWORD
uv run --env-file .env --extra llm --extra sqlserver \
  uda propose --sqlserver dbo.Customer --out out/candidate.json
```

`--sqlserver TABLE` accepts `table` or `schema.table` (default schema `dbo`) and
reads catalog metadata only. `UDA_DB_SERVER` accepts `HOST`, `HOST,PORT`, or
`HOST\INSTANCE`; values containing a backslash or spaces must be single-quoted in
`.env` (for example `UDA_DB_SERVER='HOST\INSTANCE'` and
`UDA_DB_DRIVER='ODBC Driver 18 for SQL Server'`). The default driver is
`ODBC Driver 18 for SQL Server`; override it with `UDA_DB_DRIVER`. `Encrypt=yes`
and `TrustServerCertificate=yes` are local development defaults; set the latter
to `no` when the server has a trusted certificate.

Exit codes: `0` candidate written, `1` proposal rejected by validation, `2`
configuration or model-output error. The default output is `out/candidate.json`
(gitignored), and every written candidate has status `pending_review`.

## Workflow

`run_workflow(schema, model)` accepts any LangChain chat model and runs
`propose -> validate -> finalize`. Unparsable model output becomes
`WorkflowResult.error`; physical-reference issues stop the run before a candidate
is built. Tests inject `FakeListChatModel`, so they need no API key or network.
The real DeepSeek provider is optional (`--extra llm`); offline runs use
`--response-file`.

## Validation rules

- Every mapped column must exist in the table (case-insensitive, SQL Server default).
- One physical column may be mapped by at most one attribute.
- A candidate's table reference must match the schema's qualified name.
- A proposal with any issue is rejected; candidates are only built as `pending_review`.

## Safety

- Metadata only: no arbitrary SQL is generated or executed; SQL Server access goes
  through SQLAlchemy's inspector, and a read-only login is recommended.
- Model output is untrusted: it must parse as `ConceptProposal` and pass
  physical-reference validation before a candidate exists.
- Only `pending_review` candidates can exist; nothing is approved or published.
- No credentials in source, fixtures, logs, prompts, or committed `.env`.

## Commands

```bash
uv sync --all-extras    # optional provider and SQL Server extras
uv run pytest           # offline: no API key, database, network, or Langfuse
uv run ruff check .
```

## Constraints

- Python 3.12, managed with `uv`.
- LangChain for LLM interaction, LangGraph for orchestration, Pydantic for models.
- SQLAlchemy only for optional SQL Server metadata inspection.
- Offline tests require no API key, database, network, or Langfuse.
- No credentials in source, fixtures, logs, prompts, or committed `.env`.
