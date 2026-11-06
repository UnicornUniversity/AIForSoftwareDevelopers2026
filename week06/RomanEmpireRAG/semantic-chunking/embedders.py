"""Sentence embedding backends.

The segmentation algorithm in ``segmenter.py`` is backend-agnostic: it only
needs one vector per sentence and a cosine function. This module supplies three:

``tfidf``
    Standard library only. A sparse sublinear TF-IDF vector over unigrams and
    adjacent bigrams. It is a *lexical* proxy for semantics, not a semantic
    model; it is the fallback that keeps the pipeline runnable with no installs.

``spacy``
    Local 300-d static word vectors (``en_core_web_lg``), averaged per sentence
    with smooth-inverse-frequency weights and the first principal component
    removed (Arora et al., 2017). No API key, no network after the model is
    installed. This is the default when available.

``st``
    ``sentence-transformers`` (contextual transformer embeddings). Optional; the
    model is downloaded on first use. No API key.

DeepSeek is deliberately *not* an embedder: its public API exposes chat
completions, not an embeddings endpoint. See ``deepseek.py`` for the roles where
an LLM is actually the right tool.
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from pathlib import Path

STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because been
    before being below between both but by can't cannot could couldn't did didn't do does
    doesn't doing don't down during each few for from further had hadn't has hasn't have
    haven't having he he'd he'll he's her here here's hers herself him himself his how how's
    i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my
    myself no nor not of off on once only or other ought our ours ourselves out over own same
    shan't she she'd she'll she's should shouldn't so some such than that that's the their
    theirs them themselves then there there's these they they'd they'll they're they've this
    those through to too under until up very was wasn't we we'd we'll we're we've were weren't
    what what's when when's where where's which while who who's whom why why's with won't would
    wouldn't you you'd you'll you're you've your yours yourself yourselves
    """.split()
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
SIF_A = 1e-3


# ---------------------------------------------------------------------------
# Vector helpers (dense numpy arrays and sparse dicts)
# ---------------------------------------------------------------------------


def is_sparse(vector) -> bool:
    return isinstance(vector, dict)


def vec_add(a, b):
    if isinstance(a, dict):
        out = dict(a)
        for key, value in b.items():
            out[key] = out.get(key, 0.0) + value
        return out
    return a + b


def vec_mean(vectors: list):
    if not vectors:
        return {}
    if isinstance(vectors[0], dict):
        total: dict[str, float] = {}
        for vector in vectors:
            for key, value in vector.items():
                total[key] = total.get(key, 0.0) + value
        n = len(vectors)
        return {key: value / n for key, value in total.items()}
    import numpy as np

    return np.mean(np.asarray(vectors), axis=0)


def vec_l2(vector) -> float:
    if isinstance(vector, dict):
        return math.sqrt(sum(value * value for value in vector.values()))
    import numpy as np

    return float(np.linalg.norm(vector))


def normalize(vector):
    if isinstance(vector, dict):
        norm = vec_l2(vector)
        if norm == 0:
            return {}
        return {key: value / norm for key, value in vector.items()}
    import numpy as np

    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector
    return vector / norm


def cosine(a, b) -> float:
    if isinstance(a, dict) and isinstance(b, dict):
        if len(a) > len(b):
            a, b = b, a
        dot = 0.0
        for key, value in a.items():
            other = b.get(key)
            if other:
                dot += value * other
        norm = vec_l2(a) * vec_l2(b)
        return dot / norm if norm else 0.0
    import numpy as np

    a = np.asarray(a, dtype="float32")
    b = np.asarray(b, dtype="float32")
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b)) / norm if norm else 0.0


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in TOKEN_RE.finditer(text))
        if len(token) > 1 and token not in STOPWORDS
    ]


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class Embedder:
    name = "base"
    is_dense = False

    def embed(self, texts: list[str]) -> list:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"backend": self.name, "dense": self.is_dense}

    def cache_key(self) -> str:
        return self.name


