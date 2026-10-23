"""Corpus manifest: loading, title repair and id lookup."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .errors import CorpusError


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that was decoded as cp1252.

    Two manifest titles arrive as ``â€”`` / ``â€“``.  Re-encoding to cp1252 and
    decoding as UTF-8 recovers the em/en dash.  Any string that does not
    round-trip cleanly is returned unchanged, so legitimate Unicode (including
    a real em dash) stays intact.
    """

    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if "�" in fixed:
        return text
    return fixed


def match_key(text: str) -> str:
    """A comparison key tolerant of mojibake, punctuation and case.

    Only ASCII letters and digits survive, so ``(1998â€“2024)`` and
    ``(1998–2024)`` produce the same key.
    """

    decomposed = unicodedata.normalize("NFKD", repair_mojibake(text))
    kept = [ch for ch in decomposed if ch.isascii() and ch.isalnum()]
    return "".join(kept).casefold()


@dataclass(frozen=True)
class DocumentEntry:
    id: str
    filename: str
    format: str
    sub_topic: str
    title: str
    word_count: int
    target_words: int
    has_contradiction: bool
    raw_title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str = ""
    document_type: str = ""
    body_word_count: int | None = None
    has_figure: bool = False

    def path(self, corpus_dir: Path) -> Path:
        return corpus_dir / self.filename

    @property
    def format_label(self) -> str:
        return self.format.upper()

    @property
    def author_label(self) -> str:
        """A short author label for citations, e.g. ``Voss et al.``."""

        if not self.authors:
            return self.id
        first = self.authors[0]
        surname = first.split()[-1] if first.split() else first
        if len(self.authors) == 1:
            return surname
        if len(self.authors) == 2:
            second = self.authors[1].split()[-1]
            return f"{surname} and {second}"
        return f"{surname} et al."

    @property
    def citation(self) -> str:
        """The in-text citation, e.g. ``(Marchetti et al., 2023)``."""

        if self.year is None:
            return f"({self.author_label}, n.d.)"
        return f"({self.author_label}, {self.year})"


class Manifest:
    def __init__(self, documents: list[DocumentEntry], source: Path, raw: dict) -> None:
        self.documents = documents
        self.source = source
        self.raw = raw
        self.by_id = {entry.id: entry for entry in documents}

    def lookup(self, doc_id: str) -> DocumentEntry:
        try:
            return self.by_id[doc_id]
        except KeyError:
            raise CorpusError(
                f"unknown source id {doc_id!r}", file=self.source
            ) from None

    def by_sub_topic(self) -> dict[str, list[DocumentEntry]]:
        groups: dict[str, list[DocumentEntry]] = {}
        for entry in self.documents:
            groups.setdefault(entry.sub_topic, []).append(entry)
        return groups


