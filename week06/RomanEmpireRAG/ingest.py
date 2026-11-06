#!/usr/bin/env python3
"""Split the six Gibbon volumes into chunks and store them in ChromaDB.

The segmentation is imported from ``week06/chunking/chunking.py`` -- the same
code that produced the report -- so the vectors cover exactly the chunks the
study analysed, with the same chapter headings, sentence boundaries and
overlap. Nothing is re-implemented here.

Chunks are embedded with Chroma's default embedding function
(all-MiniLM-L6-v2, run locally through ONNX) and persisted to ``week06/chroma``.
No API key is needed.

Every chunk is stored with its ``volume`` and ``chapter`` metadata -- both are
required, and ingestion fails rather than storing a chunk without them -- plus
the chunk's size and paragraph range. ``query.py`` filters on them.

Usage
-----
    python week06/ingest.py                 # all six volumes, recommended params
    python week06/ingest.py --volumes 1     # one volume (same chunk ids as the full run)
    python week06/ingest.py --append        # upsert into an existing collection
    python week06/ingest.py --stats         # print the stored collection summary

The target/overlap default to the winner recorded in
``chunking/out/stats.json``; if that file is missing the measured defaults
(1,500 / 100 characters) are used.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
CHUNKING_DIR = HERE / "chunking"
DEFAULT_DB = HERE / "chroma"
DEFAULT_COLLECTION = "gibbon"
FALLBACK_TARGET = 1500
FALLBACK_OVERLAP = 100
DEFAULT_BATCH_SIZE = 256

# `chunking/chunking.py` is a module, not an installed package. Putting its
# directory first on the path makes `import chunking` resolve to that file even
# when the script is launched from the repository root.
sys.path.insert(0, str(CHUNKING_DIR))

try:
    from chunking import flatten, load_volume, pack
except ImportError as err:  # pragma: no cover - only on a broken checkout
    raise SystemExit(f"cannot import week06/chunking/chunking.py: {err}") from err


def volume_number(path: Path) -> int:
    match = re.search(r"Volume (\d+)", path.name)
    if match is None:
        raise SystemExit(f"{path.name}: cannot read a volume number from the filename")
    return int(match.group(1))


def discover_volumes(data_dir: Path, selected: set[int] | None) -> list[tuple[int, Path]]:
    volumes = []
    for path in data_dir.glob("*.txt"):
        number = volume_number(path)
        if selected is None or number in selected:
            volumes.append((number, path))
    volumes.sort(key=lambda item: item[0])
    if not volumes:
        wanted = "any" if selected is None else ", ".join(map(str, sorted(selected)))
        raise SystemExit(f"no volumes found in {data_dir} (wanted: {wanted})")
    return volumes


def recommendation(stats_path: Path) -> tuple[int, int]:
    """The chunking study's winning target/overlap, when it has been generated."""
    try:
        best = json.loads(stats_path.read_text(encoding="utf-8"))["best"]
        return int(best["target_chars"]), int(best["overlap_chars"])
    except (OSError, KeyError, TypeError, ValueError):
        return FALLBACK_TARGET, FALLBACK_OVERLAP


def chunk_id(chunk, index: int) -> str:
    """Match the ids in chunking/out/chunks.jsonl.gz exactly."""
    return f"v{chunk.volume}-{index:05d}"


def verify_against_reference(chunks: list) -> int | None:
    """Refuse to ingest chunks that differ from the study's generated file.

    The report, the Node backend and ChromaDB should all see the same retrieval
    units. If `chunking.py` changed but `out/chunks.jsonl.gz` was not rebuilt,
    this catches the drift instead of quietly indexing a different corpus.
    """
    reference_path = CHUNKING_DIR / "out" / "chunks.jsonl.gz"
    if not reference_path.exists():
        return None

    try:
        with gzip.open(reference_path, "rt", encoding="utf-8") as handle:
            reference = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError) as err:
        raise SystemExit(f"cannot read {reference_path}: {err}") from err

    if len(reference) != len(chunks):
        raise SystemExit(
            f"{reference_path} has {len(reference)} chunks, but chunking.py produced "
            f"{len(chunks)}. Re-run `python chunking.py` before ingesting."
        )

    for index, (chunk, expected) in enumerate(zip(chunks, reference)):
        if (
            chunk_id(chunk, index) != expected["id"]
            or chunk.volume != expected["volume"]
            or chunk.text != expected["text"]
        ):
            raise SystemExit(
                f"{reference_path} disagrees at chunk {index} "
                f"({expected['id']}). Re-run `python chunking.py` before ingesting."
            )
    return len(reference)


