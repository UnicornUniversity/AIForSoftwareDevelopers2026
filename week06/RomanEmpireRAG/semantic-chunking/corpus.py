"""Corpus loading for the semantic-chunking study.

The six Project Gutenberg files are wrapped at ~70 columns, use blank lines as
paragraph separators, and put a one-block synopsis under every chapter heading.
Those rules are parsed here with the same heuristics as the stdlib-only sibling
study in ``../chunking/chunking.py``. The code is intentionally duplicated
rather than imported: each assignment folder in this repository is a
self-contained answer, and the sibling is a different deliverable.

Nothing in this module is semantic. It produces the sentence stream that the
embedding pass in ``semantic_chunking.py`` reasons about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

START_MARK = "*** START OF THE PROJECT GUTENBERG EBOOK"
END_MARK = "*** END OF THE PROJECT GUTENBERG"

# A heading is a *short* block that opens with one of these. Length matters:
# the same words occur inside running prose and in the table of contents.
HEADING_RE = re.compile(
    r"^(?:Chapter\s+[IVXL]+\b|Introduction\b|Preface\b|Appendix\b|Advertisement\b)"
)
CHAPTER_RE = re.compile(r"^Chapter\s+([IVXL]+)\b")
PART_RE = re.compile(r"Part\s+([IVXL]+)\b")

# Sentence end: terminal punctuation, optional closing quote/bracket, whitespace.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])[\"”’')\]]*\s+")
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "rev", "hon", "capt", "col", "gen", "lieut",
    "vol", "vols", "ch", "chap", "bk", "p", "pp", "no", "nos", "cf", "viz",
    "i.e", "e.g", "etc", "ib", "ibid", "id", "cap", "lib", "edit", "ed", "sq",
    "b.c", "a.d", "a.c", "a.u", "c", "vid", "apud", "advers", "m", "mm", "d",
}
INITIALS_RE = re.compile(r"^[A-Z]$")

# A sentence that opens with one of these looks backwards. Used only to measure
# how often overlap repairs a dangling reference; never to place a boundary.
REFERENCE_START_RE = re.compile(
    r"^(?:the former|the latter|in this|in that|at this|from this|by this|to this|"
    r"he|she|it|they|this|these|those|such|his|her|its|their|him|them|"
    r"which|who|whom|whose|that|but|and|nor|yet|thus|hence|however|therefore|"
    r"thereupon|meanwhile)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Low-level block handling
# ---------------------------------------------------------------------------


def read_volume(path: Path) -> str:
    """Return the book body of a Gutenberg file, line endings normalised."""
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    start = raw.find(START_MARK)
    if start < 0:
        raise SystemExit(f"{path.name}: no Project Gutenberg START marker")
    body = raw[start:].split("\n", 1)[1]
    end = body.find(END_MARK)
    if end >= 0:
        body = body[:end]
    return body


def join_lines(block: str) -> str:
    """Collapse a wrapped block into one line.

    A scan of all six volumes found no line break inside a hyphenated word, so
    joining with a space is exact; no dehyphenation pass is needed.
    """
    lines = [line.strip() for line in block.split("\n")]
    return " ".join(line for line in lines if line)


def is_heading(text: str) -> bool:
    return len(text) <= 400 and bool(HEADING_RE.match(text))


def split_blocks(body: str) -> list["Block"]:
    raw_blocks = re.split(r"\n[ \t]*\n+", body)
    blocks: list[Block] = []
    for raw in raw_blocks:
        text = join_lines(raw)
        if text:
            blocks.append(Block(index=len(blocks), text=text))
    return blocks


def find_content_start(blocks: list["Block"]) -> int:
    """Index of the first block that is book content rather than front matter.

    Every volume opens with a title page and a table of contents, but only some
    label it ``CONTENTS``. The reliable discriminator is rhythm: a real chapter
    heading is followed by its synopsis and then by a long paragraph, while a
    TOC entry is followed by the next short entry. So the body starts at the
    first heading with a >1,000-character block within the next two blocks.
    """
    for block in blocks:
        if not is_heading(block.text):
            continue
        window = blocks[block.index + 1 : block.index + 3]
        if any(len(b.text) > 1000 for b in window):
            return block.index
    return next((b.index for b in blocks if CHAPTER_RE.match(b.text)), 0)


def classify(blocks: list["Block"], start: int) -> list["Block"]:
    """Mark headings and the descriptive subtitle that follows each heading."""
    kept = blocks[start:]
    current_chapter = ""
    previous_was_heading = True
    for block in kept:
        if is_heading(block.text):
            block.kind = "heading"
            current_chapter = block.text
            previous_was_heading = True
        elif previous_was_heading and len(block.text) < 600:
            block.kind = "subtitle"
            previous_was_heading = False
        else:
            block.kind = "paragraph"
            previous_was_heading = False
        block.chapter = current_chapter
    return kept


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, resisting abbreviations and initials."""
    parts = SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if sentences:
            previous = sentences[-1]
            last_word = previous.rstrip(".!?\"”’')]").rsplit(" ", 1)[-1]
            ends_abbrev = last_word.lower().rstrip(".") in ABBREVIATIONS or bool(
                INITIALS_RE.match(last_word.rstrip("."))
            )
            if ends_abbrev or not re.search(r"[.!?][\"”’')\]]*$", previous):
                sentences[-1] = previous + " " + part
                continue
        sentences.append(part)
    return sentences


