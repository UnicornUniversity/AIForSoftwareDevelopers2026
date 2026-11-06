"""LlamaIndex alternative: the reference SemanticSplitterNodeParser.

This script is intentionally separate from the core pipeline. It runs
LlamaIndex's own implementation over the same chapters and writes a chunk file
with the same basic schema, so the report can compare the two segmentations.

Install the optional dependencies first::

    pip install -r requirements-optional.txt

Then, from this directory::

    python llamaindex_pipeline.py                  # all six volumes
    python llamaindex_pipeline.py --limit 1        # quick smoke test
    python llamaindex_pipeline.py --backend openai # needs OPENAI_API_KEY

The default embedding backend is a local Hugging Face sentence-transformer
(`BAAI/bge-small-en-v1.5`), downloaded on first use. No API key is required for
that path. `--backend openai` reads `OPENAI_API_KEY` and `OPENAI_EMBED_MODEL`
from `.env`.

LlamaIndex is a *cosine-similarity splitter*, like the core pipeline: it embeds
buffered sentence groups and breaks where adjacent embeddings diverge above a
percentile. The differences that matter here are that it applies no minimum or
maximum chunk size, has no overlap, and uses its own sentence splitter. The
comparison in the report is therefore a comparison of defaults, not of a better
implementation.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from corpus import load_corpus
from envfile import env, env_int, load_env
from segmenter import size_metrics

HERE = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LlamaIndex SemanticSplitter baseline")
    parser.add_argument("--data", type=Path, default=HERE.parent / "data")
    parser.add_argument("--out", type=Path, default=HERE / "out")
    parser.add_argument("--backend", default=env("LLAMAINDEX_EMBED_BACKEND", "huggingface"),
                        choices=["huggingface", "openai"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--percentile", type=float,
                        default=float(env("LLAMAINDEX_BREAKPOINT_PERCENTILE", "95")))
    parser.add_argument("--buffer", type=int, default=env_int("LLAMAINDEX_BUFFER_SIZE", 1))
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def build_embed_model(args):
    if args.backend == "openai":
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding
        except ImportError as exc:
            raise SystemExit(
                "LlamaIndex's OpenAI embedding package is missing.\n"
                "  pip install -r requirements-optional.txt"
            ) from exc
        key = env("OPENAI_API_KEY")
        if not key:
            raise SystemExit("OPENAI_API_KEY is not set (needed for --backend openai)")
        return OpenAIEmbedding(
            model=args.model or env("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=key,
            api_base=env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    except ImportError as exc:
        raise SystemExit(
            "LlamaIndex's Hugging Face embedding package is missing.\n"
            "  pip install -r requirements-optional.txt"
        ) from exc
    return HuggingFaceEmbedding(
        model_name=args.model or env("LLAMAINDEX_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        cache_folder=str(HERE / "out" / "hf-cache"),
        # A token helps only on a rate-limited network; it is optional.
        token=env("HF_TOKEN") or None,
    )


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    try:
        from llama_index.core import Document
        from llama_index.core.node_parser import SemanticSplitterNodeParser
    except ImportError:
        print(
            "LlamaIndex is not installed.\n"
            "  pip install -r requirements-optional.txt\n"
            "The core pipeline (`python semantic_chunking.py`) runs without it.",
            file=sys.stderr,
        )
        return 2

    volumes = load_corpus(args.data)
    if args.limit:
        volumes = volumes[: args.limit]

    documents = []
    lookup = {}
    for volume in volumes:
        for chapter in volume.chapters:
            if not chapter.sentences:
                continue
            documents.append(
                Document(
                    text=chapter.text,
                    metadata={
                        "volume": volume.number,
                        "chapter_id": chapter.id,
                        "chapter": chapter.label,
                        "heading": chapter.heading,
                    },
                    id_=chapter.id,
                )
            )
            lookup[chapter.id] = chapter

    embed_model = build_embed_model(args)
    parser = SemanticSplitterNodeParser(
        buffer_size=args.buffer,
        breakpoint_percentile_threshold=args.percentile,
        embed_model=embed_model,
    )
    print(
        f"[llamaindex] {len(documents)} chapters, buffer={args.buffer}, "
        f"percentile={args.percentile}, backend={args.backend}",
        file=sys.stderr,
    )
    nodes = parser.get_nodes_from_documents(documents)

    records = []
    sizes = []
    paragraph_starts = 0
    for index, node in enumerate(nodes):
        metadata = node.metadata or {}
        text = node.get_content().strip()
        if not text:
            continue
        chapter = lookup.get(metadata.get("chapter_id"))
        starts_paragraph = False
        if chapter is not None:
            probe = " ".join(text.split())[:40]
            starts_paragraph = any(
                " ".join(paragraph.sentences[0].split())[:40] == probe
                for paragraph in chapter.paragraphs
                if paragraph.sentences
            )
            paragraph_starts += int(starts_paragraph)
        sizes.append(len(text))
        records.append(
            {
                "id": f"li-{index:05d}",
                "volume": metadata.get("volume"),
                "chapter": metadata.get("chapter", ""),
                "chapter_id": metadata.get("chapter_id", ""),
                "chars": len(text),
                "words": len(text.split()),
                "tokens": round(len(text) / 4.0),
                "paragraph_from": None,
                "paragraph_to": None,
                "overlap_chars": 0,
                "text": text,
                "method": "llamaindex SemanticSplitterNodeParser",
                "starts_at_paragraph": starts_paragraph,
            }
        )

    stats = {
        "status": "ok",
        "method": "llama_index.core.node_parser.SemanticSplitterNodeParser",
        "backend": args.backend,
        "model": args.model
        or (
            env("OPENAI_EMBED_MODEL", "text-embedding-3-small")
            if args.backend == "openai"
            else env("LLAMAINDEX_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
        ),
        "params": {
            "buffer_size": args.buffer,
            "breakpoint_percentile_threshold": args.percentile,
            "chunk_size": None,
            "chunk_overlap": 0,
        },
        "chunks": len(records),
        "size": size_metrics(sizes),
        "paragraph_alignment_pct": round(100.0 * paragraph_starts / max(1, len(records)), 1),
        "overlap_pct": 0.0,
        "volumes": len(volumes),
    }

    with gzip.open(args.out / "llamaindex_chunks.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.out / "llamaindex_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"[llamaindex] {len(records)} nodes; mean {stats['size'].get('mean_chars')} chars, "
        f"p90 {stats['size'].get('p90_chars')}; wrote {args.out / 'llamaindex_stats.json'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
