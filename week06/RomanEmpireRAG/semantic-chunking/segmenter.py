"""Semantic boundary detection and chunk construction.

The mechanism is the standard embedding-distance splitter, made explicit and
constrained:

1.  Embed every sentence (``embedders.py``).
2.  Build a *probe* for each sentence: the L2-normalised mean of the sentence
    vectors in a window of ``buffer_size`` sentences on either side. The probe
    represents local context, not a single sentence, so one short sentence
    cannot move the boundary estimate on its own.
3.  Measure the cosine distance between consecutive probes inside a chapter.
4.  A boundary is *candidate* where that distance is at or above a percentile
    of the chapter's distance distribution (95th by default). This is the
    breakpoint rule used by Kamradt's semantic chunker and LlamaIndex's
    ``SemanticSplitterNodeParser``.
5.  Candidates are filtered by hard size constraints (``min_chars`` /
    ``max_chars``) and chosen greedily left-to-right. The strongest candidate
    inside the legal window wins; a candidate that lands on a paragraph start
    gets a small bonus, because paragraph starts are the only structural signal
    in this corpus that is independent of the embedding.
6.  Overlap is carried backwards in whole sentences from the previous chunk,
    never across a chapter heading.

Chapters are hard boundaries. The data has explicit chapter/part headings, and
merging across them would be wrong regardless of what the vectors say.
"""

from __future__ import annotations

import bisect
import random
import statistics
from dataclasses import dataclass

from embedders import cosine, normalize, vec_mean

CHARS_PER_TOKEN = 4.0
# A chunk must fit a 512-token embedding window together with its overlap and a
# small chapter breadcrumb. 2,048 chars is the chars/4 estimate of 512 tokens.
EMBED_WINDOW_CHARS = 2_048
HEADING_PREFIX_CHARS = 110


@dataclass
class Range:
    """A half-open sentence range within one chapter."""

    start: int
    end: int
    boundary_distance: float | None = None
    threshold: float | None = None

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Chunk:
    id: str
    volume: int
    chapter_id: str
    chapter_label: str
    chapter_heading: str
    index_in_chapter: int
    content_start: int  # chapter-local sentence index, inclusive
    content_end: int  # chapter-local sentence index, exclusive
    overlap_start: int
    overlap_end: int
    text: str
    content_text: str
    overlap_text: str
    boundary_distance: float | None
    threshold: float | None
    starts_at_paragraph: bool
    paragraph_from: int
    paragraph_to: int

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def content_chars(self) -> int:
        return len(self.content_text)

    @property
    def overlap_chars(self) -> int:
        return len(self.overlap_text)

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def tokens(self) -> int:
        return round(self.chars / CHARS_PER_TOKEN)

    @property
    def sentence_count(self) -> int:
        return self.content_end - self.content_start


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def char_prefix(sentences) -> list[int]:
    """Prefix sums of the *joined* text, not of raw sentence lengths.

    Sentences are joined with one space, so a range of ``k`` sentences is
    ``sum(len) + k - 1`` characters. Counting raw lengths understates a long
    chunk by one character per sentence boundary; on a 66-sentence footnote
    cluster that was 65 characters, enough to push the chunk (and its chapter
    breadcrumb) past the 512-token window while the size check still said it
    fit. ``prefix[i]`` is the length of ``" ".join(texts[:i])``.
    """
    prefix = [0]
    for index, sentence in enumerate(sentences):
        prefix.append(prefix[-1] + sentence.chars + (1 if index else 0))
    return prefix


