"""Chunking analysis for the six volumes of Gibbon's *Decline and Fall*.

Standard library only. This module is the single source of truth for every number
in the report: `make_html.py` renders what it writes to `stats.json`, and the
sample chunks it emits come from the same splitter that produced the stats.

What it does
------------
1. Loads the six Gutenberg volumes and strips the boilerplate (licence header and
   footer) and the table of contents -- neither is book prose, and both would
   distort paragraph and chunk statistics.
2. Splits each volume into paragraphs on blank lines, marks chapter headings, and
   records every paragraph's length.
3. Re-splits paragraphs into sentences so a chunk can end at a sentence boundary
   instead of cutting mid-clause. Sentence splitting is abbreviation-aware: the
   text is full of "St.", "M.", "A.D." and "i.e.".
4. Sweeps a grid of chunk sizes and overlaps, packing whole paragraphs where they
   fit and falling back to sentences. Every configuration is scored on the same
   metrics, so the recommendation is a measured choice rather than a rule of thumb.
5. Writes `stats.json` (everything the report shows), `report.html` (via
   `make_html.py`) and, for the recommended configuration, the chunks themselves
   as gzipped JSON Lines.

Usage
-----
    python chunking.py                 # analyse and write stats.json + chunks
    python chunking.py --no-chunks     # stats.json only
    python chunking.py --explain       # print the segmentation decisions

Run it from this directory; paths are resolved relative to the file, not the cwd.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = Path(__file__).resolve().parent / "out"

# Project Gutenberg wraps every text in a licence header and footer. Everything
# outside these two markers is not the book.
START_MARK = "*** START OF THE PROJECT GUTENBERG EBOOK"
END_MARK = "*** END OF THE PROJECT GUTENBERG"

# A heading is a *short* block that opens with one of these. Length matters: the
# same wording also appears inside running prose ("...in the first chapter..."),
# and in the tables of contents.
HEADING_RE = re.compile(r"^(?:Chapter\s+[IVXL]+\b|Introduction\b|Preface\b|Appendix\b|Advertisement\b)")
CHAPTER_RE = re.compile(r"^Chapter\s+([IVXL]+)\b")
# Word count is a whitespace token count. The token estimate is deliberately the
# crudest possible one and is labelled as such wherever it is shown: chars / 4 is
# the standard GPT-family rule of thumb for English, and no tokenizer is vendored
# here because that would add a dependency to a stdlib-only report.
CHARS_PER_TOKEN = 4.0
# Hard constraint on the recommendation, not part of the score: the common
# embedding models (bge-base, e5, all-MiniLM) take at most 512 input tokens and
# silently truncate anything longer. A chunk above that limit is only half
# embedded, so no target beyond it can be optimal however well it scores.
EMBED_WINDOW_TOKENS = 512
EMBED_WINDOW_CHARS = int(EMBED_WINDOW_TOKENS * CHARS_PER_TOKEN)
# Overlap above a fifth of the chunk is repetition rather than context. The grid
# is cut there rather than at the point the score's waste penalty saturates.
MAX_OVERLAP_SHARE = 0.20
# The chapter heading is prepended at embedding time as a breadcrumb; this is the
# measured mean length of a heading block, for the window arithmetic in the report.
HEADING_PREFIX_CHARS = 110

# Sentence end: terminal punctuation, then optional closing quote/bracket, then
# whitespace. The lookbehind keeps the punctuation on the left fragment.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])[\"”’')\]]*\s+")
# Titles and abbreviations that end in a period but not a sentence. Gibbon mixes
# Latin and English, so this list is longer than a modern prose one would be.
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "rev", "hon", "capt", "col", "gen", "lieut",
    "vol", "vols", "ch", "chap", "bk", "p", "pp", "no", "nos", "cf", "viz",
    "i.e", "e.g", "etc", "ib", "ibid", "id", "cap", "lib", "edit", "ed", "sq",
    "b.c", "a.d", "a.c", "a.u", "c", "vid", "apud", "advers", "m", "mm", "d",
}
INITIALS_RE = re.compile(r"^[A-Z]$")
# Sentence openers that point backwards. Used to measure what overlap repairs.
REFERENCE_START_RE = re.compile(
    r"^(?:the former|the latter|in this|in that|at this|from this|by this|to this|"
    r"he|she|it|they|this|these|those|such|his|her|its|their|him|them|"
    r"which|who|whom|whose|that|but|and|nor|yet|thus|hence|however|therefore|"
    r"thereupon|meanwhile)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------------------
# Loading and segmentation
# --------------------------------------------------------------------------------------


@dataclass
class Block:
    """One blank-line-delimited block of a volume, before classification."""

    index: int
    text: str
    kind: str = "paragraph"  # "heading" | "subtitle" | "paragraph"
    chapter: str = ""


@dataclass
class Paragraph:
    volume: int
    chapter: str
    text: str
    index: int = 0  # position within the volume, not the corpus
    sentences: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return len(self.text)


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

    No dehyphenation is needed: a scan of all six volumes found zero line breaks
    inside a hyphenated word, so joining with a space is exact.
    """
    lines = [line.strip() for line in block.split("\n")]
    return " ".join(line for line in lines if line)


