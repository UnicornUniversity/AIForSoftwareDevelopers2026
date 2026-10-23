"""Parse the constrained Markdown used for chapter files.

The chapter format is deliberately small: front matter, level-2 headings,
paragraphs, block quotes with a provenance marker, emphasis and ``[docNN]``
citations.  Everything else is rejected with a line number, because a silently
ignored construct is a formatting bug the author would only notice in Word.

::

    ---
    chapter: 2
    title: Movement and Migration
    sources: doc06, doc24
    ---

    Prose citing a source [doc06].

    ## Dusk Routes

    > A verbatim sentence from the source.
    > — doc06
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ContentError

_CHAPTER_RE = re.compile(r"^chapter:\s*(\d+)\s*$")
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$")
_SOURCES_RE = re.compile(r"^sources:\s*(.*?)\s*$")
_DOC_ID_RE = re.compile(r"^doc\d+$")
_CITATION_RE = re.compile(r"\[doc\d+\]")
_MARKER_RE = re.compile(r"^—\s*(doc\d+)\s*$")
_INLINE_RE = re.compile(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[doc\d+\])")

_FRONT_KEYS = {"chapter", "title", "sources"}


@dataclass(frozen=True)
class Inline:
    text: str
    bold: bool = False
    italic: bool = False
    citation: bool = False


@dataclass(frozen=True)
class Block:
    kind: str  # heading | paragraph | quote | list_item
    text: str
    line: int
    source: str | None = None
    inlines: tuple[Inline, ...] = ()

    @property
    def citations(self) -> list[str]:
        if self.kind in {"quote"}:
            return []
        return re.findall(r"\[(doc\d+)\]", self.text)

    def with_inlines(self) -> "Block":
        if self.kind in {"quote"}:
            return self
        return Block(
            kind=self.kind,
            text=self.text,
            line=self.line,
            source=self.source,
            inlines=tuple(parse_inline(self.text, self.line, None)),
        )


@dataclass
class Chapter:
    path: Path
    number: int
    title: str
    sources: list[str]
    blocks: list[Block] = field(default_factory=list)

    @property
    def headings(self) -> list[Block]:
        return [block for block in self.blocks if block.kind == "heading"]

    @property
    def quotes(self) -> list[Block]:
        return [block for block in self.blocks if block.kind == "quote"]

    @property
    def words(self) -> int:
        return sum(len(block.text.split()) for block in self.blocks)


def _fail(path: Path, line: int, message: str) -> None:
    raise ContentError(message, file=path, line=line)


def parse_inline(text: str, line: int, path: Path | None) -> list[Inline]:
    """Split a paragraph into plain, bold, italic and citation spans."""

    spans: list[Inline] = []
    position = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > position:
            spans.append(Inline(text[position : match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            spans.append(Inline(token[2:-2], bold=True))
        elif token.startswith("*"):
            spans.append(Inline(token[1:-1], italic=True))
        else:
            spans.append(Inline(token, citation=True))
        position = match.end()
    if position < len(text):
        spans.append(Inline(text[position:]))

    for span in spans:
        if span.bold or span.italic or span.citation:
            continue
        if "*" in span.text:
            if path is not None:
                _fail(path, line, "unbalanced emphasis (check the * markers)")
        if "[" in span.text or "]" in span.text:
            if path is not None and not _CITATION_RE.search(span.text):
                _fail(path, line, "unsupported bracket syntax; cite sources with [docNN]")
    return spans


def _reject_markup(path: Path, line_no: int, line: str) -> None:
    stripped = line.strip()
    if stripped.startswith("```"):
        _fail(path, line_no, "code fences are not supported")
    if stripped.startswith("|"):
        _fail(path, line_no, "tables are not supported in chapter files")
    if stripped.startswith("# "):
        _fail(path, line_no, "level-1 headings are reserved for chapters; use ## for a section")
    if stripped.startswith("###"):
        _fail(path, line_no, "only level-2 headings (##) are supported")
    if stripped.startswith("!["):
        _fail(path, line_no, "images are not supported")
    if re.search(r"\[[^\]]+\]\([^)]+\)", stripped):
        _fail(path, line_no, "links are not supported")
    if stripped.startswith("[^"):
        _fail(path, line_no, "footnotes are not supported")
    if stripped in {"---", "***", "___"}:
        _fail(path, line_no, "horizontal rules are not supported")
    if stripped.startswith(("<", ">")):
        # '>' is handled as a quote before this check; a literal '<...>' is HTML.
        if stripped.startswith("<"):
            _fail(path, line_no, "HTML is not supported")


def _parse_front_matter(path: Path, lines: list[str]) -> tuple[dict, int]:
    if not lines or lines[0].strip() != "---":
        _fail(path, 1, "chapter file must start with a '---' front-matter block")
    values: dict[str, str] = {}
    for index in range(1, len(lines)):
        raw = lines[index]
        if raw.strip() == "---":
            return values, index + 1
        if not raw.strip():
            continue
        key, separator, value = raw.partition(":")
        if not separator:
            _fail(path, index + 1, "front matter must use 'key: value' lines")
        key = key.strip()
        if key not in _FRONT_KEYS:
            _fail(path, index + 1, f"unknown front-matter key {key!r}")
        if key in values:
            _fail(path, index + 1, f"duplicate front-matter key {key!r}")
        values[key] = value.strip()
    _fail(path, 1, "front-matter block is not closed with '---'")


def load_chapter(path: str | Path) -> Chapter:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ContentError("chapter file not found", file=path) from None
    except OSError as exc:
        raise ContentError(f"cannot read chapter file: {exc}", file=path) from None

    lines = text.splitlines()
    front, body_start = _parse_front_matter(path, lines)

    if "chapter" not in front:
        _fail(path, 1, "front matter is missing 'chapter'")
    if "title" not in front:
        _fail(path, 1, "front matter is missing 'title'")
    if "sources" not in front:
        _fail(path, 1, "front matter is missing 'sources'")
    if not _CHAPTER_RE.match(f"chapter: {front['chapter']}"):
        _fail(path, 1, "front-matter 'chapter' must be an integer")
    if not _TITLE_RE.match(f"title: {front['title']}"):
        _fail(path, 1, "front-matter 'title' must not be empty")

    number = int(front["chapter"])
    title = front["title"].strip()
    sources: list[str] = []
    for part in front["sources"].split(","):
        part = part.strip()
        if not part:
            continue
        if not _DOC_ID_RE.match(part):
            _fail(path, 1, f"invalid source id {part!r}; expected docNN")
        if part in sources:
            _fail(path, 1, f"source {part!r} is listed twice")
        sources.append(part)
    if not sources:
        _fail(path, 1, "front-matter 'sources' must list at least one document id")

    blocks: list[Block] = []
    paragraph: list[str] = []
    paragraph_line = 0

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_line
        if not paragraph:
            return
        joined = " ".join(part.strip() for part in paragraph).strip()
        joined = re.sub(r"\s+", " ", joined)
        if joined:
            block = Block(kind="paragraph", text=joined, line=paragraph_line)
            blocks.append(block.with_inlines())
        paragraph = []
        paragraph_line = 0

    index = body_start
    while index < len(lines):
        raw = lines[index]
        line_no = index + 1
        stripped = raw.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines: list[str] = []
            quote_start = line_no
            source: str | None = None
            while index < len(lines) and lines[index].strip().startswith(">"):
                content = lines[index].strip()[1:].strip()
                marker = _MARKER_RE.match(content)
                if marker:
                    if source is not None:
                        _fail(path, index + 1, "a quote may carry only one provenance marker")
                    source = marker.group(1)
                else:
                    if source is not None:
                        _fail(
                            path,
                            index + 1,
                            "the provenance marker must be the last line of the quote",
                        )
                    quote_lines.append(content)
                index += 1
            if source is None:
                _fail(path, quote_start, "quote is missing its '— docNN' provenance marker")
            quote_text = re.sub(r"\s+", " ", " ".join(quote_lines)).strip()
            if not quote_text:
                _fail(path, quote_start, "quote is empty")
            blocks.append(
                Block(kind="quote", text=quote_text, line=quote_start, source=source)
            )
            continue

        if stripped.startswith("## "):
            flush_paragraph()
            heading = stripped[3:].strip()
            if not heading:
                _fail(path, line_no, "heading text is empty")
            blocks.append(Block(kind="heading", text=heading, line=line_no))
            index += 1
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            item = stripped[2:].strip()
            if not item:
                _fail(path, line_no, "list item is empty")
            blocks.append(
                Block(kind="list_item", text=item, line=line_no).with_inlines()
            )
            index += 1
            continue

        if raw.startswith("    ") or raw.startswith("\t"):
            _fail(path, line_no, "indented blocks are not supported")

        _reject_markup(path, line_no, raw)
        if not paragraph:
            paragraph_line = line_no
        paragraph.append(raw)
        index += 1

    flush_paragraph()
    if not blocks:
        _fail(path, body_start + 1, "chapter has no content")
    return Chapter(path=path, number=number, title=title, sources=sources, blocks=blocks)
