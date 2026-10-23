"""Command-line interface for the corpus-to-book tool.

Every command prints one JSON object on stdout and leaves human-readable
diagnostics on stderr, so a skill (or a person) can parse the result without
scraping prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import EXIT_USAGE, BookError, ContentError
from .extract import Extractor
from .manifest import Manifest, load_manifest, resolve_manifest_path
from .markdown import load_chapter
from .plan import (
    Plan,
    load_frontmatter,
    load_plan,
    save_plan,
    starter_frontmatter,
    starter_plan,
)
from .render import render_book
from .settings import Settings, load_settings
from .validate import validate_book


def _emit(data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - only when stdout has been replaced by a StringIO
        sys.stdout.write(text)


def _write(text: str) -> None:
    try:
        print(text, file=sys.stderr)
    except UnicodeEncodeError:  # pragma: no cover - rare legacy consoles
        print(text.encode("ascii", "replace").decode("ascii"), file=sys.stderr)


def _context(
    args: argparse.Namespace,
) -> tuple[Settings, Manifest, Extractor, Path]:
    settings = load_settings(args.settings)
    corpus_dir, manifest_path = resolve_manifest_path(
        settings, corpus_override=args.corpus, manifest_override=args.manifest
    )
    manifest = load_manifest(manifest_path)
    extractor = Extractor(settings.cache_dir)
    return settings, manifest, extractor, corpus_dir


def _enabled_formats(settings: Settings) -> set[str]:
    return set(settings.raw["corpus"]["formats"])


def _extract_all(
    settings: Settings,
    manifest: Manifest,
    extractor: Extractor,
    corpus_dir: Path,
    *,
    refresh: bool,
) -> list[dict]:
    enabled = _enabled_formats(settings)
    report: list[dict] = []
    for entry in manifest.documents:
        if entry.format not in enabled:
            report.append(
                {
                    "id": entry.id,
                    "format": entry.format,
                    "skipped": "format disabled in settings",
                }
            )
            continue
        source = extractor.load_or_extract(
            entry, entry.path(corpus_dir), refresh=refresh
        )
        report.append(
            {
                "id": entry.id,
                "format": entry.format,
                "title": entry.title,
                "blocks": len(source.blocks),
                "words": source.words,
                "body_words": source.body_words,
                "manifest_body_words": entry.body_word_count,
            }
        )
    return report


def cmd_init(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, corpus_dir = _context(args)
    enabled = _enabled_formats(settings)

    extracted = []
    for entry in manifest.documents:
        if entry.format not in enabled:
            continue
        source = extractor.load_or_extract(
            entry, entry.path(corpus_dir), refresh=False
        )
        extracted.append({"id": entry.id, "words": source.words})

    plan_path = settings.plan_path
    frontmatter_path = settings.frontmatter_path
    if plan_path.exists() and not args.force:
        raise ContentError(
            "book plan already exists; pass --force to replace it",
            file=plan_path,
        )
    if frontmatter_path.exists() and not args.force:
        raise ContentError(
            "front matter already exists; pass --force to replace it",
            file=frontmatter_path,
        )

    plan = starter_plan(manifest, settings.raw["book"]["title"], plan_path)
    save_plan(plan)
    starter_frontmatter(frontmatter_path)
    settings.chapters_dir.mkdir(parents=True, exist_ok=True)

    _write(f"wrote {plan_path} and {frontmatter_path}")
    return {
        "plan": str(plan_path),
        "frontmatter": str(frontmatter_path),
        "chapters": [
            {
                "number": chapter.number,
                "slug": chapter.slug,
                "title": chapter.title,
                "sources": list(chapter.sources),
                "path": str(chapter.path(settings)),
            }
            for chapter in plan.chapters
        ],
        "sources": extracted,
    }


def cmd_extract(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, corpus_dir = _context(args)
    report = _extract_all(
        settings, manifest, extractor, corpus_dir, refresh=args.refresh
    )
    return {
        "corpus": str(settings.corpus_dir),
        "manifest": str(manifest.source),
        "sources": report,
    }


def cmd_status(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, _ = _context(args)
    plan = load_plan(settings.plan_path)
    report = validate_book(
        settings,
        plan,
        manifest,
        extractor,
        require_frontmatter=False,
        refresh=False,
    )
    data = report.as_dict()
    data["plan"] = str(plan.path)
    data["output"] = str(settings.output_path)
    data["total_words"] = sum(chapter.words for chapter in report.chapters)
    data["output_exists"] = settings.output_path.is_file()
    _write(
        f"{len(plan.chapters)} chapters planned, "
        f"{len(plan.chapters) - len(report.missing)} authored"
    )
    return data


def cmd_context(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, corpus_dir = _context(args)
    plan = load_plan(settings.plan_path)
    planned = plan.by_number(args.chapter)
    sources: dict[str, dict] = {}
    blocks: list[dict] = []
    for doc_id in planned.sources:
        entry = manifest.lookup(doc_id)
        source = extractor.load_or_extract(entry, entry.path(corpus_dir), refresh=False)
        sources[doc_id] = {
            "title": entry.title,
            "authors": list(entry.authors),
            "year": entry.year,
            "venue": entry.venue,
            "document_type": entry.document_type,
            "sub_topic": entry.sub_topic,
            "format": entry.format,
            "word_count": entry.word_count,
            "has_contradiction": entry.has_contradiction,
            "citation": entry.citation,
            "blocks": [
                {"kind": block["kind"], "text": block["text"]}
                for block in source.blocks
            ],
        }
        for block in source.blocks:
            blocks.append(
                {"id": doc_id, "kind": block["kind"], "text": block["text"]}
            )
    return {
        "chapter": {
            "number": planned.number,
            "slug": planned.slug,
            "title": planned.title,
            "sources": list(planned.sources),
            "path": str(planned.path(settings)),
        },
        "sources": sources,
        "blocks": blocks,
        "note": (
            "Quote text by copying complete sentences from 'blocks'. Every quote "
            "must end with a line '— docNN' naming the source it came from."
        ),
    }


def _load_chapters(settings: Settings, plan: Plan, numbers: list[int]):
    chapters = []
    for number in numbers:
        planned = plan.by_number(number)
        chapters.append(load_chapter(planned.path(settings)))
    return chapters


def cmd_render(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, _ = _context(args)
    plan = load_plan(settings.plan_path)
    if args.all:
        report = validate_book(
            settings,
            plan,
            manifest,
            extractor,
            require_all=True,
            require_frontmatter=True,
        )
        numbers = [chapter.number for chapter in plan.chapters]
    else:
        if args.chapter is None:
            raise BookError("render needs --chapter N or --all", exit_code=EXIT_USAGE)
        if args.chapter < 1 or args.chapter > len(plan.chapters):
            raise BookError(
                f"chapter must be between 1 and {len(plan.chapters)}",
                exit_code=EXIT_USAGE,
            )
        report = validate_book(
            settings,
            plan,
            manifest,
            extractor,
            require_upto=args.chapter,
            require_frontmatter=True,
        )
        numbers = list(range(1, args.chapter + 1))

    frontmatter = load_frontmatter(settings.frontmatter_path)
    chapters = _load_chapters(settings, plan, numbers)
    output = render_book(settings, plan, manifest, chapters, frontmatter)
    _write(f"wrote {output}")
    return {
        "output": str(output),
        "chapters": numbers,
        "words": sum(chapter.words for chapter in chapters),
        "used_sources": report.used_sources,
        "warnings": report.warnings,
    }


def cmd_validate(args: argparse.Namespace) -> dict:
    settings, manifest, extractor, _ = _context(args)
    plan = load_plan(settings.plan_path)
    report = validate_book(
        settings,
        plan,
        manifest,
        extractor,
        require_all=args.all,
        require_frontmatter=True,
    )
    return report.as_dict()


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--settings", required=True, help="path to settings.json")
    common.add_argument("--corpus", help="override the corpus folder")
    common.add_argument("--manifest", help="override the manifest file")

    parser = argparse.ArgumentParser(
        prog="build_book.py",
        description="Build an authored Word book from a document corpus.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", parents=[common], help="create the plan and front matter")
    init.add_argument("--force", action="store_true", help="replace existing files")
    init.set_defaults(handler=cmd_init)

    extract = subparsers.add_parser("extract", parents=[common], help="refresh the text cache")
    extract.add_argument("--refresh", action="store_true", help="ignore cached text")
    extract.set_defaults(handler=cmd_extract)

    status = subparsers.add_parser("status", parents=[common], help="show chapter progress")
    status.set_defaults(handler=cmd_status)

    context = subparsers.add_parser(
        "context", parents=[common], help="print source text for one chapter"
    )
    context.add_argument("--chapter", type=int, required=True)
    context.set_defaults(handler=cmd_context)

    render = subparsers.add_parser("render", parents=[common], help="build the Word document")
    render.add_argument("--chapter", type=int)
    render.add_argument("--all", action="store_true")
    render.set_defaults(handler=cmd_render)

    validate = subparsers.add_parser(
        "validate", parents=[common], help="check every file without rendering"
    )
    validate.add_argument("--all", action="store_true")
    validate.set_defaults(handler=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except BookError as exc:
        _write(exc.formatted)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        _write("interrupted")
        return 130
    _emit(result)
    return 0
