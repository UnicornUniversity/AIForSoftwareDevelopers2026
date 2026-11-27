"""CLI entry point."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from .adapters.ddl import SmoDdlExtractor
from .adapters.readonly import ReadOnlyVerification, verify_read_only
from .adapters.smo import SmoStatus, detect_smo_availability
from .adapters.sqlserver import SqlServerAdapter, build_connection_url
from .config import AppConfig, CliOverrides, load_config, load_env_file
from .discovery.evidence import load_ddl_repository
from .discovery.graph import DiscoveryRunConfig, build_discovery_graph
from .discovery.object_graph import (
    ObjectDiscoveryRunConfig,
    ObjectRunResult,
    plan_object_requests,
    run_object_level_discovery,
)
from .discovery.prompt import build_discovery_prompt
from .discovery.proposals import (
    ProposalRepositoryValidation,
    validate_proposal_repository,
)
from .errors import ConfigurationError, UDAError
from .graph import build_query_graph, render_mermaid
from .llm import build_llm_client
from .llm.fake import FakeLLMClient
from .metadata.fixtures import filter_metadata_schemas, load_metadata_fixture
from .prompts import PromptRegistry
from .query import build_live_query_graph, build_schema_context
from .repository import (
    DdlRepositoryWriter,
    RepositoryValidation,
    WriteResult,
    validate_repository,
)
from .repository.manifest import DdlManifest
from .tracing import build_tracer
from .tracing.noop import NoopTracer

DEFAULT_PROFILE = Path("config/profiles/deepseek.yaml")
DEFAULT_DDL_REPOSITORY = Path("data/knowledge/ddl")
DEFAULT_PROPOSALS_REPOSITORY = Path("data/knowledge/proposals")
DEFAULT_CANDIDATES_REPOSITORY = Path("data/knowledge/discovery-runs")
DEFAULT_PROMPT_REGISTRY = Path("config/prompts/registry.yaml")
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_CONFIG = 2
EXIT_PARTIAL = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uda",
        description="Universal Database Agent",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to a .env file (default: .env)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="Inspect or validate configuration")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)

    show = config_commands.add_parser("show", help="Show effective configuration, secrets masked")
    _add_profile_option(show)
    show.add_argument("--json", action="store_true", help="Emit JSON")
    _add_override_options(show)

    validate = config_commands.add_parser("validate", help="Validate configuration")
    _add_profile_option(validate)
    _add_override_options(validate)

    graph_parser = subparsers.add_parser("graph", help="Print the LangGraph diagram as Mermaid")
    _add_profile_option(graph_parser)
    graph_parser.add_argument("--output", type=Path, help="Write the Mermaid diagram to a file")

    demo = subparsers.add_parser("demo", help="Run the graph with a fake LLM")
    _add_profile_option(demo)
    demo.add_argument(
        "--question",
        default="How many customers are there?",
        help="Question to pass through the skeleton graph",
    )

    ask = subparsers.add_parser(
        "ask", help="Ask a natural-language question and run a read-only query"
    )
    _add_profile_option(ask)
    _add_override_options(ask)
    ask.add_argument("--question", required=True, help="Natural-language question")
    ask.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_DDL_REPOSITORY,
        help=f"Validated DDL Repository (default: {DEFAULT_DDL_REPOSITORY})",
    )
    ask.add_argument("--json", action="store_true", help="Emit a machine-readable result")

    provider_parser = subparsers.add_parser("provider", help="Provider diagnostics")
    provider_commands = provider_parser.add_subparsers(dest="provider_command", required=True)
    check = provider_commands.add_parser("check", help="Check provider service availability")
    _add_profile_option(check)
    check.add_argument("--timeout", type=float, default=2.0, help="Seconds to wait")

    trace = subparsers.add_parser("trace-demo", help="Emit one redacted trace span")
    _add_profile_option(trace)
    trace.add_argument("--message", default="phase-1 smoke", help="Message length sample")

    db_parser = subparsers.add_parser("db", help="Database connectivity and introspection")
    db_commands = db_parser.add_subparsers(dest="db_command", required=True)
    db_check = db_commands.add_parser("check", help="Validate database connectivity")
    _add_profile_option(db_check)
    db_introspect = db_commands.add_parser(
        "introspect", help="Extract normalized schema metadata"
    )
    _add_profile_option(db_introspect)
    db_introspect.add_argument(
        "--schema",
        action="append",
        dest="schemas",
        help="Schema to inspect; repeat for multiple schemas (default: all visible)",
    )
    db_introspect.add_argument("--json", action="store_true", help="Print metadata as JSON")
    db_introspect.add_argument(
        "--output", type=Path, help="Write metadata JSON to a file"
    )

    db_snapshot = db_commands.add_parser(
        "snapshot", help="Extract metadata and write a DDL Repository snapshot"
    )
    _add_profile_option(db_snapshot)
    db_snapshot.add_argument(
        "--schema",
        action="append",
        dest="schemas",
        help="Schema to extract; repeat for multiple schemas (default: all visible)",
    )
    db_snapshot.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_DDL_REPOSITORY,
        help=f"DDL Repository root (default: {DEFAULT_DDL_REPOSITORY})",
    )
    db_snapshot.add_argument(
        "--fixture",
        type=Path,
        help="Use recorded metadata instead of a live database",
    )
    db_snapshot.add_argument(
        "--no-ddl",
        action="store_true",
        help="Skip SMO DDL extraction (normalized metadata is still written)",
    )
    db_snapshot.add_argument(
        "--ddl-timeout",
        type=float,
        default=120.0,
        help="SMO extraction timeout in seconds (default: 120)",
    )
    db_snapshot.add_argument("--json", action="store_true", help="Emit JSON summary")

    db_validate = db_commands.add_parser(
        "validate", help="Validate an existing DDL Repository"
    )
    db_validate.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_DDL_REPOSITORY,
        help=f"DDL Repository root (default: {DEFAULT_DDL_REPOSITORY})",
    )
    db_validate.add_argument("--json", action="store_true", help="Emit JSON result")

    db_status = db_commands.add_parser(
        "status", help="Show DDL Repository snapshot summary and completeness"
    )
    db_status.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_DDL_REPOSITORY,
        help=f"DDL Repository root (default: {DEFAULT_DDL_REPOSITORY})",
    )
    db_status.add_argument("--json", action="store_true", help="Emit JSON summary")

    db_smo = db_commands.add_parser("smo", help="Check SMO availability")
    db_smo.add_argument("--json", action="store_true", help="Emit JSON result")

    db_readonly = db_commands.add_parser(
        "readonly-check", help="Verify the configured login has no write permissions"
    )
    _add_profile_option(db_readonly)
    db_readonly.add_argument("--json", action="store_true", help="Emit JSON result")

    discover_parser = subparsers.add_parser(
        "discover",
        help="Semantic discovery (single-shot Phase 3 or object-level strategy)",
    )
    discover_commands = discover_parser.add_subparsers(
        dest="discover_command", required=True
    )
    discover_run = discover_commands.add_parser(
        "run", help="Run discovery and write validated proposals"
    )
    _add_profile_option(discover_run)
    _add_override_options(discover_run)
    discover_run.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_DDL_REPOSITORY,
        help=f"DDL Repository root (default: {DEFAULT_DDL_REPOSITORY})",
    )
    discover_run.add_argument(
        "--strategy",
        choices=["single", "object-level"],
        default="single",
        help="Discovery strategy (default: single, the Phase 3 pipeline)",
    )
    discover_run.add_argument(
        "--proposals",
        type=Path,
        default=DEFAULT_PROPOSALS_REPOSITORY,
        help=f"Proposal Repository root (default: {DEFAULT_PROPOSALS_REPOSITORY})",
    )
    discover_run.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES_REPOSITORY,
        help=(
            "Object-level candidate store root "
            f"(default: {DEFAULT_CANDIDATES_REPOSITORY})"
        ),
    )
    discover_run.add_argument(
        "--max-tables",
        type=int,
        default=None,
        help="Limit the number of tables processed by object-level discovery",
    )
    discover_run.add_argument(
        "--prompts",
        type=Path,
        default=DEFAULT_PROMPT_REGISTRY,
        help=f"Prompt registry path (default: {DEFAULT_PROMPT_REGISTRY})",
    )
    discover_run.add_argument(
        "--no-ddl",
        action="store_true",
        help="Omit per-object SQL DDL from the discovery prompt",
    )
    discover_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Assemble and summarize the prompt without calling an LLM",
    )
    discover_run.add_argument(
        "--show-prompt",
        action="store_true",
        help="Write the assembled prompt to stderr for inspection",
    )
    discover_run.add_argument("--json", action="store_true", help="Emit a JSON summary")

    discover_validate = discover_commands.add_parser(
        "validate", help="Validate an existing Proposal Repository"
    )
    discover_validate.add_argument(
        "--repo",
        type=Path,
        default=DEFAULT_PROPOSALS_REPOSITORY,
        help=f"Proposal Repository root (default: {DEFAULT_PROPOSALS_REPOSITORY})",
    )
    discover_validate.add_argument(
        "--ddl-repo",
        type=Path,
        help="Cross-check source references against this DDL Repository",
    )
    discover_validate.add_argument("--json", action="store_true", help="Emit JSON result")

    return parser


def _add_profile_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help=f"YAML profile path (default: {DEFAULT_PROFILE})",
    )


def _add_override_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", help="Override LLM provider")
    parser.add_argument("--base-url", help="Override LLM base URL")
    parser.add_argument("--model", help="Override LLM model")
    parser.add_argument("--tracer", choices=["noop", "langfuse"], help="Override tracer")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        load_env_file(args.env_file)
        return _dispatch(args)
    except ConfigurationError as exc:
        print(f"uda: configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except UDAError as exc:
        print(f"uda: error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "config":
        if args.config_command == "show":
            return _config_show(args)
        return _config_validate(args)
    if args.command == "graph":
        return _graph(args)
    if args.command == "demo":
        return _demo(args)
    if args.command == "ask":
        return _ask(args)
    if args.command == "provider":
        return _provider_check(args)
    if args.command == "trace-demo":
        return _trace_demo(args)
    if args.command == "db":
        if args.db_command == "check":
            return _db_check(args)
        if args.db_command == "introspect":
            return _db_introspect(args)
        if args.db_command == "snapshot":
            return _db_snapshot(args)
        if args.db_command == "validate":
            return _db_validate(args)
        if args.db_command == "status":
            return _db_status(args)
        if args.db_command == "readonly-check":
            return _db_readonly_check(args)
        return _db_smo(args)
    if args.command == "discover":
        if args.discover_command == "run":
            if args.strategy == "object-level":
                return _discover_run_object_level(args)
            return _discover_run(args)
        return _discover_validate(args)
    raise ConfigurationError(f"Unknown command: {args.command}")


def _resolve(args: argparse.Namespace) -> AppConfig:
    overrides = CliOverrides(
        provider=getattr(args, "provider", None),
        base_url=getattr(args, "base_url", None),
        model=getattr(args, "model", None),
        tracer=getattr(args, "tracer", None),
    )
    return load_config(profile_path=args.profile, overrides=overrides)


def _config_show(args: argparse.Namespace) -> int:
    config = _resolve(args)
    data = config.redacted_dump()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        for key, value in _flatten(data):
            print(f"{key} = {value}")
    return EXIT_OK


def _config_validate(args: argparse.Namespace) -> int:
    config = _resolve(args)
    print(f"Configuration OK (profile: {config.profile})")
    return EXIT_OK


def _graph(args: argparse.Namespace) -> int:
    _resolve(args)
    compiled = build_query_graph(FakeLLMClient(), NoopTracer())
    mermaid = render_mermaid(compiled)
    print(mermaid)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(mermaid + "\n", encoding="utf-8")
        print(f"Graph written to {args.output}", file=sys.stderr)
    return EXIT_OK


def _demo(args: argparse.Namespace) -> int:
    config = _resolve(args)
    tracer = build_tracer(config)
    compiled = build_query_graph(FakeLLMClient(), tracer)
    result = compiled.invoke({"question": args.question, "retry_count": 0})
    tracer.flush()
    print(f"status: {result.get('status')}")
    print(f"answer: {result.get('answer')}")
    return EXIT_OK


def _ask(args: argparse.Namespace) -> int:
    config = _resolve(args)
    evidence = load_ddl_repository(args.repo)
    context = build_schema_context(
        evidence.metadata, default_schema=config.database.schema_name
    )
    registry = PromptRegistry.load(DEFAULT_PROMPT_REGISTRY)
    tracer = build_tracer(config)
    adapter = SqlServerAdapter(config.database)
    try:
        adapter.connect()
        compiled = build_live_query_graph(
            build_llm_client(config),
            tracer,
            adapter=adapter,
            schema_context=context,
            registry=registry,
            timeout_seconds=config.database.query_timeout_seconds,
            row_limit=config.database.row_limit,
        )
        result = compiled.invoke({"question": args.question, "retry_count": 0})
    finally:
        adapter.close()
        tracer.flush()
    warnings = (*evidence.warnings, *context.warnings)
    return _print_ask_result(
        result, question=args.question, warnings=warnings, json_output=args.json
    )


def _display_value(value: object, *, max_length: int = 60) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return "<binary>"
    text = str(value)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _render_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    max_display_rows: int = 50,
) -> str:
    if not columns:
        return "(no columns)"
    if not rows:
        return "(no rows)"
    display = rows[:max_display_rows]
    cells = [[_display_value(value) for value in row] for row in display]
    widths = [len(column) for column in columns]
    for row in cells:
        for index, cell in enumerate(row[: len(widths)]):
            widths[index] = max(widths[index], len(cell))

    def render_line(values: Sequence[str]) -> str:
        return " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values[: len(widths)])
        )

    lines = [render_line(list(columns)), "-+-".join("-" * width for width in widths)]
    lines.extend(render_line(row) for row in cells)
    if len(rows) > len(display):
        lines.append(f"... {len(rows) - len(display)} more row(s)")
    return "\n".join(lines)


def _print_ask_result(
    result: dict[str, Any],
    *,
    question: str,
    warnings: Sequence[str],
    json_output: bool,
) -> int:
    for warning in warnings:
        print(f"uda: warning: {warning}", file=sys.stderr)
    status = str(result.get("status", ""))
    columns = tuple(result.get("result_columns", ()))
    rows = tuple(result.get("result_rows", ()))
    truncated = bool(result.get("result_truncated", False))
    answer = str(result.get("answer", ""))
    sql = str(result.get("candidate_sql", ""))

    if json_output:
        payload = {
            "question": question,
            "status": status,
            "sql": sql,
            "columns": list(columns),
            "rows": [list(row) for row in rows],
            "truncated": truncated,
            "answer": answer,
            "warnings": list(warnings),
        }
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return EXIT_OK if status in {"answered", "clarification_required"} else EXIT_RUNTIME

    if status == "clarification_required":
        print(answer or "Please clarify your question.")
        return EXIT_OK
    if status == "execution_failed":
        print(answer or "The query could not be executed.", file=sys.stderr)
        return EXIT_RUNTIME
    if status != "answered":
        print(f"uda: query generation failed: {answer}", file=sys.stderr)
        return EXIT_RUNTIME

    print("SQL:")
    print(sql or "(no SQL)")
    print()
    print(_render_table(columns, rows))
    if truncated:
        print(f"(truncated at {len(rows)} row(s); refine the question for a smaller result)")
    print()
    print("Answer:")
    print(answer)
    return EXIT_OK


def _provider_check(args: argparse.Namespace) -> int:
    config = _resolve(args)
    if config.llm.provider != "ollama":
        print(
            f"Profile provider is '{config.llm.provider}', not 'ollama'; "
            "use config/profiles/ollama.yaml."
        )
        return EXIT_OK
    available = check_ollama_available(config.llm.base_url, timeout=args.timeout)
    print(f"Ollama at {config.llm.base_url}: {'available' if available else 'unavailable'}")
    return EXIT_OK if available else EXIT_RUNTIME


def _trace_demo(args: argparse.Namespace) -> int:
    config = _resolve(args)
    tracer = build_tracer(config)
    with tracer.span(
        "phase1_smoke",
        question_length=len(args.message),
        result_ref="demo",
        question=args.message,
    ):
        pass
    tracer.flush()
    if config.observability.tracer == "langfuse":
        print("Trace emitted through langfuse tracer.")
    else:
        print("No external trace emitted: noop tracer is active.")
    return EXIT_OK


def _db_check(args: argparse.Namespace) -> int:
    config = _resolve(args)
    adapter = SqlServerAdapter(config.database)
    try:
        adapter.connect()
        auth = "windows integrated" if config.database.trusted_connection else "sql server"
        print(f"Connection OK (auth: {auth}, database: {config.database.name})")
    finally:
        adapter.close()
    return EXIT_OK


def _db_introspect(args: argparse.Namespace) -> int:
    config = _resolve(args)
    adapter = SqlServerAdapter(config.database)
    try:
        adapter.connect()
        metadata = adapter.introspect(schemas=args.schemas)
    finally:
        adapter.close()

    payload = metadata.model_dump(mode="json", by_alias=True)
    as_json = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(as_json + "\n", encoding="utf-8")
        print(f"Metadata written to {args.output}", file=sys.stderr)
    if args.json:
        print(as_json)
    else:
        print(f"Database: {metadata.identity.database}")
        print(f"Schemas: {len(metadata.schemas)}")
        print(f"Tables: {metadata.table_count}")
        print(f"Views: {metadata.view_count}")
        print(f"Columns: {metadata.column_count}")
        print(f"Primary keys: {metadata.primary_key_count}")
        print(f"Foreign keys: {metadata.foreign_key_count}")
        print(f"Indexes: {metadata.index_count}")
    if metadata.issues:
        print(
            f"Partial extraction: {len(metadata.issues)} metadata issue(s).",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    return EXIT_OK


def _db_snapshot(args: argparse.Namespace) -> int:
    smo = detect_smo_availability()
    ddl = None
    if args.fixture is not None:
        metadata = filter_metadata_schemas(
            load_metadata_fixture(args.fixture), args.schemas
        )
        source = "fixture"
    else:
        config = _resolve(args)
        adapter = SqlServerAdapter(config.database)
        try:
            adapter.connect()
            metadata = adapter.introspect(schemas=args.schemas)
        finally:
            adapter.close()
        source = "sqlserver"
        if not args.no_ddl:
            ddl = SmoDdlExtractor(
                config.database, timeout_seconds=args.ddl_timeout
            ).extract(metadata)

    result = DdlRepositoryWriter(args.repo).write(
        metadata, source=source, smo=smo, ddl=ddl
    )
    payload = _snapshot_payload(result, source=source, smo=smo)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Database: {metadata.identity.database}")
        print(f"Snapshot: {result.snapshot_id}")
        print(f"Run: {result.run_id}")
        print(f"Status: {result.status}")
        print(f"Source: {source}")
        print(f"Repository: {result.root}")
        print(f"Manifest: {result.manifest_path}")
        print(
            "Counts: "
            + ", ".join(f"{key}={value}" for key, value in result.counts.items())
        )
        print(
            "Changes: "
            f"added={len(result.changes.added)}, "
            f"changed={len(result.changes.changed)}, "
            f"removed={len(result.changes.removed)}"
        )
        print(_format_smo_status(smo))
        print(
            f"DDL: {result.ddl_status} "
            f"({result.ddl_extracted}/{result.ddl_object_count} objects extracted)"
        )
    if result.ddl_status in {"failed", "unavailable"}:
        print(
            f"DDL extraction status: {result.ddl_status}. "
            "The normalized snapshot remains valid; see manifest extraction.ddl.",
            file=sys.stderr,
        )
    if result.status == "partial":
        print(
            f"Partial extraction: {result.issue_count} metadata issue(s) recorded.",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    return EXIT_OK


def _snapshot_payload(
    result: WriteResult, *, source: str, smo: SmoStatus
) -> dict[str, Any]:
    return {
        "repository": str(result.root),
        "manifest": str(result.manifest_path),
        "snapshot_id": result.snapshot_id,
        "run_id": result.run_id,
        "status": result.status,
        "issue_count": result.issue_count,
        "source": source,
        "counts": result.counts,
        "changes": {
            "added": list(result.changes.added),
            "changed": list(result.changes.changed),
            "removed": list(result.changes.removed),
        },
        "smo": {
            "available": smo.available,
            "version": smo.version,
            "mechanism": smo.mechanism,
        },
        "ddl": {
            "status": result.ddl_status,
            "extracted": result.ddl_extracted,
            "objects": result.ddl_object_count,
        },
    }


def _format_smo_status(smo: SmoStatus) -> str:
    if smo.available:
        suffix = f" ({smo.version})" if smo.version else ""
        return f"SMO: available{suffix} [mechanism: {smo.mechanism}]"
    return "SMO: unavailable; SQLAlchemy Inspector and catalog fallback remains active."


def _db_validate(args: argparse.Namespace) -> int:
    validation = validate_repository(args.repo)
    if args.json:
        print(
            json.dumps(
                _validation_payload(validation),
                indent=2,
                sort_keys=True,
            )
        )
    elif validation.valid:
        print(
            f"Repository valid: yes (status: {validation.status}, "
            f"snapshot: {validation.manifest.snapshot.id if validation.manifest else '-'})"
        )
    else:
        print("Repository valid: no", file=sys.stderr)
        for error in validation.errors:
            print(f"- {error}", file=sys.stderr)
    return EXIT_OK if validation.valid else EXIT_RUNTIME


def _validation_payload(validation: RepositoryValidation) -> dict[str, Any]:
    manifest = validation.manifest
    return {
        "valid": validation.valid,
        "status": validation.status,
        "errors": list(validation.errors),
        "snapshot_id": manifest.snapshot.id if manifest is not None else None,
        "manifest": (
            manifest.model_dump(mode="json", by_alias=True)
            if manifest is not None
            else None
        ),
    }


def _db_status(args: argparse.Namespace) -> int:
    validation = validate_repository(args.repo)
    manifest = validation.manifest
    if manifest is None:
        if args.json:
            print(json.dumps(_validation_payload(validation), indent=2, sort_keys=True))
        else:
            print("DDL Repository manifest is missing or invalid.", file=sys.stderr)
            for error in validation.errors:
                print(f"- {error}", file=sys.stderr)
        return EXIT_RUNTIME
    if args.json:
        print(json.dumps(_validation_payload(validation), indent=2, sort_keys=True))
    else:
        _print_manifest_summary(manifest, valid=validation.valid)
    if not validation.valid:
        for error in validation.errors:
            print(f"- {error}", file=sys.stderr)
        return EXIT_RUNTIME
    return EXIT_OK


def _print_manifest_summary(manifest: DdlManifest, *, valid: bool) -> None:
    snapshot = manifest.snapshot
    git = manifest.git
    print(f"Repository: {manifest.repository}")
    print(f"Database: {manifest.database.name} ({manifest.database.platform})")
    print(f"Snapshot: {snapshot.id}")
    print(f"Status: {snapshot.status}")
    print(f"Valid: {'yes' if valid else 'no'}")
    print(f"Run: {snapshot.run_id}")
    print(f"Created: {snapshot.created_at}")
    print(f"Generator: {manifest.generator.name} {manifest.generator.version}")
    print(f"Schema version: {manifest.schema_version}")
    if git.available:
        print(f"Git commit: {git.commit}")
    else:
        print(f"Git commit: unavailable ({git.detail or 'not available'})")
    print(f"Source: {manifest.extraction.source}")
    print(
        "SMO: "
        + (
            f"available ({manifest.extraction.smo.version or 'version unknown'})"
            if manifest.extraction.smo.available
            else "unavailable"
        )
    )
    print(
        "Original DDL: "
        + ("available" if manifest.extraction.original_ddl.available else "unavailable")
    )
    ddl = manifest.extraction.ddl
    if ddl is None:
        print("DDL: not recorded (legacy manifest)")
    else:
        extracted = sum(1 for item in ddl.objects if item.status == "extracted")
        print(
            f"DDL: {ddl.status} ({extracted}/{len(ddl.objects)} extracted; "
            f"mechanism: {ddl.mechanism or '-'}, version: {ddl.version or '-'})"
        )
        if extracted:
            original = sum(
                1
                for item in ddl.objects
                if item.status == "extracted" and item.is_original_text
            )
            print(
                f"DDL provenance: {original} stored module definition(s), "
                f"{extracted - original} SMO-generated definition(s)"
            )
    print(f"Issues: {manifest.extraction.issue_count}")
    print(f"External references: {len(manifest.external_references)}")
    print(
        "Counts: "
        + ", ".join(
            f"{key}={value}" for key, value in manifest.counts.model_dump().items()
        )
    )


def _db_smo(args: argparse.Namespace) -> int:
    smo = detect_smo_availability()
    if args.json:
        print(
            json.dumps(
                {
                    "available": smo.available,
                    "version": smo.version,
                    "mechanism": smo.mechanism,
                    "detail": smo.detail,
                    "fallback": smo.fallback,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_format_smo_status(smo))
        print(smo.detail)
        if not smo.available:
            print(smo.fallback)
    return EXIT_OK if smo.available else EXIT_RUNTIME


def _db_readonly_check(args: argparse.Namespace) -> int:
    config = _resolve(args)
    engine = create_engine(build_connection_url(config.database))
    try:
        try:
            with engine.connect() as connection:
                verification = verify_read_only(
                    connection, secret=config.database.password
                )
        except Exception as exc:  # noqa: BLE001 - converted to a verification status
            verification = ReadOnlyVerification(
                status="unavailable",
                detail=f"Read-only verification could not run ({type(exc).__name__}).",
            )
    finally:
        engine.dispose()

    payload = {
        "status": verification.status,
        "detail": verification.detail,
        "granted_permissions": list(verification.granted_permissions),
        "write_probe_attempted": verification.write_probe_attempted,
        "write_probe_rejected": verification.write_probe_rejected,
        "database": config.database.name,
        "auth": (
            "windows integrated"
            if config.database.trusted_connection
            else "sql server"
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Read-only verification: {verification.status}")
        print(verification.detail)
        print(
            "Write probe attempted: "
            + ("yes" if verification.write_probe_attempted else "no")
        )
        if verification.granted_permissions:
            print(
                "Granted write permissions: "
                + ", ".join(verification.granted_permissions)
            )
    return (
        EXIT_OK
        if verification.status == "verified_read_only"
        else EXIT_RUNTIME
    )


def _discover_run_object_level(args: argparse.Namespace) -> int:
    if args.max_tables is not None and args.max_tables < 1:
        raise ConfigurationError("--max-tables must be a positive integer.")
    registry = PromptRegistry.load(args.prompts)

    if args.dry_run:
        evidence = load_ddl_repository(args.repo)
        dry_config = ObjectDiscoveryRunConfig(
            provider="dry-run",
            model="dry-run",
            temperature=0.0,
            max_tokens=1,
            include_ddl=not args.no_ddl,
            max_tables=args.max_tables,
        )
        plans = plan_object_requests(
            evidence, registry, dry_config, max_tables=args.max_tables
        )
        payload = {
            "status": "dry_run",
            "strategy": "object-level",
            "ddl_repository": str(args.repo),
            "snapshot_id": evidence.snapshot_id,
            "database": {
                "platform": evidence.database.platform,
                "name": evidence.database.database,
            },
            "candidate_root": str(args.candidates),
            "tables_scheduled": len(plans),
            "tables": [
                {
                    "object_physical_id": plan.table.physical_id,
                    "object_kind": plan.table.object_type,
                    "prompt_version": plan.prompt.prompt_version,
                    "prompt_sha256": plan.prompt.prompt_sha256,
                    "evidence_sha256": plan.prompt.evidence_sha256,
                    "ddl_included": plan.prompt.ddl_included,
                    "truncated_ddl": plan.prompt.truncated_ddl,
                    "warnings": list(plan.prompt.warnings),
                }
                for plan in plans
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"DDL Repository: {args.repo}")
            print(f"Snapshot: {evidence.snapshot_id}")
            print(
                f"Database: {evidence.database.database} "
                f"({evidence.database.platform})"
            )
            print("Strategy: object-level")
            print(f"Tables scheduled: {len(plans)}")
            print(f"Candidate root: {args.candidates}")
            for plan in plans:
                print(
                    f"- {plan.table.physical_id}: prompt {plan.prompt.prompt_version}, "
                    f"DDL included={plan.prompt.ddl_included}"
                )
        if args.show_prompt:
            for plan in plans:
                print(
                    f"=== prompt: {plan.table.physical_id} ===",
                    file=sys.stderr,
                )
                for message in plan.prompt.messages:
                    print(f"--- {message.type} ---", file=sys.stderr)
                    print(str(message.content), file=sys.stderr)
        return EXIT_OK

    config = _resolve(args)
    llm = build_llm_client(config)
    tracer = build_tracer(config)
    run_config = ObjectDiscoveryRunConfig(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        include_ddl=not args.no_ddl,
        max_tables=args.max_tables,
    )
    try:
        result = run_object_level_discovery(
            llm,
            tracer,
            registry=registry,
            candidates_root=args.candidates,
            ddl_repository=args.repo,
            run_config=run_config,
            max_tables=args.max_tables,
        )
    finally:
        tracer.flush()
    return _object_run_report(result, args)


def _object_run_report(result: ObjectRunResult, args: argparse.Namespace) -> int:
    payload = {
        "status": result.status,
        "strategy": "object-level",
        "run_id": result.run_id,
        "run_record": str(result.run_path) if result.run_path is not None else None,
        "candidate_root": str(args.candidates),
        "tables_scheduled": result.tables_scheduled,
        "tables_succeeded": result.tables_succeeded,
        "tables_reused": result.tables_reused,
        "tables_failed": result.tables_failed,
        "warnings": list(result.warnings),
        "tables": [
            {
                "object_physical_id": outcome.object_physical_id,
                "object_kind": outcome.object_kind,
                "status": outcome.status,
                "candidate_id": outcome.candidate_id,
                "concepts": outcome.concepts,
                "mappings": outcome.mappings,
                "validation": outcome.validation,
                "errors": list(outcome.errors),
                "message": outcome.message,
            }
            for outcome in result.outcomes
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Strategy: object-level")
        print(f"Run: {result.run_id}")
        if result.run_path is not None:
            print(f"Run record: {result.run_path}")
        print(f"Candidate root: {args.candidates}")
        print(f"Tables scheduled: {result.tables_scheduled}")
        print(f"Status: {result.status}")
        print(
            f"Succeeded: {result.tables_succeeded} "
            f"(reused: {result.tables_reused})"
        )
        print(f"Failed: {result.tables_failed}")
        if result.status == "no_tables":
            print("No tables were selected; nothing was processed.")
        for outcome in result.outcomes:
            detail = (
                f"- {outcome.object_physical_id}: {outcome.status} "
                f"(concepts={outcome.concepts}, mappings={outcome.mappings})"
            )
            print(detail)
            if outcome.message:
                print(f"  {outcome.message}")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)}", file=sys.stderr)
        for warning in result.warnings:
            print(f"- {warning}", file=sys.stderr)
    for outcome in result.outcomes:
        if not outcome.succeeded:
            print(
                f"Table failed: {outcome.object_physical_id} ({outcome.status})",
                file=sys.stderr,
            )
            for error in outcome.errors:
                print(f"- {error}", file=sys.stderr)
    if result.status in {"no_tables", "completed"}:
        return EXIT_OK
    if result.tables_succeeded == 0:
        return EXIT_RUNTIME
    return EXIT_PARTIAL


def _discover_run(args: argparse.Namespace) -> int:
    registry = PromptRegistry.load(args.prompts)
    if args.dry_run:
        evidence = load_ddl_repository(args.repo)
        prompt = build_discovery_prompt(
            evidence, registry, include_ddl=not args.no_ddl
        )
        payload = _discovery_dry_run_payload(args, evidence, prompt)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"DDL Repository: {args.repo}")
            print(f"Snapshot: {evidence.snapshot_id}")
            print(
                f"Database: {evidence.database.database} "
                f"({evidence.database.platform})"
            )
            print(f"Objects considered: {prompt.object_count}")
            print(f"DDL included: {prompt.ddl_included}")
            print(f"Prompt version: {prompt.prompt_version}")
            print(f"Prompt SHA-256: {prompt.prompt_sha256}")
            print(f"Evidence SHA-256: {prompt.evidence_sha256}")
            print(f"Proposals: {args.proposals}")
        if prompt.warnings:
            print(f"Warnings: {len(prompt.warnings)}", file=sys.stderr)
            for warning in prompt.warnings:
                print(f"- {warning}", file=sys.stderr)
        if args.show_prompt:
            for message in prompt.messages:
                print(f"--- {message.type} ---", file=sys.stderr)
                print(str(message.content), file=sys.stderr)
        return EXIT_OK

    config = _resolve(args)
    llm = build_llm_client(config)
    tracer = build_tracer(config)
    graph = build_discovery_graph(
        llm,
        tracer,
        registry=registry,
        proposals_root=args.proposals,
        run_config=DiscoveryRunConfig(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        ),
    )
    try:
        result: dict[str, Any] = graph.invoke(
            {
                "ddl_repository": str(args.repo),
                "include_ddl": not args.no_ddl,
            }
        )
    finally:
        tracer.flush()
    return _discover_run_report(result, args)


def _discover_run_report(
    result: dict[str, Any], args: argparse.Namespace
) -> int:
    status = str(result.get("status", "failed"))
    evidence = result.get("evidence")
    prompt = result.get("prompt")
    proposals = result.get("proposals")
    write_result = result.get("write_result")
    warnings = tuple(result.get("warnings", ()))
    errors = tuple(result.get("validation_errors", ()))
    error = result.get("error")
    if proposals is not None:
        counts = proposals.counts
    elif write_result is not None:
        counts = write_result.counts
    else:
        counts = {"concepts": 0, "mappings": 0, "relationships": 0}
    payload = {
        "status": status,
        "ddl_repository": str(args.repo),
        "snapshot_id": evidence.snapshot_id if evidence is not None else None,
        "database": (
            {
                "platform": evidence.database.platform,
                "name": evidence.database.database,
            }
            if evidence is not None
            else None
        ),
        "objects_considered": (
            prompt.object_count
            if prompt is not None
            else (evidence.object_count if evidence is not None else 0)
        ),
        "prompt_version": prompt.prompt_version if prompt is not None else None,
        "prompt_sha256": prompt.prompt_sha256 if prompt is not None else None,
        "validation": "passed" if status != "failed" else "failed",
        "proposals_repository": str(args.proposals),
        "concepts": counts["concepts"],
        "mappings": counts["mappings"],
        "relationships": counts["relationships"],
        "written": list(write_result.written) if write_result is not None else [],
        "unchanged": (
            list(write_result.unchanged) if write_result is not None else []
        ),
        "conflicts": (
            list(write_result.conflicts) if write_result is not None else []
        ),
        "warnings": list(warnings),
        "errors": list(errors),
        "error": error,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"DDL Repository: {args.repo}")
        if evidence is not None:
            print(f"Snapshot: {evidence.snapshot_id}")
            print(
                f"Database: {evidence.database.database} "
                f"({evidence.database.platform})"
            )
        print(f"Objects considered: {payload['objects_considered']}")
        if prompt is not None:
            print(f"Prompt version: {prompt.prompt_version}")
            print(f"Prompt SHA-256: {prompt.prompt_sha256}")
        print(f"Status: {status}")
        print(f"Concepts: {counts['concepts']}")
        print(f"Mappings: {counts['mappings']}")
        print(f"Relationships: {counts['relationships']}")
        print(f"Validation: {payload['validation']}")
        if status == "no_proposals":
            print("No proposals produced.")
        else:
            print(f"Proposals: {args.proposals}")
            if write_result is not None:
                print(
                    f"Written: {len(write_result.written)}, "
                    f"unchanged: {len(write_result.unchanged)}, "
                    f"conflicts: {len(write_result.conflicts)}"
                )
    if warnings:
        print(f"Warnings: {len(warnings)}", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)
    if status == "failed":
        print(f"Discovery failed: {error}", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return EXIT_RUNTIME
    if status == "conflicts":
        return EXIT_PARTIAL
    return EXIT_OK


def _discovery_dry_run_payload(
    args: argparse.Namespace, evidence: Any, prompt: Any
) -> dict[str, Any]:
    return {
        "status": "dry_run",
        "ddl_repository": str(args.repo),
        "snapshot_id": evidence.snapshot_id,
        "database": {
            "platform": evidence.database.platform,
            "name": evidence.database.database,
        },
        "objects_considered": prompt.object_count,
        "ddl_included": prompt.ddl_included,
        "prompt_version": prompt.prompt_version,
        "prompt_sha256": prompt.prompt_sha256,
        "evidence_sha256": prompt.evidence_sha256,
        "warnings": list(prompt.warnings),
        "proposals_repository": str(args.proposals),
    }


def _discover_validate(args: argparse.Namespace) -> int:
    validation: ProposalRepositoryValidation = validate_proposal_repository(
        args.repo, ddl_repository=args.ddl_repo
    )
    payload = {
        "valid": validation.valid,
        "empty": validation.empty,
        "counts": validation.counts,
        "errors": list(validation.errors),
        "manifest": (
            validation.manifest.model_dump(mode="json", by_alias=True)
            if validation.manifest is not None
            else None
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif validation.empty:
        print("Proposal repository is empty (no proposals).")
    elif validation.valid:
        print(
            "Proposal repository valid: yes "
            f"(concepts={validation.counts.get('concepts', 0)}, "
            f"mappings={validation.counts.get('mappings', 0)}, "
            f"relationships={validation.counts.get('relationships', 0)})"
        )
    else:
        print("Proposal repository valid: no", file=sys.stderr)
        for error in validation.errors:
            print(f"- {error}", file=sys.stderr)
    return EXIT_OK if validation.valid else EXIT_RUNTIME


def check_ollama_available(base_url: str, timeout: float) -> bool:
    """Return whether the Ollama service responds, without calling a model."""

    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(getattr(response, "status", 0)) < 300
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError):
        return False


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten(nested, name))
    else:
        rows.append((prefix, value))
    return rows


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