def is_heading(text: str) -> bool:
    return len(text) <= 400 and bool(HEADING_RE.match(text))


def split_blocks(body: str) -> list[Block]:
    raw_blocks = re.split(r"\n[ \t]*\n+", body)
    blocks = []
    for raw in raw_blocks:
        text = join_lines(raw)
        if text:
            blocks.append(Block(index=len(blocks), text=text))
    return blocks


def find_content_start(blocks: list[Block]) -> int:
    """Index of the first block that is book content rather than front matter.

    Every volume opens with a table of contents *and* a title page, but only
    volumes 1 and 3 label it "CONTENTS"; volume 2 omits the label entirely, so a
    marker search is not enough. The reliable discriminator is rhythm: a real
    chapter heading is followed by its synopsis and then by a long paragraph,
    while a TOC entry is followed by its short synopsis and then by the next
    entry. So the body starts at the first heading with a >1000-char block within
    the next two blocks.
    """
    for block in blocks:
        if not is_heading(block.text):
            continue
        window = blocks[block.index + 1 : block.index + 3]
        if any(len(b.text) > 1000 for b in window):
            return block.index
    return next((b.index for b in blocks if CHAPTER_RE.match(b.text)), 0)


def classify(blocks: list[Block], start: int) -> list[Block]:
    """Mark headings and the descriptive subtitle that follows each heading.

    In these texts every chapter heading is followed by a one-block synopsis
    ("Death Of Gratian.—Ruin Of Arianism.—..."). Keeping it as prose would put a
    table-of-contents fragment into the first chunk of every chapter, so it is
    attached to the heading as metadata instead.
    """
    kept = blocks[start:]
    current_chapter = ""
    previous_was_heading = True  # the first block after front matter is a heading
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


def load_volume(path: Path, volume: int) -> tuple[list[Paragraph], list[str]]:
    blocks = split_blocks(read_volume(path))
    blocks = classify(blocks, find_content_start(blocks))
    headings = [b.text for b in blocks if b.kind == "heading"]
    paragraphs = []
    for block in blocks:
        if block.kind != "paragraph":
            continue
        paragraphs.append(
            Paragraph(
                volume=volume,
                chapter=block.chapter,
                text=block.text,
                index=len(paragraphs),
                sentences=split_sentences(block.text),
            )
        )
    return paragraphs, headings


# --------------------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------------------


@dataclass
class Sentence:
    volume: int
    chapter: str
    paragraph: int
    text: str
    starts_paragraph: bool
    ends_paragraph: bool
    # Position in the flattened stream. Chunks record the range they cover so
    # the report can lay the corpus out once and still show chunk boundaries.
    pos: int = -1


@dataclass
class Chunk:
    volume: int
    chapter: str
    text: str
    paragraph_from: int
    paragraph_to: int
    overlap_chars: int
    starts_at_paragraph: bool
    ends_at_paragraph: bool
    content_start: str = ""
    content_text: str = ""
    # Range of the sentence stream this chunk covers: `stream_from` includes the
    # carried overlap, `content_from` is the chunk's own first sentence, and
    # `stream_to` is its last. `split` marks the word-boundary fallback, whose
    # pieces are not whole sentences and therefore cannot be laid out as ranges.
    stream_from: int = -1
    content_from: int = -1
    stream_to: int = -1
    split: bool = False

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def tokens(self) -> int:
        return round(self.chars / CHARS_PER_TOKEN)


def flatten(paragraphs: list[Paragraph]) -> list[Sentence]:
    """Turn paragraphs into a sentence stream with boundary flags attached."""
    stream: list[Sentence] = []
    for paragraph in paragraphs:
        for s_index, sentence in enumerate(paragraph.sentences):
            stream.append(
                Sentence(
                    volume=paragraph.volume,
                    chapter=paragraph.chapter,
                    paragraph=paragraph.index,
                    text=sentence,
                    starts_paragraph=s_index == 0,
                    ends_paragraph=s_index == len(paragraph.sentences) - 1,
                    pos=len(stream),
                )
            )
    return stream


