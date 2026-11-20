"""Command-line entry point for the Universal Database Access demo.

Exit codes: 0 candidate written, 1 proposal rejected by validation,
2 configuration or model-output error.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from uda.fixtures import load_demo_schema
from uda.models import TableSchema
from uda.provider import ProviderConfigurationError, build_deepseek_model
from uda.sqlserver import (
    SqlServerError,
    engine_from_env,
    inspect_table,
    parse_table_reference,
)
from uda.storage import CandidateStorageError, save_candidate
from uda.workflow import run_workflow

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_ERROR = 2

DEFAULT_OUT = Path("out/candidate.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uda",
        description="Propose one semantic candidate for a table and save it for review.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose",
        help="propose a candidate for the bundled demo schema",
    )
    propose.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"candidate JSON path (default: {DEFAULT_OUT})",
    )
    propose.add_argument(
        "--response-file",
        type=Path,
        help="use this local text file as the LLM response (offline mode)",
    )
    propose.add_argument(
        "--sqlserver",
        metavar="TABLE",
        help=(
            "read metadata for TABLE (schema.table) from SQL Server; "
            "requires UDA_SQLSERVER_URL"
        ),
    )
    return parser


def _make_model(response_file: Path | None) -> BaseChatModel:
    if response_file is None:
        return build_deepseek_model()

    text = response_file.read_text(encoding="utf-8")
    return FakeListChatModel(responses=[text])


def _load_schema(sqlserver_table: str | None) -> TableSchema:
    if sqlserver_table is None:
        return load_demo_schema()

    schema_name, table_name = parse_table_reference(sqlserver_table)
    return inspect_table(engine_from_env(), table_name, schema_name)


def _propose(
    out: Path,
    response_file: Path | None,
    sqlserver_table: str | None,
) -> int:
    try:
        model = _make_model(response_file)
        schema = _load_schema(sqlserver_table)
    except (ProviderConfigurationError, SqlServerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: cannot read response file: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        result = run_workflow(schema, model)
    except Exception as exc:  # CLI boundary: keep provider details out of output
        print(f"error: model request failed ({exc.__class__.__name__})", file=sys.stderr)
        return EXIT_ERROR

    if result.issues:
        print("proposal rejected:", file=sys.stderr)
        for issue in result.issues:
            print(f"- {issue.code}: {issue.message}", file=sys.stderr)
        return EXIT_REJECTED

    if result.candidate is None:
        print(f"error: {result.error}", file=sys.stderr)
        return EXIT_ERROR

    try:
        saved = save_candidate(out, schema, result.candidate)
    except (CandidateStorageError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"wrote {saved} ({result.candidate.status})")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "propose":
        return _propose(args.out, args.response_file, args.sqlserver)
    return EXIT_ERROR
