"""Semantic chunking over Gibbon's six volumes.

Run from this directory:

    python semantic_chunking.py                 # sweep + best chunk set + stats
    python semantic_chunking.py --backend tfidf # standard library only
    python semantic_chunking.py --percentile 90 --buffer 1 --min-chars 700 --max-chars 1900

Outputs (all under ``out/`` unless ``--out`` is given):

    stats.json         every number the HTML report shows
    chunks.jsonl.gz    the selected chunk set, one JSON object per line
    volumes_view.json  the whole corpus with sentence-level chunk ownership
    cache/*.npy        dense sentence-embedding cache (spaCy / transformer)

The chunk JSONL deliberately carries the same core fields as
``../chunking/out/chunks.jsonl.gz`` (``id``, ``volume``, ``chapter``, ``chars``,
``words``, ``tokens``, ``paragraph_from``, ``paragraph_to``, ``overlap_chars``,
``text``) so the sibling RAG app can consume it by changing ``CHUNKS_PATH``.
Extra fields describe the semantic decision.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import statistics
import sys
from pathlib import Path

import corpus
import segmenter
from embedders import cosine, embed_with_cache, make_embedder
from envfile import load_env

HERE = Path(__file__).resolve().parent

# The grid deliberately includes q=0. On this corpus a high floor (q=95) is
# worse than no floor: the max-chars constraint forces roughly six thousand
# cuts, and when a window has no candidate above the floor the packer has to
# take an arbitrary one. With a low floor it always takes the strongest
# boundary in the window. See README "Why the floor is low".
DEFAULT_PERCENTILES = [0, 60, 70, 80, 90, 95]
DEFAULT_BUFFERS = [0, 1, 2]
DEFAULT_MIN_CHARS = [500, 700]
DEFAULT_MAX_CHARS = [1500, 1700, 1900]
DEFAULT_TARGET = 1500


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Semantic chunking of the six Decline and Fall volumes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--data", type=Path, default=HERE.parent / "data")
    parser.add_argument("--out", type=Path, default=HERE / "out")
    parser.add_argument(
        "--backend",
        default=os.environ.get("SEMANTIC_BACKEND", "auto"),
        choices=["auto", "spacy", "tfidf", "st", "sentence-transformers"],
        help="sentence-embedding backend",
    )
    parser.add_argument("--refresh-cache", action="store_true", help="ignore the dense embedding cache")
    parser.add_argument("--no-sweep", action="store_true", help="use the supplied parameters, do not sweep")
    parser.add_argument("--percentile", type=float, default=0.0,
                        help="candidate-boundary floor as a percentile of the chapter's distances; 0 = no floor")
    parser.add_argument("--buffer", type=int, default=0)
    parser.add_argument("--min-chars", type=int, default=500)
    parser.add_argument("--max-chars", type=int, default=1900)
    parser.add_argument("--target-chars", type=int, default=DEFAULT_TARGET)
    parser.add_argument("--overlap-sentences", type=int, default=1)
    parser.add_argument("--overlap-chars", type=int, default=0, help="cap on carried overlap, 0 = no cap")
    parser.add_argument("--percentiles", default=",".join(map(str, DEFAULT_PERCENTILES)))
    parser.add_argument("--buffers", default=",".join(map(str, DEFAULT_BUFFERS)))
    parser.add_argument("--min-grid", default=",".join(map(str, DEFAULT_MIN_CHARS)))
    parser.add_argument("--max-grid", default=",".join(map(str, DEFAULT_MAX_CHARS)))
    parser.add_argument("--baseline-target", type=int, default=DEFAULT_TARGET)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--limit", type=int, default=0, help="only the first N volumes (development)")
    parser.add_argument("--no-chunks", action="store_true", help="skip chunks.jsonl.gz")
    parser.add_argument("--no-view", action="store_true", help="skip volumes_view.json")
    parser.add_argument("--explain", action="store_true", help="print per-volume decisions to stderr")
    parser.add_argument("--quiet", action="store_true")
    # Optional DeepSeek stages. All off by default and all sampled.
    parser.add_argument("--deepseek-verify", type=int, default=0, metavar="N",
                        help="ask DeepSeek to adjudicate N proposed boundaries")
    parser.add_argument("--deepseek-label", action="store_true",
                        help="write one short topic label per sampled chunk")
    parser.add_argument("--deepseek-questions", type=int, default=0, metavar="N",
                        help="generate N questions for a retrieval sanity check")
    return parser.parse_args(argv)


def _csv_ints(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip()]


def _csv_floats(value: str) -> list[float]:
    return [float(part) for part in value.split(",") if part.strip()]


def log(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def chapter_vector_slices(volumes, vectors) -> dict[str, object]:
    """Slice the flat embedding matrix back into chapters.

    ``Sentence.pos`` is volume-local (it is reassigned at the start of every
    volume), so it cannot index the corpus-wide matrix. The stream order is the
    same order ``flatten_sentences`` produced, so a running offset is both
    simpler and correct.
    """
    slices: dict[str, object] = {}
    offset = 0
    for volume in volumes:
        for chapter in volume.chapters:
            length = len(chapter.sentences)
            if not length:
                continue
            slices[chapter.id] = vectors[offset : offset + length]
            offset += length
    return slices


def ranges_for(
    volumes,
    distances_by_chapter: dict[str, list[float]],
    percentile: float,
    min_chars: int,
    max_chars: int,
    target_chars: int,
) -> dict[str, list[segmenter.Range]]:
    return {
        chapter.id: segmenter.semantic_ranges(
            chapter.sentences,
            distances_by_chapter.get(chapter.id, []),
            percentile,
            min_chars,
            max_chars,
            target_chars,
        )
        for volume in volumes
        for chapter in volume.chapters
    }


def fixed_ranges_for(volumes, target_chars: int) -> dict[str, list[segmenter.Range]]:
    return {
        chapter.id: segmenter.fixed_ranges(chapter.sentences, target_chars)
        for volume in volumes
        for chapter in volume.chapters
    }


def paragraph_ranges_for(volumes, min_chars: int, max_chars: int) -> dict[str, list[segmenter.Range]]:
    return {
        chapter.id: segmenter.paragraph_ranges(chapter.sentences, min_chars, max_chars)
        for volume in volumes
        for chapter in volume.chapters
    }


def build_all(
    volumes,
    ranges_by_chapter: dict[str, list[segmenter.Range]],
    overlap_sentences: int,
    overlap_chars: int,
) -> dict[int, dict[str, list[segmenter.Chunk]]]:
    by_volume: dict[int, dict[str, list[segmenter.Chunk]]] = {}
    counter = 0
    for volume in volumes:
        per_chapter: dict[str, list[segmenter.Chunk]] = {}
        for chapter in volume.chapters:
            ranges = ranges_by_chapter.get(chapter.id, [])
            chunks = segmenter.build_chunks(
                volume,
                chapter,
                ranges,
                overlap_sentences,
                overlap_chars,
                chunk_id_start=counter,
            )
            counter += len(chunks)
            per_chapter[chapter.id] = chunks
        segmenter.validate_chunks(volume, per_chapter)
        by_volume[volume.number] = per_chapter
    return by_volume


def all_chunks(volumes, chunks_by_volume) -> list[segmenter.Chunk]:
    return [
        chunk
        for volume in volumes
        for chapter in volume.chapters
        for chunk in chunks_by_volume[volume.number][chapter.id]
    ]


def sweep(
    volumes,
    distances_by_buffer: dict[int, dict[str, list[float]]],
    percentiles: list[float],
    buffers: list[int],
    min_grid: list[int],
    max_grid: list[int],
    target_chars: int,
    quiet: bool,
) -> list[dict]:
    results: list[dict] = []
    total = len(percentiles) * len(buffers) * len(min_grid) * len(max_grid)
    done = 0
    for buffer_size in buffers:
        distances = distances_by_buffer[buffer_size]
        for percentile in percentiles:
            for min_chars in min_grid:
                for max_chars in max_grid:
                    if min_chars >= max_chars:
                        continue
                    ranges = ranges_for(
                        volumes, distances, percentile, min_chars, max_chars, target_chars
                    )
                    metrics = segmenter.cheap_metrics(volumes, ranges, distances)
                    results.append(
                        {
                            "buffer_size": buffer_size,
                            "percentile": percentile,
                            "min_chars": min_chars,
                            "max_chars": max_chars,
                            "target_chars": target_chars,
                            "metrics": metrics,
                        }
                    )
                    done += 1
                    if not quiet and done % 12 == 0:
                        log(f"[sweep] {done}/{total} configurations", quiet)
    results.sort(key=lambda item: (item["metrics"]["composite"], -item["metrics"]["count"]), reverse=True)
    return results


def histogram(sizes: list[int]) -> list[dict]:
    edges = [0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 3000]
    labels = [
        "<250",
        "250-499",
        "500-749",
        "750-999",
        "1,000-1,249",
        "1,250-1,499",
        "1,500-1,749",
        "1,750-1,999",
        "2,000-2,249",
        "2,250-2,499",
        "2,500-2,999",
        "3,000+",
    ]
    counts = [0] * len(labels)
    for size in sizes:
        for index in range(len(edges) - 1):
            if edges[index] <= size < edges[index + 1]:
                counts[index] += 1
                break
        else:
            counts[-1] += 1
    return [
        {"label": label, "count": count, "pct": round(100.0 * count / max(1, len(sizes)), 1)}
        for label, count in zip(labels, counts)
    ]


def boundary_samples(volumes, chunks_by_volume: dict[int, dict[str, list[segmenter.Chunk]]], limit: int = 8) -> list[dict]:
    rows: list[dict] = []
    for volume in volumes:
        for chapter in volume.chapters:
            chunks = chunks_by_volume[volume.number][chapter.id]
            for index, chunk in enumerate(chunks):
                if chunk.boundary_distance is None:
                    continue
                previous = chunks[index - 1]
                left = [sentence.text for sentence in chapter.sentences[previous.content_end - 2 : previous.content_end]]
                right = [
                    sentence.text
                    for sentence in chapter.sentences[chunk.content_start : chunk.content_start + 2]
                ]
                rows.append(
                    {
                        "volume": volume.number,
                        "chapter": chapter.label,
                        "heading": chapter.heading,
                        "left_chunk": previous.id,
                        "right_chunk": chunk.id,
                        "distance": round(float(chunk.boundary_distance), 4),
                        "threshold": round(float(chunk.threshold or 0.0), 4),
                        "starts_at_paragraph": chunk.starts_at_paragraph,
                        "left": left,
                        "right": right,
                    }
                )
    rows.sort(key=lambda row: row["distance"], reverse=True)
    return rows[:limit]


def sample_chunks(volumes, chunks_by_volume, seed: int = 7) -> list[dict]:
    chunks = all_chunks(volumes, chunks_by_volume)
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda chunk: chunk.chars)
    picks = [
        ("first", chunks[0]),
        ("median-size", ordered[len(ordered) // 2]),
        (
            "strongest-boundary",
            max(
                (chunk for chunk in chunks if chunk.boundary_distance is not None),
                key=lambda chunk: chunk.boundary_distance or 0.0,
                default=chunks[0],
            ),
        ),
    ]
    seen = set()
    out = []
    for label, chunk in picks:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        out.append(
            {
                "label": label,
                "id": chunk.id,
                "volume": chunk.volume,
                "chapter": chunk.chapter_label,
                "heading": chunk.chapter_heading,
                "chars": chunk.chars,
                "content_chars": chunk.content_chars,
                "overlap_chars": chunk.overlap_chars,
                "sentences": chunk.sentence_count,
                "boundary_distance": round(float(chunk.boundary_distance), 4)
                if chunk.boundary_distance is not None
                else None,
                "text": chunk.text[:900] + ("..." if len(chunk.text) > 900 else ""),
            }
        )
    return out


def per_volume_stats(volumes, chunks_by_volume, vectors_by_chapter, distances_by_chapter, seed) -> list[dict]:
    rows = []
    for volume in volumes:
        chunks = [
            chunk
            for chapter in volume.chapters
            for chunk in chunks_by_volume[volume.number][chapter.id]
        ]
        metrics = segmenter.full_metrics(
            [volume],
            chunks_by_volume[volume.number],
            vectors_by_chapter,
            distances_by_chapter,
            sample_size=200,
            seed=seed,
        )
        rows.append(
            {
                "volume": volume.number,
                "chapters": len(volume.chapters),
                "chunks": len(chunks),
                "chars": sum(chunk.chars for chunk in chunks),
                "mean_chars": metrics.get("mean_chars"),
                "median_chars": metrics.get("median_chars"),
                "p90_chars": metrics.get("p90_chars"),
                "overlap_pct": metrics.get("overlap_pct"),
                "boundary_contrast_z": metrics.get("contrast_z"),
                "paragraph_alignment_pct": metrics.get("paragraph_alignment_pct"),
                "separation_drop": metrics.get("separation_drop"),
                "separation_accuracy_pct": metrics.get("separation_accuracy_pct"),
            }
        )
    return rows


def plateau(results: list[dict]) -> dict:
    if not results:
        return {}
    best = results[0]["metrics"]["composite"]
    near = [item for item in results if item["metrics"]["composite"] >= best - 0.02]
    return {
        "within_0.02_of_best": len(near),
        "percentiles": sorted({item["percentile"] for item in near}),
        "buffers": sorted({item["buffer_size"] for item in near}),
        "min_chars": sorted({item["min_chars"] for item in near}),
        "max_chars": sorted({item["max_chars"] for item in near}),
    }


def write_chunks_jsonl(path: Path, chunks: list[segmenter.Chunk], backend: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        for chunk in chunks:
            record = {
                "id": chunk.id,
                "volume": chunk.volume,
                "chapter": chunk.chapter_label,
                "chars": chunk.chars,
                "words": chunk.words,
                "tokens": chunk.tokens,
                "paragraph_from": chunk.paragraph_from,
                "paragraph_to": chunk.paragraph_to,
                "overlap_chars": chunk.overlap_chars,
                "text": chunk.text,
                # Semantic-chunking extras.
                "chapter_id": chunk.chapter_id,
                "chapter_heading": chunk.chapter_heading,
                "content_chars": chunk.content_chars,
                "sentence_count": chunk.sentence_count,
                "boundary_distance": round(float(chunk.boundary_distance), 4)
                if chunk.boundary_distance is not None
                else None,
                "threshold": round(float(chunk.threshold), 4)
                if chunk.threshold is not None
                else None,
                "backend": backend,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_view(path: Path, volumes, chunks_by_volume) -> None:
    views = []
    for volume in volumes:
        views.append(segmenter.build_volume_view(volume, chunks_by_volume[volume.number]))
    path.write_text(json.dumps({"volumes": views}, ensure_ascii=False), encoding="utf-8")


def top_configuration(results: list[dict], args) -> dict:
    if results:
        return results[0]
    return {
        "buffer_size": args.buffer,
        "percentile": args.percentile,
        "min_chars": args.min_chars,
        "max_chars": args.max_chars,
        "target_chars": args.target_chars,
    }


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    volumes = corpus.load_corpus(args.data)
    if args.limit:
        volumes = volumes[: args.limit]
    sentence_stream = corpus.flatten_sentences(volumes)
    texts = [sentence.text for sentence in sentence_stream]
    log(f"[corpus] {len(volumes)} volumes, {len(sentence_stream)} sentences, "
        f"{sum(len(text) for text in texts):,} chars", args.quiet)

    embedder = make_embedder(args.backend, texts, os.environ)
    log(f"[embed] backend: {json.dumps(embedder.describe())}", args.quiet)
    vectors = embed_with_cache(embedder, texts, args.out / "cache", refresh=args.refresh_cache)
    vectors_by_chapter = chapter_vector_slices(volumes, vectors)

    buffers = _csv_ints(args.buffers)
    percentiles = _csv_floats(args.percentiles)
    min_grid = _csv_ints(args.min_grid)
    max_grid = _csv_ints(args.max_grid)

    distances_by_buffer = {
        buffer_size: {
            chapter.id: segmenter.probe_distances(vectors_by_chapter[chapter.id], buffer_size)
            for volume in volumes
            for chapter in volume.chapters
            if chapter.sentences
        }
        for buffer_size in buffers
    }

    if args.no_sweep:
        results = []
        config = {
            "buffer_size": args.buffer,
            "percentile": args.percentile,
            "min_chars": args.min_chars,
            "max_chars": args.max_chars,
            "target_chars": args.target_chars,
        }
        distances = distances_by_buffer.get(args.buffer)
        if distances is None:
            distances = {
                chapter.id: segmenter.probe_distances(vectors_by_chapter[chapter.id], args.buffer)
                for volume in volumes
                for chapter in volume.chapters
            }
            distances_by_buffer[args.buffer] = distances
        ranges = ranges_for(
            volumes, distances, args.percentile, args.min_chars, args.max_chars, args.target_chars
        )
        config["metrics"] = segmenter.cheap_metrics(volumes, ranges, distances)
        results = [config]
    else:
        results = sweep(
            volumes,
            distances_by_buffer,
            percentiles,
            buffers,
            min_grid,
            max_grid,
            args.target_chars,
            args.quiet,
        )
        config = top_configuration(results, args)

    log(
        f"[sweep] best: percentile={config['percentile']} buffer={config['buffer_size']} "
        f"min={config['min_chars']} max={config['max_chars']} "
        f"score={config['metrics']['composite']:.4f}",
        args.quiet,
    )

    # Recompute the winning ranges and build the final chunk set.
    best_distances = distances_by_buffer[config["buffer_size"]]
    best_ranges = ranges_for(
        volumes,
        best_distances,
        config["percentile"],
        config["min_chars"],
        config["max_chars"],
        config["target_chars"],
    )
    chunks_by_volume = build_all(
        volumes,
        best_ranges,
        args.overlap_sentences,
        args.overlap_chars,
    )
    selected = all_chunks(volumes, chunks_by_volume)
    # full_metrics expects a flat {chapter_id: chunks} map.
    flat_chunks = {
        chapter.id: chunks_by_volume[volume.number][chapter.id]
        for volume in volumes
        for chapter in volume.chapters
    }
    best_metrics = segmenter.full_metrics(
        volumes,
        flat_chunks,
        vectors_by_chapter,
        best_distances,
        target_chars=config["target_chars"],
        sample_size=800,
        seed=args.seed,
    )

    # Baselines use the same overlap policy, so differences come from the
    # segmentation rule rather than from how overlap was applied.
    fixed = build_all(volumes, fixed_ranges_for(volumes, args.baseline_target), args.overlap_sentences, args.overlap_chars)
    paragraph = build_all(
        volumes,
        paragraph_ranges_for(volumes, min_chars=500, max_chars=config["max_chars"]),
        args.overlap_sentences,
        args.overlap_chars,
    )
    fixed_flat = {
        chapter.id: fixed[volume.number][chapter.id]
        for volume in volumes
        for chapter in volume.chapters
    }
    paragraph_flat = {
        chapter.id: paragraph[volume.number][chapter.id]
        for volume in volumes
        for chapter in volume.chapters
    }
    fixed_metrics = segmenter.full_metrics(
        volumes, fixed_flat, vectors_by_chapter, best_distances,
        target_chars=args.baseline_target, sample_size=800, seed=args.seed,
    )
    paragraph_metrics = segmenter.full_metrics(
        volumes, paragraph_flat, vectors_by_chapter, best_distances,
        target_chars=config["target_chars"], sample_size=800, seed=args.seed,
    )

    sizes = [chunk.chars for chunk in selected]
    summary = corpus.corpus_summary(volumes)
    stats = {
        "generated_by": "semantic_chunking.py",
        "backend": embedder.describe(),
        "corpus": summary,
        "method": {
            "summary": "Embed sentences, compare adjacent context probes by cosine distance, "
                       "break where the distance is above a per-chapter percentile, then enforce "
                       "size constraints and paragraph preference.",
            "breakpoint_rule": "per-chapter percentile of adjacent-probe cosine distance",
            "buffer_size": config["buffer_size"],
            "percentile": config["percentile"],
            "min_chars": config["min_chars"],
            "max_chars": config["max_chars"],
            "target_chars": config["target_chars"],
            "overlap_sentences": args.overlap_sentences,
            "overlap_chars_cap": args.overlap_chars,
            "hard_boundaries": "chapter and part headings; sentences never cross a heading",
        },
        "constraints": {
            "embed_window_tokens": 512,
            "embed_window_chars": segmenter.EMBED_WINDOW_CHARS,
            "heading_prefix_chars": segmenter.HEADING_PREFIX_CHARS,
            "chars_per_token": segmenter.CHARS_PER_TOKEN,
        },
        "sweep": results,
        "best": {
            "buffer_size": config["buffer_size"],
            "percentile": config["percentile"],
            "min_chars": config["min_chars"],
            "max_chars": config["max_chars"],
            "target_chars": config["target_chars"],
            "metrics": best_metrics,
        },
        "plateau": plateau(results),
        "baselines": {
            "fixed": {
                "params": {"target_chars": args.baseline_target, "overlap_sentences": args.overlap_sentences},
                "metrics": fixed_metrics,
            },
            "paragraph": {
                "params": {"min_chars": 500, "max_chars": config["max_chars"], "overlap_sentences": args.overlap_sentences},
                "metrics": paragraph_metrics,
            },
        },
        "per_volume": per_volume_stats(
            volumes, chunks_by_volume, vectors_by_chapter, best_distances, args.seed
        ),
        "chunk_histogram": histogram(sizes),
        "samples": sample_chunks(volumes, chunks_by_volume),
        "boundary_samples": boundary_samples(volumes, chunks_by_volume),
        "chunk_count": len(selected),
        "deepseek": {"status": "not_requested"},
    }

    # Optional DeepSeek stages. A failure is recorded and never aborts the run.
    if args.deepseek_verify or args.deepseek_label or args.deepseek_questions:
        try:
            from deepseek import run_stages

            stats["deepseek"] = run_stages(
                volumes=volumes,
                chunks_by_volume=chunks_by_volume,
                all_chunks=selected,
                verify=args.deepseek_verify,
                label=args.deepseek_label,
                questions=args.deepseek_questions,
                out_dir=args.out,
                seed=args.seed,
            )
        except Exception as exc:  # noqa: BLE001 - report, never fail the pipeline
            stats["deepseek"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    (args.out / "stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not args.no_chunks:
        write_chunks_jsonl(args.out / "chunks.jsonl.gz", selected, embedder.name)
    if not args.no_view:
        write_view(args.out / "volumes_view.json", volumes, chunks_by_volume)

    if args.explain:
        for volume in volumes:
            chunks = all_chunks([volume], {volume.number: chunks_by_volume[volume.number]})
            boundaries = sorted(
                (chunk for chunk in chunks if chunk.boundary_distance is not None),
                key=lambda chunk: chunk.boundary_distance or 0.0,
                reverse=True,
            )[:3]
            log(
                f"[explain] volume {volume.number}: {len(chunks)} chunks, "
                f"{len(volume.chapters)} chapters; strongest boundaries: "
                + ", ".join(
                    f"{chunk.id} d={chunk.boundary_distance:.3f}" for chunk in boundaries
                ),
                args.quiet,
            )

    log(
        f"[done] {len(selected)} chunks; mean {statistics.fmean(sizes):.0f} chars, "
        f"median {statistics.median(sizes):.0f}, "
        f"overlap {best_metrics.get('overlap_pct', 0):.1f}%; "
        f"wrote {args.out / 'stats.json'}",
        args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