_REQUIRED = (
    "id",
    "filename",
    "format",
    "sub_topic",
    "title",
    "word_count",
    "target_words",
    "has_contradiction",
)


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CorpusError("manifest not found", file=path) from None
    except OSError as exc:
        raise CorpusError(f"cannot read manifest: {exc}", file=path) from None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorpusError(exc.msg, file=path, line=exc.lineno) from None

    if not isinstance(raw, dict) or not isinstance(raw.get("documents"), list):
        raise CorpusError("manifest must contain a 'documents' list", file=path)
    count = raw.get("count")
    if not isinstance(count, int) or count != len(raw["documents"]):
        raise CorpusError(
            "'count' must be an integer equal to the number of documents",
            file=path,
            key="count",
        )

    documents: list[DocumentEntry] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for index, item in enumerate(raw["documents"]):
        key = f"documents[{index}]"
        if not isinstance(item, dict):
            raise CorpusError("must be an object", file=path, key=key)
        missing = [name for name in _REQUIRED if name not in item]
        if missing:
            raise CorpusError(
                f"missing key(s): {', '.join(missing)}", file=path, key=key
            )
        for name in _REQUIRED:
            expected = int if name in {"word_count", "target_words"} else (
                bool if name == "has_contradiction" else str
            )
            value = item[name]
            if expected is bool:
                if not isinstance(value, bool):
                    raise CorpusError("must be true or false", file=path, key=f"{key}.{name}")
            elif expected is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise CorpusError("must be an integer", file=path, key=f"{key}.{name}")
            elif not isinstance(value, str) or not value.strip():
                raise CorpusError("must be a non-empty string", file=path, key=f"{key}.{name}")
        if item["format"] not in {"docx", "pdf"}:
            raise CorpusError("must be 'docx' or 'pdf'", file=path, key=f"{key}.format")
        if item["id"] in seen_ids:
            raise CorpusError(f"duplicate id {item['id']!r}", file=path, key=f"{key}.id")
        if item["filename"] in seen_files:
            raise CorpusError(
                f"duplicate filename {item['filename']!r}", file=path, key=f"{key}.filename"
            )
        if not item["filename"].startswith(item["id"]):
            raise CorpusError(
                "filename must start with the document id", file=path, key=f"{key}.filename"
            )
        seen_ids.add(item["id"])
        seen_files.add(item["filename"])
        documents.append(
            DocumentEntry(
                id=item["id"],
                filename=item["filename"],
                format=item["format"],
                sub_topic=item["sub_topic"],
                title=repair_mojibake(item["title"]),
                word_count=item["word_count"],
                target_words=item["target_words"],
                has_contradiction=item["has_contradiction"],
                raw_title=item["title"],
                authors=_optional_authors(item, key, path),
                year=_optional_int(item, "year", key, path),
                venue=_optional_text(item, "venue", key, path),
                document_type=_optional_text(item, "document_type", key, path),
                body_word_count=_optional_int(item, "body_word_count", key, path),
                has_figure=_optional_bool(item, "has_figure", key, path),
            )
        )

    return Manifest(documents=documents, source=path, raw=raw)


def _optional_text(item: dict, name: str, key: str, path: Path) -> str:
    if name not in item:
        return ""
    value = item[name]
    if not isinstance(value, str):
        raise CorpusError("must be a string", file=path, key=f"{key}.{name}")
    return repair_mojibake(value)


def _optional_int(item: dict, name: str, key: str, path: Path) -> int | None:
    if name not in item:
        return None
    value = item[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorpusError("must be an integer", file=path, key=f"{key}.{name}")
    return value


def _optional_bool(item: dict, name: str, key: str, path: Path) -> bool:
    if name not in item:
        return False
    value = item[name]
    if not isinstance(value, bool):
        raise CorpusError("must be true or false", file=path, key=f"{key}.{name}")
    return value


def _optional_authors(item: dict, key: str, path: Path) -> tuple[str, ...]:
    if "authors" not in item:
        return ()
    value = item["authors"]
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name.strip() for name in value
    ):
        raise CorpusError(
            "must be a list of non-empty names", file=path, key=f"{key}.authors"
        )
    return tuple(repair_mojibake(name) for name in value)


def resolve_manifest_path(
    settings,
    *,
    corpus_override: str | Path | None = None,
    manifest_override: str | Path | None = None,
) -> tuple[Path, Path]:
    """Return ``(corpus_dir, manifest_path)``, discovering both when needed."""

    corpus = Path(corpus_override).resolve() if corpus_override else settings.corpus_dir
    if manifest_override:
        manifest = Path(manifest_override).resolve()
        if not manifest.is_file():
            raise CorpusError("manifest not found", file=manifest)
        return corpus, manifest

    candidates = [
        settings.manifest_path,
        corpus / "manifest.json",
        corpus.parent / "manifest.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return corpus, candidate
    listed = "\n  ".join(str(c) for c in candidates)
    raise CorpusError(f"manifest not found; looked in:\n  {listed}", file=settings.path)