def pack(stream: list[Sentence], target_chars: int, overlap_chars: int) -> list[Chunk]:
    """Pack the sentence stream into chunks of roughly `target_chars`.

    Whole paragraphs are preferred: a sentence is appended while the chunk stays
    under 115% of the target. When the target is crossed mid-paragraph the chunk
    is closed at that sentence, which is why chunk sizes cluster just under the
    target instead of exactly on it.

    Overlap is carried in whole sentences from the tail of the previous chunk,
    within the same chapter only, so a chunk repeats the last one or two
    sentences of its predecessor -- the context an embedding needs to resolve
    pronouns and continuations.
    """
    hard_cap = max(1, int(target_chars * 1.15))
    carry_cap = max(1, int(target_chars * 0.40))  # never repeat more than 40% of a chunk
    chunks: list[Chunk] = []
    current: list[Sentence] = []
    current_chars = 0
    carry: list[Sentence] = []
    overlap_n = 0

    def flush() -> None:
        """Close the open chunk and compute the tail that may seed the next one."""
        nonlocal current, current_chars, carry, overlap_n
        if not current:
            return
        content = current[overlap_n:]  # the sentences this chunk contributes
        overlap_text = " ".join(s.text for s in current[:overlap_n])
        chunks.append(
            Chunk(
                volume=current[0].volume,
                chapter=current[0].chapter,
                text=" ".join(s.text for s in current),
                paragraph_from=content[0].paragraph if content else current[-1].paragraph,
                paragraph_to=current[-1].paragraph,
                overlap_chars=len(overlap_text) + (1 if overlap_text else 0),
                starts_at_paragraph=content[0].starts_paragraph if content else False,
                ends_at_paragraph=current[-1].ends_paragraph,
                content_start=" ".join(s.text for s in content)[:80],
                content_text=" ".join(s.text for s in content),
                stream_from=current[0].pos,
                content_from=content[0].pos if content else current[-1].pos,
                stream_to=current[-1].pos,
            )
        )
        carry = []
        if overlap_chars > 0 and content:
            total = 0
            for sentence in reversed(content):
                added = len(sentence.text) + 1
                if total >= overlap_chars:
                    break
                if carry and total + added > carry_cap:
                    break
                # Stop at the sentence count whose total is *closest* to the
                # requested overlap. Accumulating one sentence past the target
                # would double the repeated text at small chunk sizes.
                if carry and abs(total + added - overlap_chars) >= abs(total - overlap_chars):
                    break
                carry.insert(0, sentence)
                total += added
            # Never carry the whole chunk: that would repeat the chunk in full.
            if len(carry) == len(content):
                carry = carry[1:]
        current = []
        current_chars = 0
        overlap_n = 0

    def start_from_carry(sentence: Sentence) -> None:
        nonlocal current, current_chars, carry, overlap_n
        if carry and carry[0].volume == sentence.volume and carry[0].chapter == sentence.chapter:
            current = list(carry)
            current_chars = sum(len(s.text) + 1 for s in current)
            overlap_n = len(current)
        carry = []

    for sentence in stream:
        length = len(sentence.text) + 1  # +1 for the joining space
        # A new chapter never continues the previous chunk and never inherits
        # overlap from it: the heading is its own context reset.
        if current and (
            sentence.volume != current[0].volume or sentence.chapter != current[0].chapter
        ):
            flush()
            carry = []

        if not current:
            start_from_carry(sentence)

        if current and current_chars + length > hard_cap:
            flush()
            start_from_carry(sentence)

        # A single sentence longer than the cap (rare: the texts are wrapped at
        # 70 columns and sentences are short) is split at a word boundary.
        if not current and length > hard_cap:
            line: list[str] = []
            line_chars = 0
            pieces: list[str] = []
            for word in sentence.text.split():
                if line and line_chars + len(word) + 1 > hard_cap:
                    pieces.append(" ".join(line))
                    line, line_chars = [], 0
                line.append(word)
                line_chars += len(word) + 1
            if line:
                pieces.append(" ".join(line))
            for piece in pieces[:-1]:
                chunks.append(
                    Chunk(
                        volume=sentence.volume,
                        chapter=sentence.chapter,
                        text=piece,
                        paragraph_from=sentence.paragraph,
                        paragraph_to=sentence.paragraph,
                        overlap_chars=0,
                        starts_at_paragraph=False,
                        ends_at_paragraph=False,
                        content_start=piece[:80],
                        content_text=piece,
                        stream_from=sentence.pos,
                        content_from=sentence.pos,
                        stream_to=sentence.pos,
                        split=True,
                    )
                )
            # Replace the stream sentence with its last piece *locally*: the
            # stream is reused by every configuration in the sweep, so mutating
            # it would truncate the corpus for the next one.
            sentence = Sentence(
                volume=sentence.volume,
                chapter=sentence.chapter,
                paragraph=sentence.paragraph,
                text=pieces[-1],
                starts_paragraph=False,
                ends_paragraph=sentence.ends_paragraph,
                pos=sentence.pos,
            )
            length = len(sentence.text) + 1

        current.append(sentence)
        current_chars += length

    flush()
    return chunks