def probe_distances(vectors, buffer_size: int) -> list[float]:
    """Cosine distance between consecutive context probes.

    ``vectors`` are L2-normalised sentence vectors. The probe for sentence *i*
    is the mean of vectors ``[i-buffer, i+buffer]``; the returned list has one
    value per adjacent pair, so ``distance[i-1]`` is the boundary between
    sentences ``i-1`` and ``i``.
    """
    n = len(vectors)
    if n < 2:
        return []
    buffer_size = max(0, int(buffer_size))

    if isinstance(vectors[0], dict):
        probes = [
            normalize(vec_mean(vectors[max(0, i - buffer_size) : min(n, i + buffer_size + 1)]))
            for i in range(n)
        ]
        return [1.0 - cosine(probes[i - 1], probes[i]) for i in range(1, n)]

    import numpy as np

    matrix = np.asarray(vectors, dtype="float32")
    prefix = np.vstack([np.zeros((1, matrix.shape[1]), dtype="float32"), np.cumsum(matrix, axis=0)])
    distances = np.empty(n - 1, dtype="float32")
    for i in range(1, n):
        # Probe i-1 covers [i-1-buffer, i+buffer); probe i covers [i-buffer, i+buffer+1).
        a_start = max(0, i - 1 - buffer_size)
        a_end = min(n, i + buffer_size)
        b_start = max(0, i - buffer_size)
        b_end = min(n, i + buffer_size + 1)
        a = prefix[a_end] - prefix[a_start]
        b = prefix[b_end] - prefix[b_start]
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        distances[i - 1] = 1.0 - float(np.dot(a, b)) / norm if norm else 0.0
    return distances.tolist()


# ---------------------------------------------------------------------------
# Segmentation strategies
# ---------------------------------------------------------------------------


def semantic_ranges(
    sentences,
    distances: list[float],
    percentile_threshold: float,
    min_chars: int,
    max_chars: int,
    target_chars: int,
) -> list[Range]:
    """Split one chapter at the strongest legal semantic boundaries."""
    n = len(sentences)
    if n == 0:
        return []
    if n == 1:
        return [Range(0, 1)]

    cum = char_prefix(sentences)
    threshold = percentile(distances, percentile_threshold)
    candidates = [
        position
        for position, distance in enumerate(distances, start=1)
        if distance >= threshold
    ]
    candidate_set = set(candidates)

    ranges: list[Range] = []
    start = 0
    while start < n:
        remaining = cum[n] - cum[start]
        if n - start == 1 or remaining <= max_chars:
            end = n
        else:
            # First boundary that can satisfy min_chars, and last one that
            # still fits max_chars. When a single sentence is longer than
            # max_chars, the hard cap wins and the chunk is allowed to oversize.
            low = bisect.bisect_left(cum, cum[start] + min_chars, lo=start + 1, hi=n)
            low = min(low, n - 1)
            high = bisect.bisect_right(cum, cum[start] + max_chars, lo=start + 1, hi=n) - 1
            if high <= start:
                end = start + 1  # pathological single sentence
            elif high < low:
                end = high  # cannot satisfy both; max_chars is the hard cap
            else:
                window = [
                    position
                    for position in range(low, high + 1)
                    if position in candidate_set
                ]
                if window:
                    end = max(
                        window,
                        key=lambda position: _boundary_score(
                            position, start, cum, distances, sentences, target_chars
                        ),
                    )
                else:
                    end = _structural_fallback(start, low, high, cum, sentences, target_chars)
        end = min(max(end, start + 1), n)
        boundary = distances[end - 1] if end < n else None
        ranges.append(
            Range(
                start=start,
                end=end,
                boundary_distance=boundary,
                threshold=threshold,
            )
        )
        start = end

    return ranges


def _boundary_score(
    position: int,
    start: int,
    cum: list[int],
    distances: list[float],
    sentences,
    target_chars: int,
) -> float:
    if position <= 0 or position > len(distances):
        return -1.0
    semantic = distances[position - 1]
    paragraph_bonus = 0.03 if sentences[position].starts_paragraph else 0.0
    size = cum[position] - cum[start]
    size_penalty = 0.03 * abs(size - target_chars) / max(1, target_chars)
    return semantic + paragraph_bonus - size_penalty


def _structural_fallback(
    start: int, low: int, high: int, cum: list[int], sentences, target_chars: int
) -> int:
    positions = list(range(low, high + 1))
    paragraph_positions = [
        position
        for position in positions
        if position < len(sentences) and sentences[position].starts_paragraph
    ]
    pool = paragraph_positions or positions
    return min(pool, key=lambda position: abs((cum[position] - cum[start]) - target_chars))