class TfidfEmbedder(Embedder):
    """Lexical fallback: sparse sublinear TF-IDF over unigrams and bigrams."""

    name = "tfidf"
    is_dense = False

    def __init__(self, texts: list[str], min_df: int = 2, max_features: int = 120_000):
        self.min_df = min_df
        self.max_features = max_features
        self.idf: dict[str, float] = {}
        self._fit(texts)

    @staticmethod
    def _terms(text: str) -> list[str]:
        tokens = tokenize(text)
        terms = ["u:" + token for token in tokens]
        terms.extend("b:" + a + "_" + b for a, b in zip(tokens, tokens[1:]))
        return terms

    def _fit(self, texts: list[str]) -> None:
        document_frequency: dict[str, int] = {}
        for text in texts:
            for term in set(self._terms(text)):
                document_frequency[term] = document_frequency.get(term, 0) + 1
        # Keep terms that occur in at least min_df sentences, then cap the
        # vocabulary. The cap is only a memory guard for pathological corpora.
        kept = [(term, df) for term, df in document_frequency.items() if df >= self.min_df]
        kept.sort(key=lambda item: (-item[1], item[0]))
        kept = kept[: self.max_features]
        n = max(1, len(texts))
        self.idf = {
            term: math.log((1.0 + n) / (1.0 + df)) + 1.0
            for term, df in kept
        }

    def embed(self, texts: list[str]) -> list[dict[str, float]]:
        vectors: list[dict[str, float]] = []
        for text in texts:
            counts: dict[str, int] = {}
            for term in self._terms(text):
                if term in self.idf:
                    counts[term] = counts.get(term, 0) + 1
            vector = {
                term: (1.0 + math.log(count))
                for term, count in counts.items()
            }
            for term in vector:
                vector[term] *= self.idf[term]
            vectors.append(normalize(vector))
        return vectors

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "dense": False,
            "vocabulary": len(self.idf),
            "weighting": "sublinear tf-idf; unigrams + adjacent bigrams; L2-normalised",
            "note": "lexical proxy for semantics, not a neural embedding",
        }

    def cache_key(self) -> str:
        return f"tfidf-{self.min_df}-{self.max_features}-{len(self.idf)}"


class SpacyEmbedder(Embedder):
    """Static 300-d word vectors, SIF-weighted and common-component removed."""

    name = "spacy"
    is_dense = True

    def __init__(self, texts: list[str], model: str = "en_core_web_lg", remove_pc: bool = True):
        try:
            import numpy  # noqa: F401
            import spacy
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise SystemExit(
                "The spaCy backend needs spaCy and numpy.\n"
                "  pip install -r requirements-optional.txt\n"
                "  python -m spacy download en_core_web_lg"
            ) from exc
        try:
            self.nlp = spacy.load(
                model,
                exclude=["parser", "ner", "tagger", "lemmatizer", "attribute_ruler", "tok2vec"],
            )
        except OSError as exc:
            raise SystemExit(
                f"spaCy model '{model}' is not installed.\n"
                f"  python -m spacy download {model}"
            ) from exc
        self.model = model
        self.remove_pc = remove_pc
        self.dim = int(self.nlp.vocab.vectors.shape[1])
        # SIF weights come from a corpus-frequency estimate. A regex pass is
        # enough and avoids a second spaCy pass over 1.4M words.
        document_frequency: dict[str, int] = {}
        for text in texts:
            for token in set(tokenize(text)):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        self.n = max(1, len(texts))
        self.document_frequency = document_frequency

    def _word_weight(self, token: str) -> float:
        probability = self.document_frequency.get(token, 0) / self.n
        return SIF_A / (SIF_A + probability)

    def embed(self, texts: list[str]) -> "object":
        import numpy as np

        vectors = np.zeros((len(texts), self.dim), dtype="float32")
        docs = self.nlp.pipe(texts, batch_size=128)
        for row, doc in enumerate(docs):
            accumulator = np.zeros(self.dim, dtype="float32")
            total_weight = 0.0
            for token in doc:
                if not token.has_vector:
                    continue
                weight = self._word_weight(token.lower_)
                accumulator += weight * token.vector
                total_weight += weight
            if total_weight:
                vectors[row] = accumulator / total_weight

        # SIF's common-component removal works on the centred matrix. Centring
        # also keeps cosine similarity interpretable: uncentred static vectors
        # sit in a narrow cone (all sentences look ~0.93 similar), which makes
        # distances and cohesion metrics artificially flat.
        vectors -= vectors.mean(axis=0, keepdims=True)
        if self.remove_pc:
            self._remove_first_component(vectors)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    @staticmethod
    def _remove_first_component(vectors) -> None:
        import numpy as np

        nonzero = np.linalg.norm(vectors, axis=1) > 0
        sample = vectors[nonzero]
        if len(sample) < 10:
            return
        if len(sample) > 5_000:
            sample = sample[:: max(1, len(sample) // 5_000)][:5_000]
        centered = sample - sample.mean(axis=0, keepdims=True)
        # Right singular vector of the centred sample is the first principal
        # component; projecting it out is the standard SIF post-processing.
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        component = vt[0]
        vectors -= np.outer(vectors @ component, component)

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "dense": True,
            "model": self.model,
            "dimensions": self.dim,
            "weighting": "SIF (a=1e-3) over static word vectors; first principal component removed; L2-normalised",
            "note": "static vectors: semantic but not contextual",
        }

    def cache_key(self) -> str:
        # `-c1` marks the centred-vector variant; bump it when the embedding
        # arithmetic changes so an old cache cannot be reused silently.
        return f"spacy-{self.model}-{int(self.remove_pc)}-c1"


class SentenceTransformerEmbedder(Embedder):
    name = "st"
    is_dense = True

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "The sentence-transformers backend is not installed.\n"
                "  pip install -r requirements-optional.txt"
            ) from exc
        self.model_name = model
        self.model = SentenceTransformer(model)
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]):
        import numpy as np

        vectors = self.model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype="float32")

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "dense": True,
            "model": self.model_name,
            "dimensions": self.dim,
            "weighting": "model output, L2-normalised by the model",
            "note": "contextual transformer embeddings",
        }

    def cache_key(self) -> str:
        return f"st-{self.model_name}"


