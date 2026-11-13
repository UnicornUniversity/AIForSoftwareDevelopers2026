"""Tokenization and word-level alignment for WER.

Two tokenizers exist and they must be applied **symmetrically** to both sides:

``verbatim``
    Lowercase, strip punctuation, keep every word, filler, and repetition.
    This is the primary basis for the reported WER. "Verbatim" refers to what
    the ASR produced: nothing is deleted from either transcript before scoring.

``filler_removed``
    The same, minus a fixed list of hesitation tokens (``um``, ``uh``, …). It is
    a clearly labelled **supplementary** score, because systems differ in whether
    they emit fillers and that difference is not a transcription error.

Alignment is a standard Levenshtein dynamic program with a deterministic
backtrace, so the exact substitution/deletion/insertion counts are reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

#: Surface forms are matched greedily, including internal apostrophes, hyphens,
#: and dots ("don't", "release-notes", "2.4", "U.S"). Anything else (commas,
#: quotes, em dashes, trailing periods) is a separator and is dropped
#: identically from both sides.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’.\-][A-Za-z0-9]+)*")

#: Hesitations removed only in the supplementary ``filler_removed`` mode. The
#: list is deliberately small and fixed; it is never extended to drop words that
#: carry meaning.
FILLERS: frozenset[str] = frozenset(
    {"um", "umm", "uh", "uhh", "erm", "er", "ah", "eh", "hmm", "mm", "mhm"}
)

TOKEN_MODES = ("verbatim", "filler_removed")


class AlignmentError(ValueError):
    """Raised when an alignment mode or token sequence is invalid."""


@dataclass(frozen=True)
class Token:
    """One scorable word with its original surface form and normalized key."""

    text: str
    key: str
    index: int


@dataclass(frozen=True)
class TokenizedText:
    tokens: tuple[Token, ...]
    #: Half-open token ranges, one per input segment/turn, in input order.
    spans: tuple[tuple[int, int], ...]

    def span_text(self, position: int) -> str:
        start, end = self.spans[position]
        return " ".join(token.text for token in self.tokens[start:end])

    def span_of(self, token_index: int) -> int | None:
        for position, (start, end) in enumerate(self.spans):
            if start <= token_index < end:
                return position
        return None


def normalize_key(surface: str) -> str:
    return surface.lower().replace("’", "'")


def tokenize(text: str, *, mode: str = "verbatim") -> list[Token]:
    """Split ``text`` into scorable tokens under the requested mode."""

    if mode not in TOKEN_MODES:
        raise AlignmentError(f"unknown token mode {mode!r}; use one of {TOKEN_MODES}")
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(text or ""):
        surface = match.group(0)
        key = normalize_key(surface)
        if mode == "filler_removed" and key in FILLERS:
            continue
        tokens.append(Token(text=surface, key=key, index=len(tokens)))
    return tokens


def tokenize_texts(texts: Sequence[str], *, mode: str = "verbatim") -> TokenizedText:
    """Tokenize several texts and remember which tokens came from which one."""

    tokens: list[Token] = []
    spans: list[tuple[int, int]] = []
    for text in texts:
        start = len(tokens)
        for token in tokenize(text, mode=mode):
            tokens.append(Token(text=token.text, key=token.key, index=len(tokens)))
        spans.append((start, len(tokens)))
    return TokenizedText(tokens=tuple(tokens), spans=tuple(spans))


@dataclass(frozen=True)
class Op:
    """One aligned position. ``None`` means a gap on that side."""

    kind: str  # "equal" | "sub" | "del" | "ins"
    reference: str | None
    hypothesis: str | None
    reference_index: int | None
    hypothesis_index: int | None


@dataclass(frozen=True)
class Alignment:
    substitutions: int
    deletions: int
    insertions: int
    correct: int
    reference_length: int
    hypothesis_length: int
    ops: tuple[Op, ...]

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def wer(self) -> float:
        """Errors per reference word.

        When the reference is empty, WER is 0.0 for an empty hypothesis and 1.0
        otherwise; the base rate is undefined and the report says so.
        """

        if self.reference_length:
            return self.errors / self.reference_length
        return 0.0 if self.errors == 0 else 1.0

    @property
    def defined(self) -> bool:
        return self.reference_length > 0


def align(
    reference: Sequence[Token], hypothesis: Sequence[Token]
) -> Alignment:
    """Align token sequences and count substitutions, deletions, insertions."""

    n = len(reference)
    m = len(hypothesis)
    ref_keys = [token.key for token in reference]
    hyp_keys = [token.key for token in hypothesis]

    # dp[i][j] = edit distance between reference[:i] and hypothesis[:j].
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ref_key = ref_keys[i - 1]
        row = dp[i]
        previous = dp[i - 1]
        for j in range(1, m + 1):
            if ref_key == hyp_keys[j - 1]:
                row[j] = previous[j - 1]
            else:
                row[j] = 1 + min(previous[j - 1], previous[j], row[j - 1])

    ops: list[Op] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_keys[i - 1] == hyp_keys[j - 1]:
            ops.append(
                Op(
                    "equal",
                    reference[i - 1].text,
                    hypothesis[j - 1].text,
                    reference[i - 1].index,
                    hypothesis[j - 1].index,
                )
            )
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops.append(
                Op(
                    "sub",
                    reference[i - 1].text,
                    hypothesis[j - 1].text,
                    reference[i - 1].index,
                    hypothesis[j - 1].index,
                )
            )
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(
                Op(
                    "del",
                    reference[i - 1].text,
                    None,
                    reference[i - 1].index,
                    None,
                )
            )
            i -= 1
        elif j > 0:
            ops.append(
                Op(
                    "ins",
                    None,
                    hypothesis[j - 1].text,
                    None,
                    hypothesis[j - 1].index,
                )
            )
            j -= 1
        else:  # pragma: no cover - the branches above cover every state
            raise AlignmentError("alignment backtrace reached an impossible state")
    ops.reverse()

    substitutions = sum(1 for op in ops if op.kind == "sub")
    deletions = sum(1 for op in ops if op.kind == "del")
    insertions = sum(1 for op in ops if op.kind == "ins")
    correct = sum(1 for op in ops if op.kind == "equal")
    return Alignment(
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        correct=correct,
        reference_length=n,
        hypothesis_length=m,
        ops=tuple(ops),
    )


def align_texts(
    reference: str, hypothesis: str, *, mode: str = "verbatim"
) -> Alignment:
    """Convenience wrapper: tokenize two strings and align them."""

    return align(
        tokenize(reference, mode=mode), tokenize(hypothesis, mode=mode)
    )