# --------------------------------------------------------------------------------------
# Volume view (the full-text visualisation)
# --------------------------------------------------------------------------------------


CHAPTER_LABEL_RE = re.compile(r"^(Chapter\s+[IVXL]+|Introduction|Preface|Appendix|Advertisement)")


def chapter_label(title: str) -> str:
    """A short tab label for a chapter heading ("Ch. IV·II", "Preface 3")."""
    match = CHAPTER_LABEL_RE.match(title)
    if not match:
        return title[:16]
    base = match.group(1)
    if base.startswith("Chapter"):
        part = re.search(r"Part\s+([IVXL]+)\b", title)
        return base.replace("Chapter ", "Ch. ") + (f"·{part.group(1)}" if part else "")
    return base


def build_volume_view(
    stream: list[Sentence], chunks: list[Chunk], volume: int, file_name: str
) -> dict:
    """A render-ready view of one volume: every sentence once, tagged by chunk.

    The chunker emits overlapping chunks, so their texts repeat the boundary
    sentences. Laying those copies out one after another would show the overlap
    only as duplicated prose. Instead the volume is walked once and every
    sentence is tagged with the chunk that owns it and, where it applies, the
    chunk that re-reads it as overlap. Consecutive sentences with the same tag
    are merged into one run, which keeps the page small.

    Raises if a chunk is not a contiguous stream range. Only the word-split
    fallback can produce that, and it does not occur in these volumes; laying
    such chunks out silently would misplace text.
    """
    volume_chunks = [(i, c) for i, c in enumerate(chunks) if c.volume == volume]
    if not volume_chunks:
        raise SystemExit(f"volume {volume}: no chunks to visualise")
    for _, chunk in volume_chunks:
        if chunk.split:
            raise SystemExit(f"volume {volume}: a word-split chunk cannot be laid out as a range")
        if chunk.stream_from < 0 or chunk.stream_to < chunk.stream_from:
            raise SystemExit(f"volume {volume}: chunk without a stream range")

    first = volume_chunks[0][1].stream_from
    last = volume_chunks[-1][1].stream_to
    owner: dict[int, int] = {}  # sentence position -> ordinal of the chunk it belongs to
    overlap_of: dict[int, int] = {}  # sentence position -> ordinal of the chunk re-reading it
    starts: set[int] = set()  # sentence positions where a chunk begins
    sizes: dict[int, int] = {}
    for ordinal, (_, chunk) in enumerate(volume_chunks, start=1):
        sizes[ordinal] = chunk.chars
        starts.add(chunk.stream_from)
        for position in range(chunk.stream_from, chunk.content_from):
            overlap_of[position] = ordinal
        for position in range(chunk.content_from, chunk.stream_to + 1):
            if position in owner:
                raise SystemExit(f"volume {volume}: sentence {position} belongs to two chunks")
            owner[position] = ordinal
    missing = sum(1 for position in range(first, last + 1) if position not in owner)
    if missing:
        raise SystemExit(f"volume {volume}: {missing} sentences belong to no chunk")

    headings: list[dict] = []
    label_counts: dict[str, int] = {}
    segments: list[dict] = []
    run: dict | None = None
    current_chapter = None
    first_run_of_chapter = False  # no indent on the first paragraph after a heading

    def flush_run() -> None:
        nonlocal run
        if run is not None:
            segments.append(run)
            run = None

    for position in range(first, last + 1):
        sentence = stream[position]
        if sentence.chapter != current_chapter:
            flush_run()
            current_chapter = sentence.chapter
            base = chapter_label(current_chapter)
            label_counts[base] = label_counts.get(base, 0) + 1
            label = base if label_counts[base] == 1 else f"{base} {label_counts[base]}"
            anchor = f"v{volume}-ch-{len(headings) + 1}"
            headings.append({"anchor": anchor, "title": current_chapter, "label": label})
            segments.append({"kind": "heading", "text": current_chapter, "anchor": anchor})
            first_run_of_chapter = True

        overlap = position in overlap_of
        ordinal = overlap_of[position] if overlap else owner[position]
        pstart = sentence.starts_paragraph and not first_run_of_chapter
        first_run_of_chapter = False
        seam = position in starts

        if run is not None and not pstart and run["chunk"] == ordinal and run["overlap"] == overlap:
            run["text"] += " " + sentence.text
            run["seam"] = run["seam"] or seam
        else:
            flush_run()
            run = {
                "kind": "p",
                "text": sentence.text,
                "chunk": ordinal,
                "overlap": overlap,
                "pstart": pstart,
                "seam": seam,
                "size": sizes[ordinal],
            }
    flush_run()

    body_chars = sum(len(seg["text"]) + 1 for seg in segments if seg["kind"] == "p")
    expected = sum(len(stream[p].text) + 1 for p in range(first, last + 1))
    if body_chars != expected:
        raise SystemExit(
            f"volume {volume}: the view drops or repeats text ({body_chars} vs {expected} chars)"
        )
    return {
        "volume": volume,
        "file": file_name,
        "chars": body_chars,
        "sentences": last - first + 1,
        "chunks": len(volume_chunks),
        "overlap_sentences": len(overlap_of),
        "headings": len(headings),
        "chapters": headings,
        "segments": segments,
    }


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile; `statistics.quantiles` needs n > 1."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def starts_with_reference(text: str) -> bool:
    """True when a chunk opens on a word that points backwards.

    A chunk that begins "He therefore resolved..." cannot be embedded on its own:
    the pronoun has no antecedent inside the chunk. These openings are exactly
    what overlap exists to repair, so the sweep measures how many of them overlap
    actually repairs.
    """
    return bool(REFERENCE_START_RE.match(text))