def fixed_ranges(sentences, target_chars: int) -> list[Range]:
    """Size-only baseline: pack whole sentences to roughly ``target_chars``."""
    n = len(sentences)
    if n == 0:
        return []
    cum = char_prefix(sentences)
    ranges: list[Range] = []
    start = 0
    while start < n:
        end = start + 1
        while end < n and cum[end + 1] - cum[start] <= target_chars:
            end += 1
        if end < n:
            paragraph_starts = [
                position
                for position in range(start + 1, end + 1)
                if sentences[position].starts_paragraph
            ]
            if paragraph_starts:
                end = paragraph_starts[-1]
        ranges.append(Range(start, end))
        start = end
    return ranges


def paragraph_ranges(sentences, min_chars: int, max_chars: int) -> list[Range]:
    """Structural baseline: merge whole paragraphs until ``min_chars``.

    A paragraph larger than ``max_chars`` is split at sentence boundaries; the
    baseline is not allowed to emit chunks that a 512-token window cannot hold.
    """
    n = len(sentences)
    if n == 0:
        return []
    cum = char_prefix(sentences)
    boundaries = [i for i in range(1, n) if sentences[i].starts_paragraph] + [n]
    ranges: list[Range] = []
    start = 0
    for boundary in boundaries:
        size = cum[boundary] - cum[start]
        if size < min_chars and boundary != n:
            continue
        if size > max_chars:
            ranges.extend(_split_oversize(sentences, start, boundary, max_chars))
        else:
            ranges.append(Range(start, boundary))
        start = boundary
    if start < n:
        ranges.append(Range(start, n))
    return ranges


def _split_oversize(sentences, start: int, end: int, max_chars: int) -> list[Range]:
    local = sentences[start:end]
    return [
        Range(start + item.start, start + item.end)
        for item in fixed_ranges(local, max_chars)
    ]


# ---------------------------------------------------------------------------
# Chunk construction
# ---------------------------------------------------------------------------


def build_chunks(
    volume,
    chapter,
    ranges: list[Range],
    overlap_sentences: int,
    overlap_chars: int,
    chunk_id_start: int = 0,
    max_total_chars: int = EMBED_WINDOW_CHARS - HEADING_PREFIX_CHARS,
) -> list[Chunk]:
    sentences = chapter.sentences
    cum = char_prefix(sentences)
    chunks: list[Chunk] = []

    for index, item in enumerate(ranges):
        carry = 0
        if index > 0:
            carry = min(max(0, overlap_sentences), item.start - ranges[index - 1].start)
            while carry > 0 and overlap_chars and (cum[item.start] - cum[item.start - carry]) > overlap_chars:
                carry -= 1
            # Keep content + overlap inside the embedding window. The content
            # itself is already <= max_chars by construction; this only trims a
            # long overlap sentence.
            while carry > 0 and (cum[item.end] - cum[item.start - carry]) > max_total_chars:
                carry -= 1

        overlap_start = item.start - carry
        content = sentences[item.start : item.end]
        overlap = sentences[overlap_start : item.start]
        content_text = " ".join(sentence.text for sentence in content)
        overlap_text = " ".join(sentence.text for sentence in overlap)
        text = f"{overlap_text} {content_text}".strip() if overlap_text else content_text

        chunks.append(
            Chunk(
                id=f"v{volume.number}-{chunk_id_start + len(chunks):05d}",
                volume=volume.number,
                chapter_id=chapter.id,
                chapter_label=chapter.label,
                chapter_heading=chapter.heading,
                index_in_chapter=index,
                content_start=item.start,
                content_end=item.end,
                overlap_start=overlap_start,
                overlap_end=item.start,
                text=text,
                content_text=content_text,
                overlap_text=overlap_text,
                boundary_distance=item.boundary_distance,
                threshold=item.threshold,
                starts_at_paragraph=content[0].starts_paragraph if content else False,
                paragraph_from=content[0].paragraph if content else 0,
                paragraph_to=content[-1].paragraph if content else 0,
            )
        )
    return chunks


