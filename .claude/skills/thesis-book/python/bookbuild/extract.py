"""Extract readable text from corpus DOCX and PDF files.

Sources are treated as text: their fonts, colours and page layout are not
preserved.  DOCX files are walked in body order so that tables stay next to the
prose that introduces them.  PDF files are read as text lines and reflowed:
positional page furniture (running heads, footers and page numbers) is dropped,
then lines are joined into paragraphs by vertical pitch.

Every extraction is cached under ``book/.work/sources/<id>.json`` together with
the SHA-256 of the source.  A changed source is re-extracted automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .errors import CorpusError
from .manifest import DocumentEntry

# Bump when the extraction algorithm changes so old caches are discarded.
EXTRACTOR_VERSION = 1

_TERMINAL = ".!?:;”’)]"
_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s+\S")
_CAPTION_RE = re.compile(
    r"^(?:figure|fig\.|table|plate|box|chart|note)\s*\d*[.:]?\s", re.IGNORECASE
)
_FURNITURE_RE = re.compile(
    r"^(?:https?://|doi\s*:|received\b|accepted\b|published\b|"
    r"©|\(c\)\s*\d{4}|licen[cs]e|all rights reserved|downloaded from)",
    re.IGNORECASE,
)
_ABSTRACT_MARKERS = {
    "abstract",
    "executive summary",
    "summary",
    "transcription",
    "introduction",
    "contents",
}


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Collapse whitespace, remove soft hyphens and control characters."""

    text = text.replace(" ", " ").replace("­", "")
    text = "".join(
        char
        for char in text
        if char in "\n\t" or ord(char) >= 32
    )
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _join_line(left: str, right: str) -> str:
    """Join two physical lines, undoing an end-of-line hyphen."""

    right = right.strip()
    if not right:
        return left
    if left.endswith("-") and not left.endswith("--") and right[:1].islower():
        return left[:-1] + right
    return left + " " + right


def _looks_heading(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    if _HEADING_RE.match(text):
        return True
    words = text.split()
    return (
        len(words) <= 12
        and not text.endswith((".", ",", ";", ":"))
        and text[:1].isupper()
    )


def _block_kind(text: str, size: float, body_size: float, *, heading_style: bool = False) -> str:
    if _CAPTION_RE.match(text):
        return "caption"
    if heading_style or _HEADING_RE.match(text):
        return "heading"
    if size >= body_size + 1.0 and _looks_heading(text):
        return "heading"
    return "paragraph"


def _starts_lower(text: str) -> bool:
    return bool(text) and text[0].islower()


def _ends_open(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] not in _TERMINAL


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------


def _docx_blocks(document) -> Iterable[tuple[str, str]]:
    """Yield ``(kind_hint, text)`` in body order, including tables."""

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = normalise(paragraph.text)
            if not text:
                continue
            yield _docx_kind(paragraph, text), text
        elif tag == "tbl":
            table = Table(child, document)
            rows: list[str] = []
            for row in table.rows:
                cells = [normalise(cell.text) for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                yield "table", "\n".join(rows)


def _docx_kind(paragraph, text: str) -> str:
    style = (paragraph.style.name if paragraph.style is not None else "") or ""
    if style.lower().startswith("heading") or style.lower() == "title":
        return "heading"
    if _CAPTION_RE.match(text):
        return "caption"
    runs = [run for run in paragraph.runs if run.text.strip()]
    if not runs:
        return "paragraph"
    bold = all(run.bold for run in runs)
    sizes = [run.font.size.pt for run in runs if run.font.size is not None]
    if bold and sizes and max(sizes) >= 10 and _looks_heading(text):
        return "heading"
    return "paragraph"


def extract_docx(path: Path) -> list[dict]:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise CorpusError(
            "python-docx is not installed; run: python -m pip install --user -r "
            f"{Path(__file__).resolve().parents[2] / 'requirements.txt'}",
            file=path,
        ) from exc
    try:
        document = docx.Document(str(path))
    except Exception as exc:  # python-docx raises several unrelated types
        raise CorpusError(f"cannot read DOCX: {exc}", file=path) from exc

    blocks: list[dict] = []
    for hint, text in _docx_blocks(document):
        blocks.append({"kind": hint, "text": text})
    return _mark_front_matter(blocks)


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


def _pdf_line_size(line: dict) -> float:
    sizes = [
        char.get("size", 0)
        for char in line.get("chars", [])
        if char.get("size") is not None
    ]
    return max(sizes) if sizes else 0.0


def _page_lines(page) -> list[dict]:
    """Return text lines with page furniture already removed by position."""

    try:
        lines = page.extract_text_lines(return_chars=True)
    except TypeError:  # older pdfplumber without the keyword
        lines = page.extract_text_lines()
    height = float(page.height)
    top_limit = height * 0.055
    bottom_limit = height * 0.945
    kept: list[dict] = []
    for line in lines:
        text = normalise(line.get("text", ""))
        if not text:
            continue
        if line["top"] < top_limit or line["top"] > bottom_limit:
            continue
        if _FURNITURE_RE.match(text):
            continue
        if re.fullmatch(r"\d{1,4}", text):
            continue
        kept.append(
            {
                "text": text,
                "top": float(line["top"]),
                "size": _pdf_line_size(line),
            }
        )
    kept.sort(key=lambda item: item["top"])
    return kept


def _repeat_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.casefold())).strip()