# ---------------------------------------------------------------------------
# Factory and cache
# ---------------------------------------------------------------------------


def make_embedder(backend: str, texts: list[str], env: dict | None = None) -> Embedder:
    env = env or {}
    backend = (backend or "auto").lower()
    if backend == "auto":
        try:
            return SpacyEmbedder(texts, env.get("SPACY_MODEL", "en_core_web_lg"))
        except SystemExit as exc:
            print(f"[backend] spaCy unavailable, falling back to tfidf: {exc}", file=sys.stderr)
            return TfidfEmbedder(texts)
    if backend in {"spacy", "spacy_lg"}:
        return SpacyEmbedder(texts, env.get("SPACY_MODEL", "en_core_web_lg"))
    if backend == "tfidf":
        return TfidfEmbedder(texts)
    if backend in {"st", "sentence-transformers", "sentence_transformers"}:
        return SentenceTransformerEmbedder(env.get("ST_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
    raise SystemExit(f"unknown backend '{backend}' (choose auto, spacy, tfidf or st)")


def corpus_hash(texts: list[str]) -> str:
    digest = hashlib.sha1()
    for text in texts:
        digest.update(text.encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def embed_with_cache(
    embedder: Embedder,
    texts: list[str],
    cache_dir: Path,
    refresh: bool = False,
):
    """Return sentence vectors, reusing a dense cache when the corpus matches."""
    if not embedder.is_dense:
        print(f"[embed] {embedder.name}: embedding {len(texts)} sentences (no cache for sparse vectors)")
        return embedder.embed(texts)

    import numpy as np

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(
        f"{embedder.cache_key()}:{corpus_hash(texts)}".encode("utf-8")
    ).hexdigest()[:20]
    path = cache_dir / f"{embedder.name}-{key}.npy"
    if path.exists() and not refresh:
        vectors = np.load(path)
        if len(vectors) == len(texts):
            print(f"[embed] cache hit: {path.name} ({vectors.shape[0]} x {vectors.shape[1]})")
            return vectors
        print(f"[embed] cache shape mismatch, recomputing: {path.name}", file=sys.stderr)

    print(f"[embed] {embedder.name}: embedding {len(texts)} sentences...", file=sys.stderr)
    vectors = embedder.embed(texts)
    np.save(path, vectors)
    meta = cache_dir / f"{embedder.name}-{key}.json"
    meta.write_text(
        __import__("json").dumps(embedder.describe(), indent=2), encoding="utf-8"
    )
    print(f"[embed] wrote {path.name} ({vectors.shape[0]} x {vectors.shape[1]})")
    return vectors