def build_volume_view(volume, chunks_by_chapter: dict[str, list[Chunk]]) -> dict:
    """Every sentence exactly once, tagged with its owning chunk.

    A sentence in the overlap is repeated inside the next chunk's text but is
    shown once here, flagged `overlap`, so the report does not duplicate it.
    """
    chapters = []
    for chapter in volume.chapters:
        chunks = chunks_by_chapter.get(chapter.id, [])
        owner: list[Chunk | None] = [None] * len(chapter.sentences)
        overlap = [False] * len(chapter.sentences)
        for chunk in chunks:
            for index in range(chunk.content_start, chunk.content_end):
                owner[index] = chunk
            for index in range(chunk.overlap_start, chunk.overlap_end):
                overlap[index] = True
        sentences = []
        for index, sentence in enumerate(chapter.sentences):
            chunk = owner[index]
            sentences.append(
                {
                    "text": sentence.text,
                    "chunk_id": chunk.id if chunk else None,
                    "chunk_index": chunk.index_in_chapter if chunk else None,
                    "overlap": overlap[index],
                    "starts_paragraph": sentence.starts_paragraph,
                    "boundary": chunk.boundary_distance if chunk else None,
                }
            )
        chapters.append(
            {
                "id": chapter.id,
                "label": chapter.label,
                "heading": chapter.heading,
                "sentences": sentences,
            }
        )
    return {
        "volume": volume.number,
        "title": volume.title,
        "chapters": chapters,
    }


def validate_chunks(volume, chunks_by_chapter: dict[str, list[Chunk]]) -> None:
    """Fail loudly if a chunking run produced an unusable chunk set."""
    for chapter in volume.chapters:
        chunks = chunks_by_chapter[chapter.id]
        if not chunks:
            raise AssertionError(f"{volume.number}/{chapter.id}: no chunks")
        if chunks[0].content_start != 0:
            raise AssertionError(f"{volume.number}/{chapter.id}: first chunk does not start at 0")
        if chunks[-1].content_end != len(chapter.sentences):
            raise AssertionError(f"{volume.number}/{chapter.id}: last chunk does not cover the chapter")
        for previous, current in zip(chunks, chunks[1:]):
            if previous.content_end != current.content_start:
                raise AssertionError(
                    f"{volume.number}/{chapter.id}: gap or overlap between {previous.id} and {current.id}"
                )
        for chunk in chunks:
            if chunk.content_end <= chunk.content_start:
                raise AssertionError(f"{chunk.id}: empty content")
            if chunk.overlap_end and chunk.overlap_end > chunk.content_start:
                raise AssertionError(f"{chunk.id}: overlap crosses content")
            if chunk.chars > EMBED_WINDOW_CHARS:
                raise AssertionError(f"{chunk.id}: {chunk.chars} chars exceeds the embedding window")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def size_metrics(sizes: list[int], target_chars: int = 1_500) -> dict:
    if not sizes:
        return {}
    ordered = sorted(sizes)
    return {
        "count": len(sizes),
        "mean_chars": round(statistics.fmean(sizes), 1),
        "median_chars": round(statistics.median(sizes), 1),
        "p10_chars": round(percentile(ordered, 10), 1),
        "p90_chars": round(percentile(ordered, 90), 1),
        "min_chars": min(sizes),
        "max_chars": max(sizes),
        "in_band_pct": round(
            100.0 * sum(1 for size in sizes if 500 <= size <= 2_000) / len(sizes), 1
        ),
        "over_window_pct": round(
            100.0 * sum(1 for size in sizes if size > EMBED_WINDOW_CHARS) / len(sizes), 1
        ),
        "target_chars": target_chars,
    }