def chunk_metrics(chunks: list[Chunk], target_chars: int, total_stream_chars: int) -> dict:
    sizes = [c.chars for c in chunks]
    if not sizes:
        return {}
    band_low, band_high = target_chars * 0.8, target_chars * 1.2
    overlap_chars = sum(c.overlap_chars for c in chunks)
    # `content_text` excludes the carried overlap, so this counts each corpus
    # sentence exactly once however many chunks repeat it. `+1` stands for the
    # separator that followed the sentence in the stream.
    body_chars = sum(len(c.content_text) + 1 for c in chunks)
    mid_starts = [c for c in chunks if not c.starts_at_paragraph]
    reference_starts = [c for c in mid_starts if starts_with_reference(c.content_start)]
    return {
        "chunks": len(chunks),
        "mean_chars": round(statistics.fmean(sizes), 1),
        "median_chars": round(percentile(sizes, 0.5), 1),
        "p10_chars": round(percentile(sizes, 0.10), 1),
        "p90_chars": round(percentile(sizes, 0.90), 1),
        "min_chars": min(sizes),
        "max_chars": max(sizes),
        "mean_words": round(statistics.fmean(c.words for c in chunks), 1),
        "mean_tokens": round(statistics.fmean(c.tokens for c in chunks), 1),
        "p90_tokens": round(percentile([c.tokens for c in chunks], 0.90), 1),
        # Share of chunks inside +/-20% of the target. Higher is more predictable.
        "in_band_pct": round(100 * sum(1 for s in sizes if band_low <= s <= band_high) / len(sizes), 1),
        # Share of chunk charcount that is repeated from a predecessor.
        "overlap_pct": round(100 * overlap_chars / body_chars, 1) if body_chars else 0.0,
        # Share of chunks that start and end on a paragraph boundary: the most
        # self-contained chunks, with no sentence cut at either edge.
        "whole_paragraph_pct": round(
            100 * sum(1 for c in chunks if c.starts_at_paragraph and c.ends_at_paragraph) / len(sizes), 1
        ),
        # Share of chunks whose content lies inside a single paragraph. A chunk
        # that spans several paragraphs mixes topics and dilutes the embedding.
        "single_paragraph_pct": round(
            100 * sum(1 for c in chunks if c.paragraph_from == c.paragraph_to) / len(sizes), 1
        ),
        "mean_paragraphs_per_chunk": round(
            statistics.fmean(c.paragraph_to - c.paragraph_from + 1 for c in chunks), 2
        ),
        # Share of chunks whose content starts mid-paragraph, and of those, the
        # share that open on a backwards-pointing word.
        "mid_paragraph_start_pct": round(100 * len(mid_starts) / len(sizes), 1),
        "reference_start_pct": round(100 * len(reference_starts) / len(sizes), 1),
        # Of the chunks that open on a reference word, the share that carry the
        # preceding sentences as overlap. This is overlap's measurable benefit.
        "reference_restored_pct": round(
            100 * sum(1 for c in reference_starts if c.overlap_chars > 0) / len(reference_starts), 1
        ) if reference_starts else 0.0,
        # Every corpus sentence must appear in exactly one chunk's own body
        # (overlap copies excluded). This is an invariant, not a statistic: a
        # value below 100 means text was dropped or double-counted.
        "coverage_pct": round(100 * body_chars / total_stream_chars, 2) if total_stream_chars else 0.0,
    }