def extract_metadata(chunk, cid: str) -> dict:
    """The metadata stored for every chunk.

    ``volume`` and ``chapter`` are the two required fields: they are what the
    store is filtered by, so a chunk without them is a segmentation bug, not a
    chunk to embed. The rest record how the chunk was cut and are diagnostic.

    Chroma metadata may contain strings, ints, floats and bools only.
    """
    if not isinstance(chunk.volume, int) or chunk.volume < 1:
        raise SystemExit(f"chunk {cid} has no valid volume metadata: {chunk.volume!r}")
    if not isinstance(chunk.chapter, str) or chunk.chapter.strip() == "":
        raise SystemExit(f"chunk {cid} has no chapter metadata")

    return {
        "volume": chunk.volume,
        "chapter": chunk.chapter.strip(),
        "chars": chunk.chars,
        "words": chunk.words,
        "tokens": chunk.tokens,
        "paragraph_from": chunk.paragraph_from,
        "paragraph_to": chunk.paragraph_to,
        "overlap_chars": chunk.overlap_chars,
        "split": bool(chunk.split),
    }


def open_client(db_dir: Path):
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as err:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "chromadb is not installed. Install it with:\n"
            "  python -m pip install -r week06/requirements.txt"
        ) from err

    db_dir.mkdir(parents=True, exist_ok=True)
    # Telemetry is disabled: this is a coursework corpus and should not phone home.
    return chromadb.PersistentClient(
        path=str(db_dir),
        settings=Settings(anonymized_telemetry=False),
    )


def get_embedding_function():
    from chromadb.utils import embedding_functions

    # all-MiniLM-L6-v2 through ONNXMiniLM_L6_V2: local, deterministic, no key.
    return embedding_functions.DefaultEmbeddingFunction()


