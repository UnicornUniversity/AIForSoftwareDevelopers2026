"""The book plan (``book.json``) and the front-matter file (``frontmatter.json``).

The plan is the table of contents the author works from.  Chapter files live
beside it in ``chapters/NN-slug.md``.  Both files are ordinary JSON and are
meant to be edited by hand as well as written by ``init``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ContentError
from .manifest import Manifest
from .settings import Settings

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ChapterPlan:
    number: int
    slug: str
    title: str
    sources: tuple[str, ...]

    def path(self, settings: Settings) -> Path:
        return settings.chapters_dir / f"{self.number:02d}-{self.slug}.md"


@dataclass
class Plan:
    path: Path
    title: str
    chapters: list[ChapterPlan]

    def by_number(self, number: int) -> ChapterPlan:
        for chapter in self.chapters:
            if chapter.number == number:
                return chapter
        raise ContentError(f"no chapter {number} in the plan", file=self.path)

    @property
    def numbers(self) -> list[int]:
        return [chapter.number for chapter in self.chapters]


def _fail(path: Path, message: str) -> None:
    raise ContentError(message, file=path)


def load_plan(path: str | Path) -> Plan:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContentError("book plan not found; run the 'init' command first", file=path) from None
    except OSError as exc:
        raise ContentError(f"cannot read book plan: {exc}", file=path) from None
    except json.JSONDecodeError as exc:
        raise ContentError(exc.msg, file=path, line=exc.lineno) from None

    if not isinstance(raw, dict):
        _fail(path, "book plan must be a JSON object")
    unknown = set(raw) - {"title", "chapters"}
    if unknown:
        _fail(path, f"unknown key(s): {', '.join(sorted(unknown))}")
    if not isinstance(raw.get("title"), str) or not raw["title"].strip():
        _fail(path, "'title' must be a non-empty string")
    if not isinstance(raw.get("chapters"), list) or not raw["chapters"]:
        _fail(path, "'chapters' must be a non-empty list")

    chapters: list[ChapterPlan] = []
    slugs: set[str] = set()
    for index, item in enumerate(raw["chapters"]):
        where = f"chapters[{index}]"
        if not isinstance(item, dict):
            _fail(path, f"{where} must be an object")
        unknown = set(item) - {"number", "slug", "title", "sources"}
        if unknown:
            _fail(path, f"{where}: unknown key(s): {', '.join(sorted(unknown))}")
        for key in ("number", "slug", "title", "sources"):
            if key not in item:
                _fail(path, f"{where}: missing required key {key!r}")
        number = item["number"]
        if isinstance(number, bool) or not isinstance(number, int):
            _fail(path, f"{where}.number must be an integer")
        if number != index + 1:
            _fail(
                path,
                f"{where}.number must be {index + 1}; chapter numbers are contiguous from 1",
            )
        slug = item["slug"]
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            _fail(path, f"{where}.slug must be lowercase words joined by hyphens")
        if slug in slugs:
            _fail(path, f"{where}.slug {slug!r} is used twice")
        slugs.add(slug)
        title = item["title"]
        if not isinstance(title, str) or not title.strip():
            _fail(path, f"{where}.title must be a non-empty string")
        sources = item["sources"]
        if not isinstance(sources, list) or not sources:
            _fail(path, f"{where}.sources must be a non-empty list of document ids")
        clean_sources: list[str] = []
        for source in sources:
            if not isinstance(source, str) or not re.fullmatch(r"doc\d+", source):
                _fail(path, f"{where}.sources contains an invalid document id")
            if source in clean_sources:
                _fail(path, f"{where}.sources lists {source} twice")
            clean_sources.append(source)
        chapters.append(
            ChapterPlan(
                number=number,
                slug=slug,
                title=title.strip(),
                sources=tuple(clean_sources),
            )
        )

    return Plan(path=path, title=raw["title"], chapters=chapters)


def save_plan(plan: Plan) -> None:
    data = {
        "title": plan.title,
        "chapters": [
            {
                "number": chapter.number,
                "slug": chapter.slug,
                "title": chapter.title,
                "sources": list(chapter.sources),
            }
            for chapter in plan.chapters
        ],
    }
    _write_json(plan.path, data)


def starter_plan(manifest: Manifest, title: str, path: Path) -> Plan:
    """Group the corpus by sub-topic, one starter chapter per group."""

    groups = manifest.by_sub_topic()
    chapters: list[ChapterPlan] = []
    for number, (sub_topic, entries) in enumerate(groups.items(), start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", sub_topic.casefold()).strip("-") or f"chapter-{number}"
        chapters.append(
            ChapterPlan(
                number=number,
                slug=slug,
                title=sub_topic[:1].upper() + sub_topic[1:],
                sources=tuple(sorted(entry.id for entry in entries)),
            )
        )
    return Plan(path=path, title=title, chapters=chapters)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


_ABSTRACT_KEYS = {"text", "keywords"}


def load_frontmatter(path: str | Path) -> dict:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContentError("front matter not found; run 'init' first", file=path) from None
    except OSError as exc:
        raise ContentError(f"cannot read front matter: {exc}", file=path) from None
    except json.JSONDecodeError as exc:
        raise ContentError(exc.msg, file=path, line=exc.lineno) from None
    if not isinstance(raw, dict):
        _fail(path, "front matter must be a JSON object")
    return raw


def starter_frontmatter(path: Path) -> dict:
    data = {
        "dedication": "",
        "declaration": (
            "I declare that this thesis is my own work, that every quotation is "
            "reproduced verbatim from the source named beside it, and that all "
            "other sources are acknowledged in the references."
        ),
        "abstract": {"text": "", "keywords": []},
        "anotace": {"text": "", "keywords": []},
    }
    _write_json(path, data)
    return data


def validate_frontmatter(raw: dict, settings: Settings) -> None:
    """Raise :class:`ContentError` unless every enabled section has text."""

    path = settings.frontmatter_path
    allowed = {"dedication", "declaration", "abstract", "anotace"}
    unknown = set(raw) - allowed
    if unknown:
        _fail(path, f"unknown key(s): {', '.join(sorted(unknown))}")

    if settings.get("front_matter.declaration"):
        declaration = raw.get("declaration")
        if not isinstance(declaration, str) or not declaration.strip():
            _fail(path, "'declaration' must be a non-empty string")

    if settings.get("front_matter.dedication"):
        dedication = raw.get("dedication", "")
        if not isinstance(dedication, str):
            _fail(path, "'dedication' must be a string")

    for key in ("abstract", "anotace"):
        if not settings.get(f"front_matter.{key}.enabled"):
            continue
        section = raw.get(key)
        if not isinstance(section, dict):
            _fail(path, f"{key!r} must be an object with 'text' and 'keywords'")
        unknown = set(section) - _ABSTRACT_KEYS
        if unknown:
            _fail(path, f"{key}: unknown key(s): {', '.join(sorted(unknown))}")
        text = section.get("text")
        if not isinstance(text, str) or not text.strip():
            _fail(path, f"{key}.text must be a non-empty string")
        keywords = section.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(isinstance(word, str) and word.strip() for word in keywords)
        ):
            _fail(path, f"{key}.keywords must be a non-empty list of words")


def frontmatter_complete(raw: dict | None, settings: Settings) -> bool:
    if raw is None:
        return False
    try:
        validate_frontmatter(raw, settings)
    except ContentError:
        return False
    return True