def score(metrics: dict) -> float:
    """A transparent composite score for ranking configurations.

    Four things matter for retrieval, weighted in that order:
      1. Predictable size -- chunks inside +/-20% of the target embed evenly and
         fit the model's window without one giant chunk dominating recall.
      2. One topic per chunk -- chunks that stay inside a single paragraph do not
         blend two subjects into one vector.
      3. Restored context -- chunks that open on a pronoun or demonstrative have
         the antecedent in front of them because of overlap.
      4. Little repeated text -- every overlapped character is paid for again at
         embedding time; the penalty saturates at 33% overlap, well above any
         sane setting, so it never blocks a useful overlap.
    There is no reward for the *number* of chunks, which would always favour the
    smallest target. The embedding-window constraint is applied separately, in
    `main`, before this score ranks the survivors.
    """
    band = metrics["in_band_pct"] / 100
    single = metrics["single_paragraph_pct"] / 100
    restored = metrics["reference_restored_pct"] / 100
    waste = min(1.0, metrics["overlap_pct"] / 100 * 3)
    return round(0.35 * band + 0.25 * single + 0.20 * restored + 0.20 * (1 - waste), 4)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-chunks", action="store_true", help="skip writing out/chunks.jsonl.gz")
    parser.add_argument("--explain", action="store_true", help="print segmentation decisions")
    args = parser.parse_args()

    paths = sorted(DATA_DIR.glob("*.txt"))
    if len(paths) != 6:
        raise SystemExit(f"expected 6 volumes in {DATA_DIR}, found {len(paths)}")

    volumes = []
    volume_files: dict[int, str] = {}
    all_paragraphs: list[Paragraph] = []
    all_headings: list[str] = []
    for path in paths:
        volume = int(re.search(r"Volume (\d+)", path.name).group(1))
        volume_files[volume] = path.name
        paragraphs, headings = load_volume(path, volume)
        all_paragraphs.extend(paragraphs)
        all_headings.extend(headings)
        chars = sum(p.chars for p in paragraphs)
        para_sizes = [p.chars for p in paragraphs]
        sentence_sizes = [len(s) for p in paragraphs for s in p.sentences]
        volumes.append(
            {
                "volume": volume,
                "file": path.name,
                "chars": chars,
                "words": sum(len(p.text.split()) for p in paragraphs),
                "tokens": round(chars / CHARS_PER_TOKEN),
                "paragraphs": len(paragraphs),
                "headings": len(headings),
                "chapters": len({CHAPTER_RE.match(h).group(1) for h in headings if CHAPTER_RE.match(h)}),
                "mean_paragraph_chars": round(statistics.fmean(para_sizes), 1),
                "median_paragraph_chars": round(percentile(para_sizes, 0.5), 1),
                "p90_paragraph_chars": round(percentile(para_sizes, 0.9), 1),
                "max_paragraph_chars": max(para_sizes),
                "sentences": len(sentence_sizes),
                "median_sentence_chars": round(percentile(sentence_sizes, 0.5), 1),
                "mean_sentences_per_paragraph": round(statistics.fmean(len(p.sentences) for p in paragraphs), 1),
            }
        )
        if args.explain:
            print(f"v{volume}: {len(paragraphs)} paragraphs, {len(headings)} headings, first={paragraphs[0].text[:60]!r}")

    total_chars = sum(v["chars"] for v in volumes)

    # The stream is built once and reused by every configuration in the sweep.
    stream = flatten(all_paragraphs)
    total_stream_chars = sum(len(s.text) + 1 for s in stream)

    sizes_to_try = [400, 600, 800, 1000, 1200, 1500, 1800, 2000, 2500, 3000]
    overlaps_to_try = [0, 100, 150, 200, 300]
    sweep = []
    for target in sizes_to_try:
        for overlap in overlaps_to_try:
            if overlap and overlap > target * MAX_OVERLAP_SHARE:
                continue  # more repetition than context
            chunks = pack(stream, target, overlap)
            metrics = chunk_metrics(chunks, target, total_stream_chars)
            metrics["target_chars"] = target
            metrics["overlap_chars"] = overlap
            metrics["target_tokens"] = round(target / CHARS_PER_TOKEN)
            metrics["overlap_tokens"] = round(overlap / CHARS_PER_TOKEN)
            # Zero overlap has no restoration to measure, so `score` would rank
            # it on the other three terms alone. It is a legitimate candidate.
            metrics["feasible"] = target + HEADING_PREFIX_CHARS <= EMBED_WINDOW_CHARS
            metrics["score"] = score(metrics)
            sweep.append(metrics)

    best = max((m for m in sweep if m["feasible"]), key=lambda m: m["score"])
    # Tie-break toward the smaller overlap: equal scores should not be resolved
    # by dictionary order.
    tied = [m for m in sweep if m["feasible"] and abs(m["score"] - best["score"]) < 1e-9]
    best = min(tied, key=lambda m: (m["overlap_chars"], m["target_chars"]))

    # The score surface is flat enough that reporting a single winning cell would
    # overstate the precision of the result. Everything within 1% of the best is
    # reported as a plateau: any configuration in that range is defensible, which
    # is the useful thing to know when a pipeline has its own constraints.
    plateau = [m for m in sweep if m["feasible"] and m["score"] >= best["score"] * 0.99]
    plateau_summary = {
        "target_min": min(m["target_chars"] for m in plateau),
        "target_max": max(m["target_chars"] for m in plateau),
        "overlap_min": min(m["overlap_chars"] for m in plateau),
        "overlap_max": max(m["overlap_chars"] for m in plateau),
        "configs": len(plateau),
    }

    recommended_chunks = pack(stream, best["target_chars"], best["overlap_chars"])
    # The splitter's contract: no sentence is dropped or duplicated in the body of
    # the chunks. If this moves, every downstream number is wrong, so fail loudly
    # rather than publish a plausible-looking report.
    coverage = chunk_metrics(recommended_chunks, best["target_chars"], total_stream_chars)["coverage_pct"]
    assert coverage == 100.0, f"coverage is {coverage}%, expected 100%"
    per_volume = []
    for volume in volumes:
        v = volume["volume"]
        vchunks = [c for c in recommended_chunks if c.volume == v]
        sizes = [c.chars for c in vchunks]
        per_volume.append(
            {
                "volume": v,
                "chunks": len(vchunks),
                "mean_chars": round(statistics.fmean(sizes), 1),
                "median_chars": round(percentile(sizes, 0.5), 1),
                "mean_tokens": round(statistics.fmean(c.tokens for c in vchunks), 1),
                "chars_per_chunk": round(volume["chars"] / len(vchunks), 1),
            }
        )

    # The full-text views are a separate file: they are display data (the whole
    # corpus and its chunk tags), not statistics.
    volume_views = [
        build_volume_view(stream, recommended_chunks, volume["volume"], volume_files[volume["volume"]])
        for volume in volumes
    ]
    # Report the corpus-table character count in the view headings, not the
    # laid-out length (which also counts the spaces between sentences), so the
    # full-text section and the tables above it agree.
    for volume_view, volume in zip(volume_views, volumes):
        volume_view["corpus_chars"] = volume["chars"]
    corpus_view = {
        "volumes": volume_views,
        "chars": sum(v["chars"] for v in volume_views),
        "corpus_chars": sum(v["corpus_chars"] for v in volume_views),
        "sentences": sum(v["sentences"] for v in volume_views),
        "chunks": sum(v["chunks"] for v in volume_views),
        "overlap_sentences": sum(v["overlap_sentences"] for v in volume_views),
        "headings": sum(v["headings"] for v in volume_views),
    }
    assert corpus_view["chunks"] == len(recommended_chunks), "view drops a chunk"
    assert corpus_view["sentences"] == len(stream), "view drops a sentence"

    para_sizes = [p.chars for p in all_paragraphs]
    sentence_sizes = [len(s) for p in all_paragraphs for s in p.sentences]
    histogram_edges = [0, 250, 500, 750, 1000, 1500, 2000, 3000, 5000, 10**9]
    paragraph_histogram = []
    for low, high in zip(histogram_edges, histogram_edges[1:]):
        count = sum(1 for s in para_sizes if low <= s < high)
        paragraph_histogram.append(
            {"low": low, "high": None if high == 10**9 else high, "count": count,
             "pct": round(100 * count / len(para_sizes), 1)}
        )

    chunk_sizes = [c.chars for c in recommended_chunks]
    chunk_edges = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2200, 10**9]
    chunk_histogram = []
    for low, high in zip(chunk_edges, chunk_edges[1:]):
        count = sum(1 for s in chunk_sizes if low <= s < high)
        chunk_histogram.append(
            {"low": low, "high": None if high == 10**9 else high, "count": count,
             "pct": round(100 * count / len(chunk_sizes), 1)}
        )

    # Sample chunks: one from the start, middle and end of the corpus, so the
    # examples are not all from one stylistic stretch of the book.
    sample_indices = [0, len(recommended_chunks) // 2, len(recommended_chunks) - 1]
    samples = []
    for i in sample_indices:
        c = recommended_chunks[i]
        samples.append(
            {
                "id": f"v{c.volume}-{i:05d}",
                "volume": c.volume,
                "chapter": c.chapter,
                "chars": c.chars,
                "words": c.words,
                "tokens": c.tokens,
                "paragraph_from": c.paragraph_from,
                "paragraph_to": c.paragraph_to,
                "overlap_chars": c.overlap_chars,
                "text": c.text,
            }
        )

    stats = {
        "corpus": {
            "volumes": volumes,
            "chars": total_chars,
            "words": sum(v["words"] for v in volumes),
            "tokens": round(total_chars / CHARS_PER_TOKEN),
            "paragraphs": len(all_paragraphs),
            "sentences": len(sentence_sizes),
            "headings": len(all_headings),
            "unique_chapters": len({CHAPTER_RE.match(h).group(1) for h in all_headings if CHAPTER_RE.match(h)}),
            "mean_paragraph_chars": round(statistics.fmean(para_sizes), 1),
            "median_paragraph_chars": round(percentile(para_sizes, 0.5), 1),
            "p90_paragraph_chars": round(percentile(para_sizes, 0.9), 1),
            "p99_paragraph_chars": round(percentile(para_sizes, 0.99), 1),
            "max_paragraph_chars": max(para_sizes),
            "median_sentence_chars": round(percentile(sentence_sizes, 0.5), 1),
            "p90_sentence_chars": round(percentile(sentence_sizes, 0.9), 1),
            "paragraph_histogram": paragraph_histogram,
            "sentence_histogram_median": round(percentile(sentence_sizes, 0.5), 1),
        },
        "sweep": sweep,
        "best": best,
        "plateau": plateau_summary,
        "constraints": {
            "embed_window_tokens": EMBED_WINDOW_TOKENS,
            "embed_window_chars": EMBED_WINDOW_CHARS,
            "heading_prefix_chars": HEADING_PREFIX_CHARS,
            "max_overlap_share": MAX_OVERLAP_SHARE,
            "chars_per_token": CHARS_PER_TOKEN,
        },
        "per_volume": per_volume,
        "chunk_histogram": chunk_histogram,
        "samples": samples,
        "chunk_count": len(recommended_chunks),
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "volumes_view.json").write_text(
        json.dumps(corpus_view, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    if not args.no_chunks:
        with gzip.open(OUT_DIR / "chunks.jsonl.gz", "wt", encoding="utf-8", newline="\n") as handle:
            for i, c in enumerate(recommended_chunks):
                handle.write(
                    json.dumps(
                        {
                            "id": f"v{c.volume}-{i:05d}",
                            "volume": c.volume,
                            "chapter": c.chapter,
                            "chars": c.chars,
                            "words": c.words,
                            "tokens": c.tokens,
                            "paragraph_from": c.paragraph_from,
                            "paragraph_to": c.paragraph_to,
                            "overlap_chars": c.overlap_chars,
                            "text": c.text,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    print(f"{len(all_paragraphs):,} paragraphs, {total_chars:,} chars, {len(recommended_chunks):,} chunks")
    print(
        f"recommended: {best['target_chars']} chars (~{best['target_tokens']} tokens) "
        f"target, {best['overlap_chars']} chars (~{best['overlap_tokens']} tokens) overlap, "
        f"score {best['score']}"
    )
    print(f"wrote {OUT_DIR / 'stats.json'}")
    print(f"wrote {OUT_DIR / 'volumes_view.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