def _body_size(lines: list[dict]) -> float:
    sizes = [line["size"] for line in lines if line["size"]]
    return statistics.median(sizes) if sizes else 10.0


def _group_lines(lines: list[dict], body_size: float) -> list[dict]:
    """Group lines into paragraph blocks using the vertical pitch."""

    if not lines:
        return []
    tops = [line["top"] for line in lines]
    gaps = [b - a for a, b in zip(tops, tops[1:]) if 0 < b - a < 120]
    median_gap = statistics.median(gaps) if gaps else 14.0
    threshold = max(median_gap * 1.35, median_gap + 4.0)

    groups: list[list[dict]] = []
    current: list[dict] = []
    previous_top: float | None = None
    for line in lines:
        starts_new = (
            not current
            or previous_top is None
            or line["top"] - previous_top > threshold
        )
        if starts_new:
            if current:
                groups.append(current)
            current = [line]
        else:
            current.append(line)
        previous_top = line["top"]
    if current:
        groups.append(current)

    blocks: list[dict] = []
    for group in groups:
        text = group[0]["text"]
        for line in group[1:]:
            text = _join_line(text, line["text"])
        text = normalise(text)
        if not text:
            continue
        size = max(line["size"] for line in group)
        kind = _block_kind(text, size, body_size)
        blocks.append({"kind": kind, "text": text, "size": size})
    return blocks


def extract_pdf(path: Path) -> list[dict]:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise CorpusError(
            "pdfplumber is not installed; run: python -m pip install --user -r "
            f"{Path(__file__).resolve().parents[2] / 'requirements.txt'}",
            file=path,
        ) from exc
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = [_page_lines(page) for page in pdf.pages]
    except Exception as exc:  # pdfplumber raises several unrelated types
        raise CorpusError(f"cannot read PDF: {exc}", file=path) from exc

    # Running heads and footers repeat on several pages; drop them everywhere.
    page_counts: dict[str, int] = {}
    for lines in pages:
        for key in {_repeat_key(line["text"]) for line in lines}:
            page_counts[key] = page_counts.get(key, 0) + 1
    furniture = {key for key, count in page_counts.items() if count >= 2}
    pages = [
        [line for line in lines if _repeat_key(line["text"]) not in furniture]
        for lines in pages
    ]

    all_sizes = [line["size"] for lines in pages for line in lines if line["size"]]
    body_size = statistics.median(all_sizes) if all_sizes else 10.0

    blocks: list[dict] = []
    previous_page_last: dict | None = None
    for lines in pages:
        page_blocks = _group_lines(lines, body_size)
        if not page_blocks:
            continue
        if (
            blocks
            and previous_page_last is not None
            and previous_page_last["kind"] == "paragraph"
            and page_blocks[0]["kind"] == "paragraph"
            and _ends_open(previous_page_last["text"])
            and _starts_lower(page_blocks[0]["text"])
        ):
            blocks[-1]["text"] = _join_line(blocks[-1]["text"], page_blocks[0]["text"])
            page_blocks = page_blocks[1:]
        blocks.extend(page_blocks)
        if page_blocks:
            previous_page_last = page_blocks[-1]
        elif blocks:
            previous_page_last = blocks[-1]

    for block in blocks:
        block.pop("size", None)
    return _mark_front_matter(blocks)


