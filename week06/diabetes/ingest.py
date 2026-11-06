#!/usr/bin/env python3
"""Split the diabetes knowledge base into sections and store them in ChromaDB.

The corpus in ``data/`` is twelve short, evenly structured Markdown documents
(source, topic and review date in a header; then ``## Overview``,
``## Key information``, ``## Important distinctions / exceptions`` and
``## Examples``). A fixed character window -- the unit chosen for Gibbon's six
volumes in ``week06/RomanEmpireRAG`` -- would cut through those sections and
blend unrelated topics, so the retrieval unit here is the section itself.

Every chunk carries the document id, title, topic, section heading, source and
review date. ``doc_id``, ``title`` and ``section`` are required: they are what
``query.py`` and the UI filter and label passages by, so a chunk without them is
a parsing bug, not something to embed. The ``## References`` section is skipped:
bibliographic entries add no answer context and would compete with real passages.

Chunks are embedded with Chroma's default embedding function (all-MiniLM-L6-v2,
run locally through ONNX) and persisted to ``week06/diabetes/chroma``. No API key
is needed.

Usage
-----
    python week06/diabetes/ingest.py             # all twelve documents
    python week06/diabetes/ingest.py --stats     # print the stored summary
    python week06/diabetes/ingest.py --append    # upsert into an existing collection
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DEFAULT_DB = HERE / "chroma"
DEFAULT_COLLECTION = "diabetes"
DEFAULT_BATCH_SIZE = 64

# `## References` is bibliography, not answer context. Compared after slugify.
SKIPPED_SECTIONS = {"references"}

TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
DOC_NUMBER_RE = re.compile(r"^(\d+)_")
HEADER_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?):\s*(.*)$")


@dataclass
class Chunk:
    """One retrievable section, with everything the UI needs to label it."""

    id: str
    doc_id: str
    doc_number: int
    title: str
    topic: str
    section: str
    section_index: int
    source: str
    reviewed: str
    text: str
    chars: int
    words: int
    tokens: int


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug == "":
        raise SystemExit(f"cannot build a slug from {value!r}")
    return slug


def strip_emphasis(text: str) -> str:
    """Remove Markdown emphasis so the passage reads as plain prose.

    The documents are Markdown; the app renders answers and passages as text
    nodes, never as HTML or Markdown. Leaving ``**`` and ``*`` in would show
    syntax to the reader and feed punctuation tokens to the embedding model.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


def plain_text(markdown: str) -> str:
    """Turn a section body into readable plain text.

    Blank lines separate blocks. Within a block, prose lines are joined into one
    sentence flow (the sources wrap at ~80 columns) while bullet items keep their
    own lines and get a visible ``•`` marker. This is a rendering normalisation,
    not a rewrite: the wording is unchanged.
    """
    blocks: list[str] = []

    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        rendered: list[str] = []
        prose: list[str] = []

        def flush() -> None:
            if prose:
                rendered.append(" ".join(prose))
                prose.clear()

        for line in lines:
            if line.startswith(("- ", "* ")):
                flush()
                rendered.append(f"• {line[2:].strip()}")
            else:
                prose.append(line)
        flush()

        blocks.append("\n".join(rendered))

    return strip_emphasis("\n\n".join(blocks)).strip()


def parse_document(path: Path) -> list[Chunk]:
    """Parse one Markdown file into section chunks.

    Fails loudly on anything the rest of the stack relies on: a missing title,
    no sections, an empty section, or a duplicate chunk id. The corpus is small
    and hand-written, so these are parse bugs, not data to work around.
    """
    raw = path.read_text(encoding="utf-8")
    number_match = DOC_NUMBER_RE.match(path.name)
    if number_match is None:
        raise SystemExit(f"{path.name}: filename must start with a document number, e.g. 01_topic.md")
    doc_number = int(number_match.group(1))
    doc_id = path.stem

    title_match = TITLE_RE.search(raw)
    if title_match is None:
        raise SystemExit(f"{path.name}: no '# Title' heading")
    title = title_match.group(1).strip()

    sections = list(SECTION_RE.finditer(raw))
    if not sections:
        raise SystemExit(f"{path.name}: no '## ' sections")

    header_block = raw[title_match.end() : sections[0].start()]
    header: dict[str, str] = {}
    for line in header_block.splitlines():
        match = HEADER_LINE_RE.match(line.strip())
        if match is not None:
            header[match.group(1).strip().lower()] = match.group(2).strip()

    topic = header.get("topic", "")
    source = header.get("source", "")
    reviewed = header.get("last reviewed", "")
    if topic == "":
        raise SystemExit(f"{path.name}: the header has no Topic line")
    if source == "":
        raise SystemExit(f"{path.name}: the header has no Source line")

    chunks: list[Chunk] = []
    for index, match in enumerate(sections):
        section = match.group(1).strip()
        if slugify(section) in SKIPPED_SECTIONS:
            continue

        end = sections[index + 1].start() if index + 1 < len(sections) else len(raw)
        text = plain_text(raw[match.end() : end])
        if text == "":
            raise SystemExit(f"{path.name}: section {section!r} is empty")

        chars = len(text)
        chunks.append(
            Chunk(
                id=f"d{doc_number:02d}-{slugify(section)}",
                doc_id=doc_id,
                doc_number=doc_number,
                title=title,
                topic=topic,
                section=section,
                # The source index keeps sections in their document order even
                # though References is skipped.
                section_index=index,
                source=source,
                reviewed=reviewed,
                text=text,
                chars=chars,
                words=len(text.split()),
                # An estimate, not a tokenizer: the corpus is small and no
                # tokenizer is vendored. Reported as approximate in the docs.
                tokens=max(1, round(chars / 4)),
            )
        )

    if not chunks:
        raise SystemExit(f"{path.name}: every section was skipped; nothing to ingest")
    return chunks


