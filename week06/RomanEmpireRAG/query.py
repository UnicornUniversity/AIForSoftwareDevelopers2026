#!/usr/bin/env python3
"""Query the ChromaDB collection built by ``week06/ingest.py``.

This is a retrieval check, not the course UI: it prints the ranked passages the
vector store returns so the ingest can be verified without starting the Node
backend. The React app continues to use its in-memory BM25 index; see
``week06/CLAUDE.md``.

Usage
-----
    python week06/query.py "Why did the Western Empire fall?"
    python week06/query.py --k 3 "Who was Belisarius?"
    python week06/query.py --volume 4 "Who was Belisarius?"
    python week06/query.py --chapter "Last Victory" "Belisarius"
    python week06/query.py --json "The Antonine constitution"

Collection distances are cosine, so the printed score is ``1 - distance``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "chroma"
DEFAULT_COLLECTION = "gibbon"


def open_collection(db_dir: Path, name: str):
    try:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions
    except ImportError as err:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "chromadb is not installed. Install it with:\n"
            "  python -m pip install -r week06/requirements.txt"
        ) from err

    client = chromadb.PersistentClient(
        path=str(db_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        return client.get_collection(
            name=name,
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        )
    except Exception as err:
        raise SystemExit(
            f"collection {name!r} not found in {db_dir}. "
            "Build it first with: python week06/ingest.py"
        ) from err


def snippet(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[:limit].rstrip()}…"


def main() -> int:
    # The corpus is 18th-century English with typographic punctuation; a Windows
    # console defaults to a legacy code page and would print it as mojibake.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("question", nargs="+", help="question to search for")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="ChromaDB persistence directory")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Chroma collection name")
    parser.add_argument("-k", "--top-k", type=int, default=5, help="number of passages (default: 5)")
    parser.add_argument("--chars", type=int, default=500, help="snippet length per passage")
    parser.add_argument("--volume", type=int, help="only chunks from this volume")
    parser.add_argument(
        "--chapter",
        help="only chunks whose chapter contains this text (case-insensitive)",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        raise SystemExit("question must not be empty")
    if args.top_k < 1:
        raise SystemExit("--top-k must be positive")
    if args.chars < 1:
        raise SystemExit("--chars must be positive")
    if args.volume is not None and args.volume < 1:
        raise SystemExit("--volume must be positive")

    collection = open_collection(args.db, args.collection)
    if collection.count() == 0:
        raise SystemExit(f"collection {args.collection!r} is empty; run week06/ingest.py")

    # Chroma filters the volume natively. String metadata has no `$contains`
    # operator in this version, so a chapter substring is applied after
    # retrieval -- which means fetching every candidate, not just top-k.
    where = {"volume": args.volume} if args.volume is not None else None
    n_results = collection.count() if args.chapter is not None else min(args.top_k, collection.count())
    result = collection.query(
        query_texts=[question],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    needle = args.chapter.lower() if args.chapter is not None else None

    rows = []
    for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances):
        meta = meta or {}
        chapter = meta.get("chapter", "")
        if needle is not None and needle not in chapter.lower():
            continue
        rows.append(
            {
                "rank": len(rows) + 1,
                "id": chunk_id,
                "score": round(1.0 - float(distance), 4),
                "distance": round(float(distance), 4),
                "volume": meta.get("volume"),
                "chapter": chapter,
                "width": len(text),
                "text": snippet(text, args.chars),
            }
        )
        if len(rows) == args.top_k:
            break

    filters = {}
    if args.volume is not None:
        filters["volume"] = args.volume
    if args.chapter is not None:
        filters["chapter"] = args.chapter

    if args.json:
        print(
            json.dumps(
                {"question": question, "filters": filters, "results": rows},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print(f"Q: {question}")
    scope = f"collection {args.collection!r}: {collection.count()} chunks"
    if filters:
        described = ", ".join(f"{key}={value!r}" for key, value in filters.items())
        scope += f" (filters: {described})"
    print(f"{scope}\n")
    if not rows:
        print("No chunk matched the filters.")
        return 0
    for row in rows:
        chapter = f" — {row['chapter']}" if row["chapter"] else ""
        print(f"{row['rank']}. score {row['score']:.4f}  volume {row['volume']}{chapter}  ({row['id']})")
        print(f"   {row['text']}\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