# --------------------------------------------------------------------------
# whole documents
# --------------------------------------------------------------------------


def _mark_front_matter(blocks: list[dict]) -> list[dict]:
    """Label cover pages and running matter before the first body section.

    The label is informational: every block stays quotable, but ``context``
    output can show which text is scholarly furniture rather than argument.
    """

    marked: list[dict] = []
    in_front = True
    for block in blocks:
        text = block["text"]
        if in_front and block["kind"] in {"heading", "paragraph"}:
            first_line = text.splitlines()[0].strip().rstrip(":").lower()
            starts_body = any(
                first_line == marker
                or (
                    first_line.startswith(marker + " ")
                    and len(first_line) > len(marker)
                )
                for marker in _ABSTRACT_MARKERS
            )
            if starts_body or _HEADING_RE.match(text):
                in_front = False
        if in_front and block["kind"] != "table":
            marked.append({"kind": "meta", "text": text})
        else:
            marked.append({"kind": block["kind"], "text": text})
    return marked


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


@dataclass
class SourceText:
    id: str
    format: str
    title: str
    sha256: str
    size: int
    mtime: float
    extractor_version: int
    blocks: list[dict] = field(default_factory=list)

    @property
    def paragraphs(self) -> list[str]:
        return [block["text"] for block in self.blocks]

    @property
    def words(self) -> int:
        return sum(_word_count(block["text"]) for block in self.blocks)

    @property
    def body_words(self) -> int:
        return sum(
            _word_count(block["text"])
            for block in self.blocks
            if block["kind"] not in {"meta"}
        )

    def to_cache(self) -> dict:
        return {
            "id": self.id,
            "format": self.format,
            "title": self.title,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime,
            "extractor_version": self.extractor_version,
            "blocks": self.blocks,
        }

    @classmethod
    def from_cache(cls, raw: dict) -> "SourceText":
        return cls(
            id=raw["id"],
            format=raw["format"],
            title=raw.get("title", ""),
            sha256=raw["sha256"],
            size=raw["size"],
            mtime=raw["mtime"],
            extractor_version=raw["extractor_version"],
            blocks=list(raw["blocks"]),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Extractor:
    """Extract sources, reusing a hash-keyed cache when it is still valid."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def _cache_path(self, entry: DocumentEntry) -> Path:
        return self.cache_dir / f"{entry.id}.json"

    def load_or_extract(
        self,
        entry: DocumentEntry,
        source_path: Path,
        *,
        refresh: bool = False,
    ) -> SourceText:
        source_path = Path(source_path)
        if not source_path.is_file():
            raise CorpusError("source document not found", file=source_path)
        stat = source_path.stat()
        digest = _sha256(source_path)

        if not refresh:
            cached = self._read_cache(entry, source_path)
            if (
                cached is not None
                and cached.sha256 == digest
                and cached.size == stat.st_size
                and cached.extractor_version == EXTRACTOR_VERSION
            ):
                return cached

        blocks = self._extract(entry, source_path)
        result = SourceText(
            id=entry.id,
            format=entry.format,
            title=entry.title,
            sha256=digest,
            size=stat.st_size,
            mtime=stat.st_mtime,
            extractor_version=EXTRACTOR_VERSION,
            blocks=blocks,
        )
        self._write_cache(entry, result)
        return result

    def _extract(self, entry: DocumentEntry, source_path: Path) -> list[dict]:
        suffix = source_path.suffix.lower()
        if suffix == ".docx":
            blocks = extract_docx(source_path)
        elif suffix == ".pdf":
            blocks = extract_pdf(source_path)
        else:
            raise CorpusError(
                f"unsupported source format {suffix!r}", file=source_path
            )
        if not any(block["kind"] != "meta" for block in blocks):
            raise CorpusError(
                "no body text could be extracted", file=source_path
            )
        return blocks

    def _read_cache(self, entry: DocumentEntry, source_path: Path) -> SourceText | None:
        path = self._cache_path(entry)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return SourceText.from_cache(raw)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError):
            return None

    def _write_cache(self, entry: DocumentEntry, result: SourceText) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(entry)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(result.to_cache(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(temporary, path)