def discover_documents(data_dir: Path) -> list[Path]:
    paths = sorted(data_dir.glob("*.md"))
    if not paths:
        raise SystemExit(f"no Markdown documents found in {data_dir}")
    return paths


def build_chunks(paths: list[Path]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in paths:
        chunks.extend(parse_document(path))

    seen: set[str] = set()
    for chunk in chunks:
        if chunk.id in seen:
            raise SystemExit(f"duplicate chunk id {chunk.id!r}; section headings must be unique per document")
        seen.add(chunk.id)
    return chunks


def metadata(chunk: Chunk) -> dict:
    """The metadata stored for every chunk.

    Chroma metadata may contain strings, ints, floats and bools only.
    """
    if not chunk.doc_id or not chunk.title.strip() or not chunk.section.strip():
        raise SystemExit(f"chunk {chunk.id} is missing required metadata")
    return {
        "doc_id": chunk.doc_id,
        "doc_number": chunk.doc_number,
        "title": chunk.title,
        "topic": chunk.topic,
        "section": chunk.section,
        "section_index": chunk.section_index,
        "source": chunk.source,
        "reviewed": chunk.reviewed,
        "chars": chunk.chars,
        "words": chunk.words,
        "tokens": chunk.tokens,
    }


def open_client(db_dir: Path):
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as err:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "chromadb is not installed. Install it with:\n"
            "  python -m pip install -r week06/diabetes/requirements.txt"
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


def embedding_text(chunk: Chunk) -> str:
    """The text that is embedded, which is not the text that is stored.

    A section on its own ("Warning signs ... Immediate management ...") does not
    name its subject, so the mean-pooled MiniLM vector drifts toward whichever
    bullet dominates. Prefixing the document title, section and topic -- the same
    heading-context decision as the Roman corpus's chunk prefix -- anchors the
    vector without changing what the reader is shown. The stored document stays
    the section body, so the UI quotes the source verbatim.
    """
    return f"{chunk.title} — {chunk.section}\nTopic: {chunk.topic}\n\n{chunk.text}"


def open_collection(client, name: str, *, recreate: bool, ef=None):
    """Return the collection, replacing it first unless the caller asked to append."""
    if recreate:
        try:
            client.delete_collection(name)
            print(f"[ingest] removed existing collection {name!r}")
        except Exception:
            # Chroma raises when the collection does not exist; that is not an error.
            pass

    ef = ef or get_embedding_function()
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


def print_stats(collection) -> None:
    stored = collection.get(include=["metadatas"])
    metadatas = stored.get("metadatas") or []

    per_document: dict[str, int] = {}
    sections: set[tuple[str, str]] = set()
    for meta in metadatas:
        meta = meta or {}
        doc_id = meta.get("doc_id", "")
        per_document[doc_id] = per_document.get(doc_id, 0) + 1
        sections.add((doc_id, meta.get("section", "")))

    print(
        json.dumps(
            {
                "collection": collection.name,
                "chunks": collection.count(),
                "documents": len(per_document),
                "sections": len(sections),
                "chunks_per_document": dict(sorted(per_document.items())),
                "metadata": collection.metadata,
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=DATA_DIR, help="folder with the .md documents")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="ChromaDB persistence directory")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Chroma collection name")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="embedding batch size")
    parser.add_argument("--append", action="store_true", help="keep the existing collection and upsert")
    parser.add_argument("--stats", action="store_true", help="print the stored collection summary and exit")
    args = parser.parse_args()

    client = open_client(args.db)

    if args.stats:
        try:
            collection = client.get_collection(
                name=args.collection, embedding_function=get_embedding_function()
            )
        except Exception:
            raise SystemExit(f"collection {args.collection!r} does not exist in {args.db}")
        print_stats(collection)
        return 0

    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")

    started = time.perf_counter()
    paths = discover_documents(args.data)
    chunks = build_chunks(paths)
    per_document: dict[str, int] = {}
    for chunk in chunks:
        per_document[chunk.doc_id] = per_document.get(chunk.doc_id, 0) + 1

    print(
        f"[ingest] parsed {len(chunks)} sections from {len(paths)} documents "
        f"in {time.perf_counter() - started:.2f}s"
    )
    for doc_id, count in sorted(per_document.items()):
        print(f"[ingest]   {doc_id}: {count} sections")

    ef = get_embedding_function()
    collection = open_collection(
        client, args.collection, recreate=not args.append, ef=ef
    )
    print(
        f"[ingest] collection {args.collection!r} in {args.db} "
        f"({collection.count()} existing chunks)"
    )

    started = time.perf_counter()
    written = 0
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        # The embedding carries the title/section/topic prefix; the stored
        # document is the section body alone.
        embeddings = ef([embedding_text(chunk) for chunk in batch])
        collection.upsert(
            ids=[chunk.id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            # The ONNX function returns NumPy float32 values; Chroma stores
            # Python floats, so convert rather than passing the array through.
            embeddings=[[float(value) for value in vector] for vector in embeddings],
            metadatas=[metadata(chunk) for chunk in batch],
        )
        written += len(batch)
        print(f"[ingest]   {written}/{len(chunks)} chunks upserted")

    total = collection.count()
    print(
        f"[ingest] done: {written} chunks upserted, {total} in collection "
        f"({time.perf_counter() - started:.2f}s)"
    )
    print(
        "[ingest] query it with: "
        f'python week06/diabetes/query.py --db {args.db} --collection {args.collection} "your question"'
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[ingest] interrupted; the collection is partial. Re-run to replace it.", file=sys.stderr)
        raise SystemExit(130)
