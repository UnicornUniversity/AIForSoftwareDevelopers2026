#!/usr/bin/env python3
"""Line-oriented JSON bridge between the Node backend and ChromaDB.

The Node service needs vector retrieval, but Chroma's collection was embedded
with all-MiniLM-L6-v2 through the Python default embedding function. Asking a
question therefore has to happen where that function lives, so this process owns
the Chroma client and answers one request per line:

    stdin   {"id": 1, "question": "...", "k": 6}
    stdout  {"type": "ready", "collection": "gibbon", "count": 5772, ...}
    stdout  {"id": 1, "ok": true, "results": [{id, document, metadata, distance}]}
    stdout  {"id": 1, "ok": false, "error": "..."}

Only stdout carries protocol messages; Chroma's own logging and ONNX runtime
warnings go to stderr, which the Node side keeps as the tail of an exit message.

This is a reader. It never creates, deletes or upserts a collection: build the
store first with ``python week06/ingest.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[3] / "chroma"
DEFAULT_COLLECTION = "gibbon"


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def fail(message: str) -> int:
    emit({"type": "error", "error": message})
    return 1


def collection_stats(collection) -> dict:
    """Chunk, volume, chapter and character counts for /api/health.

    `chars` is stored by ingest.py for every chunk; using it avoids pulling the
    documents back out of the store just to measure them.
    """
    stored = collection.get(include=["metadatas"])
    metadatas = stored.get("metadatas") or []

    volumes: set[int] = set()
    chapters: set[tuple[int | None, str]] = set()
    characters = 0

    for metadata in metadatas:
        if not metadata:
            continue
        volume = metadata.get("volume")
        chapter = metadata.get("chapter")
        if isinstance(volume, int):
            volumes.add(volume)
        if isinstance(chapter, str):
            chapters.add((volume, chapter))
        if isinstance(metadata.get("chars"), int):
            characters += metadata["chars"]

    return {
        "chunks": len(metadatas),
        "volumes": len(volumes),
        "chapters": len(chapters),
        "characters": characters,
    }


def main() -> int:
    # Windows consoles default to a legacy code page; the corpus is
    # 18th-century English with typographic punctuation.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    args = parser.parse_args()

    db = args.db.resolve()
    if not (db / "chroma.sqlite3").is_file():
        return fail(
            f"no ChromaDB store at {db}. Build it first with "
            "`python week06/ingest.py`, or set CHROMA_DB."
        )

    try:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions
    except ImportError as err:
        return fail(
            f"chromadb is not installed for {sys.executable} ({err}). "
            "Install week06/requirements.txt, or set CHROMA_PYTHON."
        )

    client = chromadb.PersistentClient(
        path=str(db),
        # This is a coursework corpus and should not phone home.
        settings=Settings(anonymized_telemetry=False),
    )

    try:
        collection = client.get_collection(
            name=args.collection,
            # The same local model used by ingest.py: a question must be
            # embedded exactly like the passages were.
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        )
    except Exception as err:  # noqa: BLE001 - shown to the user as-is
        return fail(
            f'collection "{args.collection}" is not in {db} ({err}). '
            "Build it first with `python week06/ingest.py`."
        )

    count = collection.count()
    if count == 0:
        return fail(
            f'collection "{args.collection}" in {db} is empty. '
            "Run `python week06/ingest.py`."
        )

    emit(
        {
            "type": "ready",
            "collection": collection.name,
            "count": count,
            "corpus": collection_stats(collection),
            "metric": "cosine",
        }
    )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            question = request.get("question")
            if not isinstance(question, str) or question.strip() == "":
                raise ValueError("question must be a non-empty string")

            k = int(request.get("k", 6))
            k = max(1, min(k, count))

            result = collection.query(
                query_texts=[question],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )

            ids = (result.get("ids") or [[]])[0]
            documents = (result.get("documents") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]

            rows = [
                {
                    "id": ids[index],
                    "document": documents[index],
                    "metadata": metadatas[index] or {},
                    "distance": (
                        float(distances[index])
                        if index < len(distances) and distances[index] is not None
                        else None
                    ),
                }
                for index in range(len(ids))
            ]

            emit({"id": request_id, "ok": True, "results": rows})
        except Exception as err:  # noqa: BLE001 - one bad request must not stop the bridge
            emit({"id": request_id, "ok": False, "error": str(err)})

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