def cheap_metrics(volumes, ranges_by_chapter: dict[str, list[Range]], distances_by_chapter: dict[str, list[float]]) -> dict:
    """Metrics that need only the ranges; used to rank the 72-config sweep."""
    sizes: list[int] = []
    chosen: list[float] = []
    all_distances: list[float] = []
    boundaries = 0
    paragraph_boundaries = 0
    forced_boundaries = 0
    floored_boundaries = 0
    chapter_count = 0
    total_sentences = 0
    total_chars = 0

    for volume in volumes:
        for chapter in volume.chapters:
            ranges = ranges_by_chapter.get(chapter.id, [])
            if not ranges:
                continue
            chapter_count += 1
            cum = char_prefix(chapter.sentences)
            distances = distances_by_chapter.get(chapter.id, [])
            all_distances.extend(distances)
            n = len(chapter.sentences)
            for item in ranges:
                size = cum[item.end] - cum[item.start]
                sizes.append(size)
                total_chars += size
                total_sentences += item.length
                if item.end < n:
                    boundaries += 1
                    if chapter.sentences[item.end].starts_paragraph:
                        paragraph_boundaries += 1
                    # Baselines do not carry a `boundary_distance`; look the
                    # distance up at the position where they cut, so every
                    # strategy is measured on the same vector field.
                    if item.end - 1 < len(distances):
                        distance = distances[item.end - 1]
                        chosen.append(distance)
                        # A cut below the chapter's own floor is a cut the
                        # percentile rule did not endorse: the size constraints
                        # forced it. Baselines have no threshold and are not
                        # counted here.
                        if item.threshold is not None:
                            floored_boundaries += 1
                            if distance < item.threshold:
                                forced_boundaries += 1

    metrics = size_metrics(sizes)
    mean_all = statistics.fmean(all_distances) if all_distances else 0.0
    stdev_all = statistics.pstdev(all_distances) if len(all_distances) > 1 else 1.0
    mean_chosen = statistics.fmean(chosen) if chosen else 0.0
    contrast_z = (mean_chosen - mean_all) / (stdev_all or 1.0)
    alignment = paragraph_boundaries / boundaries if boundaries else 0.0
    estimated_overlap = 0.0
    if sizes and chapter_count and total_sentences:
        # One carried sentence per non-first chunk, at the corpus mean sentence
        # length; exact overlap is measured for the winning config later.
        mean_sentence = total_chars / total_sentences
        estimated_overlap = min(
            0.20, mean_sentence * max(0, len(sizes) - chapter_count) / max(1, total_chars)
        )
    metrics.update(
        {
            "boundary_count": boundaries,
            "mean_boundary_distance": round(mean_chosen, 4),
            "mean_all_distance": round(mean_all, 4),
            "contrast_z": round(contrast_z, 3),
            "paragraph_alignment_pct": round(100.0 * alignment, 1),
            "forced_boundary_pct": (
                round(100.0 * forced_boundaries / floored_boundaries, 1)
                if floored_boundaries
                else None
            ),
            "estimated_overlap_pct": round(100.0 * estimated_overlap, 1),
            "composite": round(
                0.40 * (metrics["in_band_pct"] / 100.0)
                + 0.35 * max(0.0, min(1.0, contrast_z / 3.0))
                + 0.15 * alignment
                + 0.10 * (1.0 - estimated_overlap),
                4,
            ),
        }
    )
    return metrics


def full_metrics(
    volumes,
    chunks_by_chapter: dict[str, list[Chunk]],
    vectors_by_chapter: dict[str, object],
    distances_by_chapter: dict[str, list[float]],
    target_chars: int = 1_500,
    sample_size: int = 800,
    seed: int = 7,
) -> dict:
    """Size, boundary and coherence metrics for one chunk set."""
    sizes = [chunk.chars for volume in volumes for chapter in volume.chapters for chunk in chunks_by_chapter[chapter.id]]
    metrics = size_metrics(sizes, target_chars)

    chosen: list[float] = []
    all_distances: list[float] = []
    boundaries = 0
    paragraph_boundaries = 0
    forced_boundaries = 0
    floored_boundaries = 0
    reference_starts = 0
    reference_with_overlap = 0
    total_overlap = 0
    total_content = 0

    for volume in volumes:
        for chapter in volume.chapters:
            chunks = chunks_by_chapter[chapter.id]
            distances = distances_by_chapter.get(chapter.id, [])
            all_distances.extend(distances)
            n = len(chapter.sentences)
            for chunk in chunks:
                total_overlap += chunk.overlap_chars
                total_content += chunk.content_chars
                if chunk.content_start > 0:
                    boundaries += 1
                    if chapter.sentences[chunk.content_start].starts_paragraph:
                        paragraph_boundaries += 1
                    position = chunk.content_start - 1
                    if position < len(distances):
                        distance = distances[position]
                        chosen.append(distance)
                        if chunk.threshold is not None:
                            floored_boundaries += 1
                            if distance < chunk.threshold:
                                forced_boundaries += 1
                first = chapter.sentences[chunk.content_start]
                if first.starts_with_reference:
                    reference_starts += 1
                    if chunk.overlap_chars > 0:
                        reference_with_overlap += 1

    mean_all = statistics.fmean(all_distances) if all_distances else 0.0
    stdev_all = statistics.pstdev(all_distances) if len(all_distances) > 1 else 1.0
    mean_chosen = statistics.fmean(chosen) if chosen else 0.0
    metrics.update(
        {
            "boundary_count": boundaries,
            "mean_boundary_distance": round(mean_chosen, 4),
            "mean_all_distance": round(mean_all, 4),
            "contrast_z": round((mean_chosen - mean_all) / (stdev_all or 1.0), 3),
            "paragraph_alignment_pct": round(100.0 * paragraph_boundaries / boundaries, 1) if boundaries else 0.0,
            "forced_boundary_pct": (
                round(100.0 * forced_boundaries / floored_boundaries, 1)
                if floored_boundaries
                else None
            ),
            "overlap_pct": round(100.0 * total_overlap / max(1, total_content), 1),
            "reference_start_pct": round(100.0 * reference_starts / max(1, len(sizes)), 1),
            "reference_with_overlap_pct": round(
                100.0 * reference_with_overlap / max(1, reference_starts), 1
            ),
        }
    )

    separation = _boundary_separation(
        volumes, chunks_by_chapter, vectors_by_chapter, sample_size, seed
    )
    metrics.update(separation)
    metrics["composite"] = round(
        0.30 * (metrics["in_band_pct"] / 100.0)
        + 0.25 * max(0.0, min(1.0, metrics["contrast_z"] / 2.0))
        + 0.20 * (metrics.get("separation_accuracy_pct", 0.0) / 100.0)
        + 0.15 * (metrics["paragraph_alignment_pct"] / 100.0)
        + 0.10 * (1.0 - metrics["overlap_pct"] / 100.0),
        4,
    )
    return metrics


