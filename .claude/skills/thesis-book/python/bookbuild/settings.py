"""Load and strictly validate the JSON settings file.

The settings file is the single description of how the Word document looks.
Validation is deliberately unforgiving: an unknown key is a typo the user wants
to hear about, not something to ignore silently.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import SettingsError

SCHEMA_VERSION = 1

_PAGE_SIZES = {"A4", "Letter"}
_ALIGNMENTS = {"left", "center", "right", "justify"}
_QUOTE_STYLES = {"english_smart"}
_PUNCTUATION = {"outside", "inside"}
_DASH_STYLES = {"em", "en", "hyphen"}
_PAGE_NUMBER_POSITIONS = {"bottom_center", "bottom_right"}
_HEADER_TEXTS = {"book_title", "chapter_title"}
_REFERENCE_STYLES = {"harvard", "apa"}
_REFERENCE_SCOPES = {"used", "all"}
_REFERENCE_SORTS = {"id", "title"}
_CAPTION_POSITIONS = {"above", "below"}
_CITATION_STYLES = {"author_date", "id"}
_FILE_FORMATS = {"docx", "pdf"}


def _fail(path: str, message: str) -> None:
    raise SettingsError(message, key=path)


def _obj(value: Any, path: str, required: tuple[str, ...], allowed: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(path, f"unknown key(s): {', '.join(unknown)}")
    missing = [key for key in required if key not in value]
    if missing:
        _fail(path, f"missing required key(s): {', '.join(missing)}")
    return value


def _str(
    value: Any,
    path: str,
    *,
    choices: set[str] | None = None,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    if not allow_empty and not value.strip():
        _fail(path, "must not be empty")
    if choices is not None and value not in choices:
        _fail(path, f"must be one of: {', '.join(sorted(choices))}")
    return value


def _num(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    integer: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    if integer and int(value) != value:
        _fail(path, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(path, f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        _fail(path, f"must be at most {maximum}")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "must be true or false")
    return value


def _color(value: Any, path: str) -> str:
    text = _str(value, path)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        _fail(path, "must be a six-digit hex colour such as 000000")
    return text.upper()


def _text(value: Any, path: str, *, allow_empty: bool = False) -> str:
    return _str(value, path, allow_empty=allow_empty)


@dataclass(frozen=True)
class Settings:
    """Validated settings plus the resolved paths that hang off them."""

    raw: dict
    path: Path

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def typography(self) -> dict:
        return self.raw["typography"]

    def resolve(self, relative: str) -> Path:
        return (self.directory / relative).resolve()

    @property
    def plan_path(self) -> Path:
        return self.resolve(self.raw["book"]["plan"])

    @property
    def frontmatter_path(self) -> Path:
        return self.resolve(self.raw["book"]["frontmatter"])

    @property
    def output_path(self) -> Path:
        return self.resolve(self.raw["book"]["output"])

    @property
    def corpus_dir(self) -> Path:
        return self.resolve(self.raw["corpus"]["folder"])

    @property
    def manifest_path(self) -> Path:
        return self.resolve(self.raw["corpus"]["manifest"])

    @property
    def book_dir(self) -> Path:
        return self.plan_path.parent

    @property
    def chapters_dir(self) -> Path:
        return self.book_dir / "chapters"

    @property
    def cache_dir(self) -> Path:
        return self.book_dir / ".work" / "sources"

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_settings(path: str | Path) -> Settings:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SettingsError("settings file not found", file=path) from None
    except OSError as exc:
        raise SettingsError(f"cannot read settings file: {exc}", file=path) from None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(exc.msg, file=path, line=exc.lineno) from None

    _validate(raw, path)
    return Settings(raw=raw, path=path)


def _validate(raw: Any, path: Path) -> None:
    _obj(
        raw,
        "settings",
        required=(
            "schema_version",
            "book",
            "page",
            "typography",
            "front_matter",
            "body",
            "corpus",
            "citations",
        ),
        allowed=(
            "schema_version",
            "book",
            "page",
            "typography",
            "front_matter",
            "body",
            "corpus",
            "citations",
        ),
    )
    if raw["schema_version"] != SCHEMA_VERSION:
        _fail("schema_version", f"must be {SCHEMA_VERSION}")
    try:
        _validate_book(raw["book"])
        _validate_page(raw["page"])
        _validate_typography(raw["typography"])
        _validate_front_matter(raw["front_matter"])
        _validate_body(raw["body"])
        _validate_corpus(raw["corpus"])
        _validate_citations(raw["citations"])
    except SettingsError as exc:
        # Every nested validator raises with only its dotted key; attach the file.
        raise SettingsError(exc.message, file=path, key=exc.key) from None


def _validate_book(book: Any) -> None:
    _obj(
        book,
        "book",
        required=("title", "author", "date", "language", "plan", "frontmatter", "output"),
        allowed=(
            "title",
            "subtitle",
            "author",
            "institution",
            "date",
            "language",
            "plan",
            "frontmatter",
            "output",
        ),
    )
    _text(book["title"], "book.title")
    _text(book.get("subtitle", ""), "book.subtitle", allow_empty=True)
    _text(book["author"], "book.author")
    _text(book.get("institution", ""), "book.institution", allow_empty=True)
    _text(book["date"], "book.date")
    _text(book["language"], "book.language")
    for key in ("plan", "frontmatter", "output"):
        _text(book[key], f"book.{key}")


def _validate_page(page: Any) -> None:
    _obj(page, "page", required=("size", "margins_cm"), allowed=("size", "margins_cm"))
    _str(page["size"], "page.size", choices=_PAGE_SIZES)
    margins = _obj(
        page["margins_cm"],
        "page.margins_cm",
        required=("top", "bottom", "left", "right"),
        allowed=("top", "bottom", "left", "right"),
    )
    for side, value in margins.items():
        _num(value, f"page.margins_cm.{side}", minimum=0, maximum=10)


def _validate_typography(typography: Any) -> None:
    _obj(
        typography,
        "typography",
        required=(
            "body",
            "headings",
            "front_titles",
            "quote",
            "provenance",
            "quotes",
            "dashes",
            "nbsp_for_single_letters",
        ),
        allowed=(
            "body",
            "headings",
            "front_titles",
            "quote",
            "provenance",
            "quotes",
            "dashes",
            "nbsp_for_single_letters",
        ),
    )
    body = _obj(
        typography["body"],
        "typography.body",
        required=(
            "font",
            "size_pt",
            "line_spacing",
            "alignment",
            "space_before_pt",
            "space_after_pt",
            "first_line_indent_cm",
        ),
        allowed=(
            "font",
            "size_pt",
            "line_spacing",
            "alignment",
            "space_before_pt",
            "space_after_pt",
            "first_line_indent_cm",
        ),
    )
    _text(body["font"], "typography.body.font")
    _num(body["size_pt"], "typography.body.size_pt", minimum=6, maximum=36)
    _num(body["line_spacing"], "typography.body.line_spacing", minimum=1, maximum=3)
    _str(body["alignment"], "typography.body.alignment", choices=_ALIGNMENTS)
    _num(body["space_before_pt"], "typography.body.space_before_pt", minimum=0, maximum=72)
    _num(body["space_after_pt"], "typography.body.space_after_pt", minimum=0, maximum=72)
    _num(body["first_line_indent_cm"], "typography.body.first_line_indent_cm", minimum=0, maximum=5)

    headings = _obj(
        typography["headings"],
        "typography.headings",
        required=(
            "font",
            "bold",
            "color",
            "h1_size_pt",
            "h2_size_pt",
            "h1_space_before_pt",
            "h1_space_after_pt",
            "h2_space_before_pt",
            "h2_space_after_pt",
        ),
        allowed=(
            "font",
            "bold",
            "color",
            "h1_size_pt",
            "h2_size_pt",
            "h1_space_before_pt",
            "h1_space_after_pt",
            "h2_space_before_pt",
            "h2_space_after_pt",
        ),
    )
    _text(headings["font"], "typography.headings.font")
    _bool(headings["bold"], "typography.headings.bold")
    _color(headings["color"], "typography.headings.color")
    for key in ("h1_size_pt", "h2_size_pt"):
        _num(headings[key], f"typography.headings.{key}", minimum=8, maximum=48)
    for key in ("h1_space_before_pt", "h1_space_after_pt", "h2_space_before_pt", "h2_space_after_pt"):
        _num(headings[key], f"typography.headings.{key}", minimum=0, maximum=72)

    front_titles = _obj(
        typography["front_titles"],
        "typography.front_titles",
        required=("font", "size_pt", "bold", "align"),
        allowed=("font", "size_pt", "bold", "align"),
    )
    _text(front_titles["font"], "typography.front_titles.font")
    _num(front_titles["size_pt"], "typography.front_titles.size_pt", minimum=8, maximum=48)
    _bool(front_titles["bold"], "typography.front_titles.bold")
    _str(front_titles["align"], "typography.front_titles.align", choices=_ALIGNMENTS)

    quote = _obj(
        typography["quote"],
        "typography.quote",
        required=("size_pt", "italic", "indent_cm"),
        allowed=("size_pt", "italic", "indent_cm"),
    )
    _num(quote["size_pt"], "typography.quote.size_pt", minimum=6, maximum=36)
    _bool(quote["italic"], "typography.quote.italic")
    _num(quote["indent_cm"], "typography.quote.indent_cm", minimum=0, maximum=5)

    provenance = _obj(
        typography["provenance"],
        "typography.provenance",
        required=("size_pt", "italic", "color"),
        allowed=("size_pt", "italic", "color"),
    )
    _num(provenance["size_pt"], "typography.provenance.size_pt", minimum=6, maximum=24)
    _bool(provenance["italic"], "typography.provenance.italic")
    _color(provenance["color"], "typography.provenance.color")

    quotes = _obj(
        typography["quotes"],
        "typography.quotes",
        required=("style", "punctuation"),
        allowed=("style", "punctuation"),
    )
    _str(quotes["style"], "typography.quotes.style", choices=_QUOTE_STYLES)
    _str(quotes["punctuation"], "typography.quotes.punctuation", choices=_PUNCTUATION)

    dashes = _obj(
        typography["dashes"],
        "typography.dashes",
        required=("sentence", "range"),
        allowed=("sentence", "range"),
    )
    _str(dashes["sentence"], "typography.dashes.sentence", choices=_DASH_STYLES)
    _str(dashes["range"], "typography.dashes.range", choices=_DASH_STYLES)

    _bool(typography["nbsp_for_single_letters"], "typography.nbsp_for_single_letters")


def _validate_front_matter(front: Any) -> None:
    _obj(
        front,
        "front_matter",
        required=(
            "title_page",
            "dedication",
            "declaration",
            "abstract",
            "anotace",
            "table_of_contents",
        ),
        allowed=(
            "title_page",
            "dedication",
            "declaration",
            "abstract",
            "anotace",
            "table_of_contents",
        ),
    )
    _bool(front["title_page"], "front_matter.title_page")
    _bool(front["dedication"], "front_matter.dedication")
    _bool(front["declaration"], "front_matter.declaration")
    for key in ("abstract", "anotace"):
        section = _obj(
            front[key],
            f"front_matter.{key}",
            required=("enabled", "title", "keywords_title"),
            allowed=("enabled", "title", "keywords_title"),
        )
        _bool(section["enabled"], f"front_matter.{key}.enabled")
        _text(section["title"], f"front_matter.{key}.title")
        _text(section["keywords_title"], f"front_matter.{key}.keywords_title")
    toc = _obj(
        front["table_of_contents"],
        "front_matter.table_of_contents",
        required=("enabled", "depth", "title"),
        allowed=("enabled", "depth", "title"),
    )
    _bool(toc["enabled"], "front_matter.table_of_contents.enabled")
    _num(toc["depth"], "front_matter.table_of_contents.depth", minimum=1, maximum=3, integer=True)
    _text(toc["title"], "front_matter.table_of_contents.title")


def _validate_body(body: Any) -> None:
    _obj(
        body,
        "body",
        required=(
            "page_numbers",
            "running_header",
            "chapter_start_new_page",
            "heading_numbering",
            "references",
            "captions",
        ),
        allowed=(
            "page_numbers",
            "running_header",
            "chapter_start_new_page",
            "heading_numbering",
            "references",
            "captions",
        ),
    )
    numbers = _obj(
        body["page_numbers"],
        "body.page_numbers",
        required=("enabled", "position", "start_at_introduction"),
        allowed=("enabled", "position", "start_at_introduction"),
    )
    _bool(numbers["enabled"], "body.page_numbers.enabled")
    _str(numbers["position"], "body.page_numbers.position", choices=_PAGE_NUMBER_POSITIONS)
    _bool(numbers["start_at_introduction"], "body.page_numbers.start_at_introduction")

    header = _obj(
        body["running_header"],
        "body.running_header",
        required=("enabled", "text", "align"),
        allowed=("enabled", "text", "align"),
    )
    _bool(header["enabled"], "body.running_header.enabled")
    _str(header["text"], "body.running_header.text", choices=_HEADER_TEXTS)
    _str(header["align"], "body.running_header.align", choices={"left", "center", "right"})

    _bool(body["chapter_start_new_page"], "body.chapter_start_new_page")

    numbering = _obj(
        body["heading_numbering"],
        "body.heading_numbering",
        required=("enabled", "format"),
        allowed=("enabled", "format"),
    )
    _bool(numbering["enabled"], "body.heading_numbering.enabled")
    _str(numbering["format"], "body.heading_numbering.format", choices={"decimal"})

    references = _obj(
        body["references"],
        "body.references",
        required=("enabled", "title", "style", "scope", "sort"),
        allowed=("enabled", "title", "style", "scope", "sort"),
    )
    _bool(references["enabled"], "body.references.enabled")
    _text(references["title"], "body.references.title")
    _str(references["style"], "body.references.style", choices=_REFERENCE_STYLES)
    _str(references["scope"], "body.references.scope", choices=_REFERENCE_SCOPES)
    _str(references["sort"], "body.references.sort", choices=_REFERENCE_SORTS)

    captions = _obj(
        body["captions"],
        "body.captions",
        required=("table", "figure", "numbering"),
        allowed=("table", "figure", "numbering"),
    )
    _str(captions["table"], "body.captions.table", choices=_CAPTION_POSITIONS)
    _str(captions["figure"], "body.captions.figure", choices=_CAPTION_POSITIONS)
    _str(captions["numbering"], "body.captions.numbering", choices={"continuous"})


def _validate_corpus(corpus: Any) -> None:
    _obj(
        corpus,
        "corpus",
        required=("folder", "manifest", "formats"),
        allowed=("folder", "manifest", "formats"),
    )
    _text(corpus["folder"], "corpus.folder")
    _text(corpus["manifest"], "corpus.manifest")
    formats = corpus["formats"]
    if not isinstance(formats, list) or not formats:
        _fail("corpus.formats", "must be a non-empty list")
    for index, value in enumerate(formats):
        _str(value, f"corpus.formats[{index}]", choices=_FILE_FORMATS)
    if len(set(formats)) != len(formats):
        _fail("corpus.formats", "must not repeat a format")


def _validate_citations(citations: Any) -> None:
    _obj(citations, "citations", required=("in_text",), allowed=("in_text",))
    _str(citations["in_text"], "citations.in_text", choices=_CITATION_STYLES)