def open_collection(client, name: str, *, recreate: bool):
    """Return the collection, replacing it first unless the caller asked to append."""
    if recreate:
        try:
            client.delete_collection(name)
            print(f"[ingest] removed existing collection {name!r}")
        except Exception:
            # Chroma raises when the collection does not exist; that is not an error.
            pass

    ef = get_embedding_function()
    embedding_name = "chromadb-default"
    if hasattr(ef, "name"):
        try:
            embedding_name = str(ef.name())
        except Exception:
            pass

    return client.get_or_create_collection(
        name=name,
        embedding_function=ef,
        # Cosine distance makes the reported score intuitive: 1 - distance.
        metadata={"hnsw:space": "cosine", "embedding": embedding_name},
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=DATA_DIR, help="folder with the six .txt volumes")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="ChromaDB persistence directory")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Chroma collection name")
    parser.add_argument(
        "--volumes",
        default=None,
        help="comma-separated volume numbers to ingest (default: all found)",
    )
    parser.add_argument("--target", type=int, default=None, help="chunk target in characters")
    parser.add_argument("--overlap", type=int, default=None, help="overlap in characters")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="embedding batch size")
    parser.add_argument("--append", action="store_true", help="keep the existing collection and upsert")
    parser.add_argument("--stats", action="store_true", help="print the stored collection summary and exit")
    args = parser.parse_args()

    selected = None
    if args.volumes:
        try:
            selected = {int(part) for part in args.volumes.split(",") if part.strip()}
        except ValueError as err:
            raise SystemExit(f"--volumes must be comma-separated integers: {err}") from err

    client = open_client(args.db)

    if args.stats:
        try:
            collection = client.get_collection(
                name=args.collection, embedding_function=get_embedding_function()
            )
        except Exception:
            raise SystemExit(f"collection {args.collection!r} does not exist in {args.db}")
        stored = collection.get(include=["metadatas"])
        per_volume: dict[str, int] = {}
        chapters: set[tuple[int, str]] = set()
        for meta in stored["metadatas"]:
            volume = meta.get("volume")
            per_volume[str(volume)] = per_volume.get(str(volume), 0) + 1
            chapters.add((volume, meta.get("chapter", "")))

        print(
            json.dumps(
                {
                    "db": str(args.db),
                    "collection": collection.name,
                    "chunks": collection.count(),
                    "volumes": dict(sorted(per_volume.items(), key=lambda item: int(item[0]))),
                    "chapters": len(chapters),
                    "metadata": collection.metadata,
                },
                indent=2,
            )
        )
        return 0

    # Always segment the full corpus so a --volumes subset keeps the same ids
    # as chunks.jsonl.gz; only the embedding batches are filtered.
    all_volumes = discover_volumes(args.data, None)
    stats_target, stats_overlap = recommendation(CHUNKING_DIR / "out" / "stats.json")
    target = args.target if args.target is not None else stats_target
    overlap = args.overlap if args.overlap is not None else stats_overlap

    if target <= 0:
        raise SystemExit("--target must be positive")
    if overlap < 0 or overlap >= target:
        raise SystemExit("--overlap must be between 0 and the target")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    source = "CLI" if args.target is not None or args.overlap is not None else "chunking/out/stats.json"

    print(
        f"[ingest] chunking {len(all_volumes)} volumes with target={target} chars, "
        f"overlap={overlap} chars (from {source})"
    )

    load_started = time.perf_counter()
    paragraphs = []
    for number, path in all_volumes:
        volume_paragraphs, _headings = load_volume(path, number)
        paragraphs.extend(volume_paragraphs)
        print(f"[ingest]   volume {number}: {len(volume_paragraphs)} paragraphs from {path.name}")
    stream = flatten(paragraphs)
    all_chunks = pack(stream, target, overlap)
    print(
        f"[ingest] packed {len(all_chunks)} chunks from {len(stream)} sentences "
        f"in {time.perf_counter() - load_started:.1f}s"
    )

    verified = verify_against_reference(all_chunks)
    if verified is None:
        print("[ingest] note: out/chunks.jsonl.gz is absent; skipping the reference check")
    else:
        print(f"[ingest] verified against out/chunks.jsonl.gz ({verified} chunks, ids and text match)")

    chunks = [
        (chunk_id(chunk, index), chunk)
        for index, chunk in enumerate(all_chunks)
        if selected is None or chunk.volume in selected
    ]
    if not chunks:
        raise SystemExit(f"no chunks were produced for volumes {sorted(selected or [])}")

    if len(chunks) != len(all_chunks):
        print(f"[ingest] limiting ingestion to {len(chunks)} of {len(all_chunks)} chunks")
    for _, chunk in chunks:
        if not chunk.text.strip():
            raise SystemExit(f"refusing to ingest an empty chunk ({chunk.volume})")

    collection = open_collection(client, args.collection, recreate=not args.append)
    print(
        f"[ingest] collection {args.collection!r} in {args.db} "
        f"({collection.count()} existing chunks)"
    )

    started = time.perf_counter()
    written = 0
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        collection.upsert(
            ids=[item[0] for item in batch],
            documents=[item[1].text for item in batch],
            metadatas=[extract_metadata(chunk, cid) for cid, chunk in batch],
        )
        written += len(batch)
        elapsed = time.perf_counter() - started
        rate = written / elapsed if elapsed else 0.0
        remaining = (len(chunks) - written) / rate if rate else 0.0
        print(
            f"[ingest]   {written}/{len(chunks)} chunks "
            f"({rate:.1f}/s, ~{remaining:.0f}s left, chunk ids {batch[0][0]}..{batch[-1][0]})"
        )

    total = collection.count()
    print(
        f"[ingest] done: {written} chunks upserted, {total} in collection "
        f"({time.perf_counter() - started:.1f}s)"
    )
    print(f"[ingest] query it with: python week06/query.py --db {args.db} --collection {args.collection} \"your question\"")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[ingest] interrupted; the collection is partial. Re-run to replace it.", file=sys.stderr)
        raise SystemExit(130)
