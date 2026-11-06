#!/usr/bin/env python3
"""Line-oriented JSON bridge between the Node backend and ChromaDB.

The Node service needs vector retrieval, but the collection was embedded with
all-MiniLM-L6-v2 through the Python default embedding function. Asking a
question therefore has to happen where that function lives, so this process
owns the Chroma client and answers one request per line:

    stdin   {"id": 1, "question": "...", "k": 5}
    stdin   {"id": 2, "op": "get_by_doc_ids", "docIds": ["02_hba1c", ...]}
    stdout  {"type": "ready", "collection": "diabetes", "count": 48, ...}
    stdout  {"id": 1, "ok": true, "results": [{id, document, metadata, distance}]}
    stdout  {"id": 2, "ok": true, "results": [{id, document, metadata}]}
    stdout  {"id": 1, "ok": false, "error": "..."}

Only stdout carries protocol messages; Chroma's own logging and ONNX runtime
warnings go to stderr, which the Node side keeps as the tail of an exit message.

This is a reader. It never creates, deletes or upserts a collection: build the
store first with ``python week06/diabetes/ingest.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# bridge/ -> backend/ -> rag-app/ -> diabetes/
DEFAULT_DB = Path(__file__).resolve().parents[3] / "chroma"
DEFAULT_COLLECTION = "diabetes"


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def fail(message: str) -> int:
    emit({"type": "error", "error": message})
    return 1


def collection_stats(collection) -> dict:
    """Chunk, document, section and character counts for /api/health.

    `chars` is stored by ingest.py for every chunk; using it avoids pulling the
    documents back out of the store just to measure them.
    """
    stored = collection.get(include=["metadatas"])
    metadatas = stored.get("metadatas") or []

    documents: set[str] = set()
    sections: set[tuple[str, str]] = set()
    characters = 0

    for metadata in metadatas:
        if not metadata:
            continue
        doc_id = metadata.get("doc_id")
        section = metadata.get("section")
        if isinstance(doc_id, str):
            documents.add(doc_id)
        if isinstance(section, str):
            sections.add((doc_id or "", section))
        if isinstance(metadata.get("chars"), int):
            characters += metadata["chars"]

    return {
        "chunks": len(metadatas),
        "documents": len(documents),
        "sections": len(sections),
        "characters": characters,
    }


def document_rows(collection, doc_ids: list[str]) -> list[dict]:
    """Every section of the requested documents, in document then section order.

    ``collection.get`` has no ranking, so the order is restored from the request
    (the caller's document rank) and the ``section_index`` metadata written by
    ``ingest.py``. There is no ``distance`` key: these rows were not compared to
    the question, and the Node side substitutes the matched document's score.
    """
    result = collection.get(
        where={"doc_id": {"$in": doc_ids}},
        include=["documents", "metadatas"],
    )

    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    rows = [
        {
            "id": ids[index],
            "document": documents[index] if index < len(documents) else "",
            "metadata": (metadatas[index] if index < len(metadatas) else None) or {},
        }
        for index in range(len(ids))
    ]

    order = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    rows.sort(
        key=lambda row: (
            order.get(row["metadata"].get("doc_id"), len(doc_ids)),
            row["metadata"].get("section_index") or 0,
            row["id"],
        )
    )
    return rows


def main() -> int:
    # Windows consoles default to a legacy code page; the corpus uses
    # typographic punctuation (≥, m², —).
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
            "`python week06/diabetes/ingest.py`, or set CHROMA_DB."
        )

    try:
        import chromadb
        from chromadb.config import Settings
        from chromadb.utils import embedding_functions
    except ImportError as err:
        return fail(
            f"chromadb is not installed for {sys.executable} ({err}). "
            "Install week06/diabetes/requirements.txt, or set CHROMA_PYTHON."
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
            "Build it first with `python week06/diabetes/ingest.py`."
        )

    count = collection.count()
    if count == 0:
        return fail(
            f'collection "{args.collection}" in {db} is empty. '
            "Run `python week06/diabetes/ingest.py`."
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
            op = request.get("op", "search")

            if op == "get_by_doc_ids":
                doc_ids = request.get("docIds")
                if not isinstance(doc_ids, list) or not doc_ids:
                    raise ValueError("docIds must be a non-empty list")
                if len(doc_ids) > 64:
                    raise ValueError("docIds is capped at 64 documents")
                if not all(isinstance(value, str) and value.strip() for value in doc_ids):
                    raise ValueError("docIds entries must be non-empty strings")

                emit(
                    {
                        "id": request_id,
                        "ok": True,
                        "results": document_rows(collection, doc_ids),
                    }
                )
                continue

            if op != "search":
                raise ValueError(f"unknown op {op!r}")

            question = request.get("question")
            if not isinstance(question, str) or question.strip() == "":
                raise ValueError("question must be a non-empty string")

            k = int(request.get("k", 5))
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