def _boundary_separation(
    volumes, chunks_by_chapter, vectors_by_chapter, sample_size: int, seed: int
) -> dict:
    """Is the similarity drop at a cut larger than the drop nearby?

    Comparing a boundary pair with *random* pairs inside a chunk is unfair:
    adjacent sentences are more similar than random pairs wherever they sit.
    The fair comparison is local. At a cut between sentence ``i-1`` and ``i``,
    compare the cross-boundary cosine with the adjacent pair just inside each
    side (``i-2,i-1`` and ``i,i+1``). A meaningful boundary is a local dip.

    ``separation_accuracy_pct`` is the share of cuts where that dip is positive.
    No centroid is involved, so the metric is not biased by chunk size.
    """
    random.seed(seed + 1)
    interior: list[float] = []
    boundary: list[float] = []
    local_drops: list[float] = []

    for volume in volumes:
        for chapter in volume.chapters:
            vectors = vectors_by_chapter.get(chapter.id)
            chunks = chunks_by_chapter[chapter.id]
            if vectors is None:
                continue
            for index, chunk in enumerate(chunks):
                pairs = [
                    (position, position + 1)
                    for position in range(chunk.content_start, chunk.content_end - 1)
                ]
                if pairs:
                    for a, b in random.sample(pairs, min(3, len(pairs))):
                        interior.append(cosine(vectors[a], vectors[b]))
                if index + 1 < len(chunks):
                    next_chunk = chunks[index + 1]
                    cut = chunk.content_end
                    cross = cosine(vectors[cut - 1], vectors[cut])
                    boundary.append(cross)
                    neighbours = []
                    if cut - 2 >= chunk.content_start:
                        neighbours.append(cosine(vectors[cut - 2], vectors[cut - 1]))
                    if cut + 1 < next_chunk.content_end:
                        neighbours.append(cosine(vectors[cut], vectors[cut + 1]))
                    if neighbours:
                        local_drops.append(statistics.fmean(neighbours) - cross)

    interior_mean = statistics.fmean(interior) if interior else 0.0
    boundary_mean = statistics.fmean(boundary) if boundary else 0.0
    return {
        "separation_interior": round(interior_mean, 4),
        "separation_boundary": round(boundary_mean, 4),
        "separation_drop": round(interior_mean - boundary_mean, 4),
        "separation_local_drop": round(statistics.fmean(local_drops), 4) if local_drops else 0.0,
        "separation_accuracy_pct": round(
            100.0 * sum(1 for value in local_drops if value > 0) / max(1, len(local_drops)),
            1,
        ),
        "separation_pairs": len(interior) + len(boundary),
    }
