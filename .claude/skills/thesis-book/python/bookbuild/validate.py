"""Cross-file checks: plan, front matter, citations and verbatim quotations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import ContentError
from .extract import Extractor, SourceText
from .manifest import DocumentEntry, Manifest
from .markdown import Block, Chapter, load_chapter
from .plan import ChapterPlan, Plan, load_frontmatter, validate_frontmatter
from .settings import Settings
from .typography import apply as apply_typography
from .typography import normalise_for_match, residual_issues, split_elision


def _fail(chapter: Chapter, block: Block, message: str) -> None:
    raise ContentError(message, file=chapter.path, line=block.line)


def _source_haystack(texts: dict[str, SourceText], doc_id: str) -> str:
    source = texts.get(doc_id)
    if source is None:
        return ""
    return normalise_for_match("\n".join(source.paragraphs))


def quote_in_source(quote: str, haystack: str) -> bool:
    """True when every elision-separated segment occurs in order."""

    position = 0
    for segment in split_elision(quote):
        needle = normalise_for_match(segment)
        if not needle:
            continue
        found = haystack.find(needle, position)
        if found < 0:
            return False
        position = found + len(needle)
    return True


def validate_chapter(
    chapter: Chapter,
    planned: ChapterPlan,
    manifest: Manifest,
    texts: dict[str, SourceText],
    settings: Settings,
) -> list[str]:
    """Validate one chapter file; return warnings, raise on errors."""

    warnings: list[str] = []
    if chapter.number != planned.number:
        raise ContentError(
            f"chapter number {chapter.number} does not match the plan ({planned.number})",
            file=chapter.path,
        )
    if chapter.title != planned.title:
        raise ContentError(
            f"chapter title {chapter.title!r} does not match the plan "
            f"({planned.title!r})",
            file=chapter.path,
        )
    declared = set(chapter.sources)
    extra = declared - set(planned.sources)
    if extra:
        raise ContentError(
            f"chapter lists source(s) not in the plan: {', '.join(sorted(extra))}",
            file=chapter.path,
        )

    for block in chapter.blocks:
        for doc_id in block.citations:
            if doc_id not in declared:
                _fail(
                    chapter,
                    block,
                    f"citation [{doc_id}] is not listed in the chapter's sources",
                )
            try:
                manifest.lookup(doc_id)
            except ContentError:
                _fail(chapter, block, f"citation [{doc_id}] is not in the corpus manifest")
        if block.kind == "quote":
            if block.source not in declared:
                _fail(
                    chapter,
                    block,
                    f"quote source {block.source!r} is not listed in the chapter's sources",
                )
            entry = manifest.lookup(block.source)
            if not quote_in_source(
                block.text, _source_haystack(texts, entry.id)
            ):
                excerpt = block.text if len(block.text) <= 90 else block.text[:87] + "..."
                _fail(
                    chapter,
                    block,
                    f"quote not found verbatim in {entry.id}: “{excerpt}”",
                )
            if len(block.text.split()) < 4:
                warnings.append(
                    f"{chapter.path.name}: line {block.line}: very short quotation"
                )

    used_ids = set()
    for block in chapter.blocks:
        used_ids.update(block.citations)
        if block.kind == "quote" and block.source:
            used_ids.add(block.source)
    unused = declared - used_ids
    if unused:
        warnings.append(
            f"{chapter.path.name}: source(s) declared but not cited: "
            f"{', '.join(sorted(unused))}"
        )

    for block in chapter.blocks:
        if block.kind == "quote":
            rendered = apply_typography(block.text, settings.typography)
        else:
            rendered = apply_typography(block.text, settings.typography)
        issues = residual_issues(rendered)
        if issues:
            warnings.append(
                f"{chapter.path.name}: line {block.line}: "
                f"{'; '.join(sorted(set(issues)))}"
            )
    return warnings


@dataclass
class ChapterResult:
    number: int
    slug: str
    title: str
    path: str
    authored: bool
    words: int = 0
    sources: list[str] = field(default_factory=list)
    used_sources: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)


def load_source_texts(
    settings: Settings,
    manifest: Manifest,
    extractor: Extractor,
    doc_ids: set[str],
    *,
    refresh: bool = False,
) -> dict[str, SourceText]:
    texts: dict[str, SourceText] = {}
    for doc_id in sorted(doc_ids):
        entry: DocumentEntry = manifest.lookup(doc_id)
        texts[doc_id] = extractor.load_or_extract(
            entry, entry.path(settings.corpus_dir), refresh=refresh
        )
    return texts


@dataclass
class BookReport:
    chapters: list[ChapterResult]
    missing: list[int]
    warnings: list[str]
    used_sources: list[str]
    frontmatter_complete: bool

    def as_dict(self) -> dict:
        return {
            "chapters": [asdict(chapter) for chapter in self.chapters],
            "missing": self.missing,
            "warnings": self.warnings,
            "used_sources": self.used_sources,
            "frontmatter_complete": self.frontmatter_complete,
            "next_chapter": self.next_chapter,
            "ready_for_all": not self.missing,
        }

    @property
    def next_chapter(self) -> int | None:
        return self.missing[0] if self.missing else None


def _load_frontmatter_safely(settings: Settings) -> tuple[dict | None, bool]:
    try:
        raw = load_frontmatter(settings.frontmatter_path)
        validate_frontmatter(raw, settings)
        return raw, True
    except ContentError:
        try:
            return load_frontmatter(settings.frontmatter_path), False
        except ContentError:
            return None, False


def validate_book(
    settings: Settings,
    plan: Plan,
    manifest: Manifest,
    extractor: Extractor,
    *,
    require_all: bool = False,
    require_upto: int | None = None,
    require_frontmatter: bool = True,
    refresh: bool = False,
) -> BookReport:
    frontmatter, frontmatter_ok = _load_frontmatter_safely(settings)
    if frontmatter is None and require_frontmatter:
        raise ContentError(
            "front matter not found; run 'init' and author it before rendering",
            file=settings.frontmatter_path,
        )

    for chapter in plan.chapters:
        for doc_id in chapter.sources:
            manifest.lookup(doc_id)

    needed = {doc_id for chapter in plan.chapters for doc_id in chapter.sources}
    texts = load_source_texts(settings, manifest, extractor, needed, refresh=refresh)

    results: list[ChapterResult] = []
    warnings: list[str] = []
    used_sources: set[str] = set()
    missing: list[int] = []
    for planned in plan.chapters:
        path = planned.path(settings)
        authored = path.is_file()
        missing_sources = [
            doc_id
            for doc_id in planned.sources
            if not manifest.lookup(doc_id).path(settings.corpus_dir).is_file()
        ]
        result = ChapterResult(
            number=planned.number,
            slug=planned.slug,
            title=planned.title,
            path=str(path),
            authored=authored,
            sources=list(planned.sources),
            missing_sources=missing_sources,
        )
        if authored:
            chapter = load_chapter(path)
            warnings.extend(
                validate_chapter(chapter, planned, manifest, texts, settings)
            )
            result.words = chapter.words
            used = set()
            for block in chapter.blocks:
                used.update(block.citations)
                if block.kind == "quote" and block.source:
                    used.add(block.source)
            result.used_sources = sorted(used)
            used_sources.update(used)
        else:
            missing.append(planned.number)
        results.append(result)

    if require_upto is not None:
        blocked = [number for number in missing if number <= require_upto]
        if blocked:
            raise ContentError(
                "render requires every earlier chapter; missing: "
                + ", ".join(str(number) for number in sorted(blocked)),
                file=settings.plan_path,
            )
    if require_all and missing:
        raise ContentError(
            "the full build needs every planned chapter; missing: "
            + ", ".join(str(number) for number in missing),
            file=settings.plan_path,
        )
    if require_frontmatter and not frontmatter_ok:
        raise ContentError(
            "front matter is incomplete; abstracts, keywords and the declaration "
            "must be authored before rendering",
            file=settings.frontmatter_path,
        )

    return BookReport(
        chapters=results,
        missing=missing,
        warnings=warnings,
        used_sources=sorted(used_sources),
        frontmatter_complete=frontmatter_ok,
    )