# ---------------------------------------------------------------------------
# Corpus model
# ---------------------------------------------------------------------------


@dataclass
class Block:
    index: int
    text: str
    kind: str = "paragraph"  # heading | subtitle | paragraph
    chapter: str = ""


@dataclass
class Paragraph:
    volume: int
    chapter_id: str
    text: str
    index: int  # position within the volume
    sentences: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class Sentence:
    volume: int
    chapter_id: str
    chapter_label: str
    paragraph: int  # volume-level paragraph index
    text: str
    starts_paragraph: bool
    ends_paragraph: bool
    pos: int = -1  # position in the global sentence stream

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def starts_with_reference(self) -> bool:
        return bool(REFERENCE_START_RE.match(self.text))


@dataclass
class Chapter:
    id: str
    volume: int
    heading: str
    label: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    sentences: list[Sentence] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(s.chars for s in self.sentences)

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.paragraphs)


@dataclass
class Volume:
    number: int
    path: Path
    title: str
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def sentences(self) -> list[Sentence]:
        return [s for c in self.chapters for s in c.sentences]

    @property
    def paragraphs(self) -> list[Paragraph]:
        return [p for c in self.chapters for p in c.paragraphs]

    @property
    def chars(self) -> int:
        return sum(c.chars for c in self.chapters)


def chapter_label(heading: str) -> str:
    """Short, stable label for tables and the RAG metadata.

    ``Chapter XIV: ...—Part II.`` becomes ``Ch. XIV · Part II``; a preface
    becomes its first phrase. The label is metadata, not a split key: two
    headings with the same label are still separate chapters (parts).
    """
    match = CHAPTER_RE.match(heading)
    if match:
        label = f"Ch. {match.group(1)}"
        part = PART_RE.search(heading)
        if part:
            label += f" · Part {part.group(1)}"
        return label
    first = re.split(r"[.:—]", heading, maxsplit=1)[0].strip()
    return (first or heading)[:48]


def volume_number(path: Path) -> int:
    match = re.search(r"Volume\s+(\d+)", path.stem)
    if not match:
        raise SystemExit(f"{path.name}: no volume number in the filename")
    return int(match.group(1))


def load_volume(path: Path) -> Volume:
    number = volume_number(path)
    blocks = split_blocks(read_volume(path))
    blocks = classify(blocks, find_content_start(blocks))
    volume = Volume(number=number, path=path, title=path.stem)
    current: Chapter | None = None
    chapter_index = 0

    for block in blocks:
        if block.kind == "heading":
            current = Chapter(
                id=f"v{number}-ch{chapter_index:03d}",
                volume=number,
                heading=block.text,
                label=chapter_label(block.text),
            )
            chapter_index += 1
            volume.chapters.append(current)
            continue
        if block.kind != "paragraph":
            continue
        if current is None:
            # Defensive: find_content_start should always land on a heading.
            current = Chapter(
                id=f"v{number}-ch{chapter_index:03d}",
                volume=number,
                heading="",
                label="Front matter",
            )
            chapter_index += 1
            volume.chapters.append(current)
        paragraph = Paragraph(
            volume=number,
            chapter_id=current.id,
            text=block.text,
            index=len(volume.paragraphs),
            sentences=split_sentences(block.text),
        )
        current.paragraphs.append(paragraph)

    # Headings with no prose (a stray part heading, a decorative divider) are
    # not chunks and would only create empty chapter rows in the report.
    volume.chapters = [chapter for chapter in volume.chapters if chapter.paragraphs]

    # Flatten to a sentence stream and assign global positions.
    pos = 0
    for chapter in volume.chapters:
        for paragraph in chapter.paragraphs:
            for s_index, text in enumerate(paragraph.sentences):
                chapter.sentences.append(
                    Sentence(
                        volume=number,
                        chapter_id=chapter.id,
                        chapter_label=chapter.label,
                        paragraph=paragraph.index,
                        text=text,
                        starts_paragraph=s_index == 0,
                        ends_paragraph=s_index == len(paragraph.sentences) - 1,
                        pos=pos,
                    )
                )
                pos += 1
    volume.chapters = [chapter for chapter in volume.chapters if chapter.sentences]
    return volume


def load_corpus(data_dir: Path | str = DATA_DIR) -> list[Volume]:
    data_dir = Path(data_dir)
    paths = sorted(data_dir.glob("*Volume*.txt"), key=volume_number)
    if not paths:
        raise SystemExit(f"no '*Volume*.txt' files in {data_dir}")
    return [load_volume(path) for path in paths]


def flatten_sentences(volumes: list[Volume]) -> list[Sentence]:
    return [s for v in volumes for s in v.sentences]


def corpus_summary(volumes: list[Volume]) -> dict:
    sentences = flatten_sentences(volumes)
    paragraphs = [p for v in volumes for p in v.paragraphs]
    para_chars = sorted(p.chars for p in paragraphs)
    sentence_chars = sorted(s.chars for s in sentences)
    return {
        "volumes": len(volumes),
        "chapters": sum(len(v.chapters) for v in volumes),
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "chars": sum(v.chars for v in volumes),
        "words": sum(len(s.text.split()) for s in sentences),
        "mean_paragraph_chars": round(sum(para_chars) / len(para_chars), 1) if para_chars else 0,
        "median_paragraph_chars": _percentile(para_chars, 50),
        "p90_paragraph_chars": _percentile(para_chars, 90),
        "p99_paragraph_chars": _percentile(para_chars, 99),
        "mean_sentence_chars": round(sum(sentence_chars) / len(sentence_chars), 1) if sentence_chars else 0,
        "median_sentence_chars": _percentile(sentence_chars, 50),
        "p90_sentence_chars": _percentile(sentence_chars, 90),
        "per_volume": [
            {
                "volume": v.number,
                "chapters": len(v.chapters),
                "paragraphs": len(v.paragraphs),
                "sentences": len(v.sentences),
                "chars": v.chars,
            }
            for v in volumes
        ],
    }


def _percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * q / 100.0
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return round(sorted_values[low] * (1 - frac) + sorted_values[high] * frac)


if __name__ == "__main__":
    import json

    vols = load_corpus()
    print(json.dumps(corpus_summary(vols), indent=2))
    for v in vols:
        print(f"volume {v.number}: {len(v.chapters)} chapters, {len(v.sentences)} sentences")
        for c in v.chapters[:3]:
            print(f"  {c.id} {c.label}: {len(c.sentences)} sentences, {c.chars} chars")
