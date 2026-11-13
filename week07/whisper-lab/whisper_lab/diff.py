"""Compare a finished transcript with the original text and render a report.

The comparison is word-aligned with a minimum edit distance, so the substitutions,
insertions, and deletions it counts are the same ones ``benchmark.py`` scores
(the WER for the same pair of texts therefore agrees). Inside a substituted pair
the letters are compared one at a time. The generated page colours exactly that:
green letters appear in both texts, red letters do not.

Pure text handling -- no model, no network -- so it can be tested on its own.
"""

from __future__ import annotations

import difflib
import html
import re
from array import array
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import config
from . import formats
from .engine import Transcription

# Words are runs of letters, digits, and apostrophes; everything else (spaces,
# punctuation, brackets) is a separator. This mirrors benchmark.py's
# normalization, which turns punctuation into spaces before scoring.
WORD_RE = re.compile(r"[\w']+")

# Above this many cells the exact alignment is skipped in favour of a faster
# approximate one: (n + 1) * (m + 1) integers, 4 bytes each. A four-million-cell
# table is 16 MB and covers roughly two hours of speech against a reference.
MAX_ALIGNMENT_CELLS = 4_000_000


@dataclass(slots=True)
class Stats:
    reference_words: int = 0
    matched: int = 0
    substitutions: int = 0
    insertions: int = 0
    deletions: int = 0

    @property
    def errors(self) -> int:
        return self.substitutions + self.insertions + self.deletions

    @property
    def wer(self) -> float | None:
        """Word error rate, or None when the reference has no words."""
        if not self.reference_words:
            return None
        return self.errors / self.reference_words


@dataclass(slots=True)
class Comparison:
    stats: Stats
    reference_html: str
    hypothesis_html: str


@dataclass(slots=True)
class _Pair:
    reference: int | None
    hypothesis: int | None
    tag: str  # equal | replace | delete | insert


# ------------------------------------------------------------- tokenizing ---


def split_words(text: str) -> list[tuple[str, str]]:
    """Split into (separator before the word, word) pairs, preserving spacing.

    Whatever follows the last word (trailing punctuation or whitespace) is kept
    as a final pair with an empty word, so the rendered text ends the way the
    input does.
    """
    parts: list[tuple[str, str]] = []
    previous = 0
    for match in WORD_RE.finditer(text):
        parts.append((text[previous : match.start()], match.group()))
        previous = match.end()
    if previous < len(text):
        parts.append((text[previous:], ""))
    return parts


# -------------------------------------------------------------- alignment ---


def align(reference: list[str], hypothesis: list[str]) -> list[_Pair]:
    """Word alignment that minimises substitutions + insertions + deletions."""
    ref_keys = [word.casefold() for word in reference]
    hyp_keys = [word.casefold() for word in hypothesis]
    if (len(ref_keys) + 1) * (len(hyp_keys) + 1) > MAX_ALIGNMENT_CELLS:
        return _align_approximate(ref_keys, hyp_keys)
    return _align_exact(ref_keys, hyp_keys)


def _align_exact(ref_keys: list[str], hyp_keys: list[str]) -> list[_Pair]:
    n, m = len(ref_keys), len(hyp_keys)
    width = m + 1
    table = array("i", [0]) * ((n + 1) * width)
    for i in range(1, n + 1):
        table[i * width] = i
    for j in range(1, m + 1):
        table[j] = j

    for i in range(1, n + 1):
        base = i * width
        previous = base - width
        ref_key = ref_keys[i - 1]
        for j in range(1, m + 1):
            if ref_key == hyp_keys[j - 1]:
                table[base + j] = table[previous + j - 1]
            else:
                best = table[previous + j - 1]
                if table[previous + j] < best:
                    best = table[previous + j]
                if table[base + j - 1] < best:
                    best = table[base + j - 1]
                table[base + j] = best + 1

    # Walk back from the bottom-right corner. Every move taken is optimal, so
    # the total error count is exact; where several moves tie, trimming a word
    # (delete/insert) is preferred to substituting it, which keeps the pairing
    # of the remaining words in reading order.
    pairs: list[_Pair] = []
    i, j = n, m
    while i or j:
        here = table[i * width + j]
        if i and j and ref_keys[i - 1] == hyp_keys[j - 1] and here == table[(i - 1) * width + j - 1]:
            pairs.append(_Pair(i - 1, j - 1, "equal"))
            i -= 1
            j -= 1
        elif i and here == table[(i - 1) * width + j] + 1:
            pairs.append(_Pair(i - 1, None, "delete"))
            i -= 1
        elif j and here == table[i * width + j - 1] + 1:
            pairs.append(_Pair(None, j - 1, "insert"))
            j -= 1
        else:  # i and j are both non-zero here: an optimal substitution
            pairs.append(_Pair(i - 1, j - 1, "replace"))
            i -= 1
            j -= 1
    pairs.reverse()
    return pairs


def _align_approximate(ref_keys: list[str], hyp_keys: list[str]) -> list[_Pair]:
    """Fallback for very long inputs: fast, but not a minimum edit script."""
    matcher = difflib.SequenceMatcher(None, ref_keys, hyp_keys, autojunk=False)
    pairs: list[_Pair] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend(_Pair(i1 + offset, j1 + offset, "equal") for offset in range(i2 - i1))
        elif tag == "replace":
            shared = min(i2 - i1, j2 - j1)
            pairs.extend(_Pair(i1 + offset, j1 + offset, "replace") for offset in range(shared))
            pairs.extend(_Pair(index, None, "delete") for index in range(i1 + shared, i2))
            pairs.extend(_Pair(None, index, "insert") for index in range(j1 + shared, j2))
        elif tag == "delete":
            pairs.extend(_Pair(index, None, "delete") for index in range(i1, i2))
        else:
            pairs.extend(_Pair(None, index, "insert") for index in range(j1, j2))
    return pairs


def _letter_flags(reference: str, hypothesis: str) -> tuple[list[bool], list[bool]]:
    """Which letters of each word correspond, compared case-insensitively."""
    # Compare character lists rather than casefolded strings: casefolding can
    # change the length (ß -> ss), which would break the index arithmetic.
    matcher = difflib.SequenceMatcher(
        None,
        [character.casefold() for character in reference],
        [character.casefold() for character in hypothesis],
        autojunk=False,
    )
    ref_flags = [False] * len(reference)
    hyp_flags = [False] * len(hypothesis)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                ref_flags[i1 + offset] = True
                hyp_flags[j1 + offset] = True
    return ref_flags, hyp_flags


# --------------------------------------------------------------- rendering ---


def _render_word(word: str, flags: list[bool] | None) -> str:
    if flags is None:
        flags = [False] * len(word)
    pieces: list[str] = []
    index = 0
    while index < len(word):
        same = flags[index]
        run_end = index + 1
        while run_end < len(word) and flags[run_end] == same:
            run_end += 1
        css = "same" if same else "diff"
        pieces.append(f'<span class="{css}">{html.escape(word[index:run_end], quote=False)}</span>')
        index = run_end
    return "".join(pieces)


def _render_words(parts: list[tuple[str, str]], flags: list[list[bool] | None]) -> str:
    out: list[str] = []
    word_index = 0
    for separator, word in parts:
        out.append(html.escape(separator, quote=False))
        if not word:  # the trailing punctuation pair
            continue
        out.append(_render_word(word, flags[word_index]))
        word_index += 1
    return "".join(out)


def compare(reference_text: str, hypothesis_text: str) -> Comparison:
    reference_parts = split_words(reference_text)
    hypothesis_parts = split_words(hypothesis_text)
    reference_words = [word for _, word in reference_parts if word]
    hypothesis_words = [word for _, word in hypothesis_parts if word]

    pairs = align(reference_words, hypothesis_words)
    reference_flags: list[list[bool] | None] = [None] * len(reference_words)
    hypothesis_flags: list[list[bool] | None] = [None] * len(hypothesis_words)

    stats = Stats(reference_words=len(reference_words))
    for pair in pairs:
        if pair.reference is not None and pair.hypothesis is not None:
            ref_flags, hyp_flags = _letter_flags(
                reference_words[pair.reference], hypothesis_words[pair.hypothesis]
            )
            reference_flags[pair.reference] = ref_flags
            hypothesis_flags[pair.hypothesis] = hyp_flags

        if pair.tag == "equal":
            stats.matched += 1
        elif pair.tag == "replace":
            stats.substitutions += 1
        elif pair.tag == "delete":
            stats.deletions += 1
        else:
            stats.insertions += 1

    return Comparison(
        stats=stats,
        reference_html=_render_words(reference_parts, reference_flags),
        hypothesis_html=_render_words(hypothesis_parts, hypothesis_flags),
    )


# ---------------------------------------------------------------- the page ---

PAGE_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f5f4f0;
  --panel: #ffffff;
  --ink: #1c1f24;
  --muted: #606772;
  --line: #e2e0da;
  --same: #157a43;
  --diff: #c02626;
  --diff-bg: rgba(192, 38, 38, 0.09);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171b;
    --panel: #1d2025;
    --ink: #e8eaee;
    --muted: #9aa1ac;
    --line: #2c3138;
    --same: #4ade80;
    --diff: #fca5a5;
    --diff-bg: rgba(248, 113, 113, 0.16);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 16px/1.6 ui-sans-serif, system-ui, "Segoe UI", sans-serif;
}
main { max-width: 62rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
.eyebrow {
  margin: 0 0 0.35rem;
  color: var(--muted);
  font-size: 0.78rem;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: clamp(1.5rem, 3vw, 2rem); line-height: 1.2; word-break: break-word; }
.meta { margin: 0.5rem 0 0; color: var(--muted); font-size: 0.92rem; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr));
  gap: 0.75rem;
  margin: 1.75rem 0 0;
}
.stats div {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 0.6rem;
  padding: 0.65rem 0.85rem;
}
.stats dt { color: var(--muted); font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; }
.stats dd { margin: 0.15rem 0 0; font-size: 1.4rem; font-variant-numeric: tabular-nums; font-weight: 600; }
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.4rem;
  margin: 1.5rem 0 0;
  color: var(--muted);
  font-size: 0.85rem;
}
.legend span::before {
  content: "";
  display: inline-block;
  width: 0.62em;
  height: 0.62em;
  margin-right: 0.4em;
  border-radius: 50%;
  background: currentColor;
  vertical-align: 0.02em;
}
.legend .same { color: var(--same); }
.legend .diff { color: var(--diff); }
.legend .neutral { color: var(--muted); }
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  margin-top: 1.5rem;
  padding: 1.1rem 1.35rem 1.35rem;
}
.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.35rem 1rem;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.6rem;
  margin-bottom: 1rem;
}
.card h2 { margin: 0; font-size: 1rem; letter-spacing: 0.02em; }
.card code { color: var(--muted); font-size: 0.82rem; overflow-wrap: anywhere; }
.text {
  margin: 0;
  font-family: ui-serif, Georgia, "Times New Roman", serif;
  font-size: 1.05rem;
  line-height: 1.95;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  hyphens: none;
}
.same { color: var(--same); }
.diff { color: var(--diff); background: var(--diff-bg); border-radius: 2px; }
footer { margin-top: 2rem; color: var(--muted); font-size: 0.82rem; line-height: 1.6; }
@media (max-width: 30rem) {
  main { padding-top: 1.75rem; }
  .card { padding: 0.9rem 1rem 1.15rem; }
}
"""


def render_page(
    comparison: Comparison,
    transcription: Transcription,
    *,
    audio_name: str,
    reference_name: str,
    generated_at: str | None = None,
) -> str:
    """Return a self-contained HTML report for one comparison."""
    stats = comparison.stats
    wer_text = "—" if stats.wer is None else f"{stats.wer:.1%}"

    language = transcription.language.upper() if transcription.language else "unknown language"
    if transcription.language_probability:
        language += f" ({transcription.language_probability:.0%})"
    model = f"{transcription.model} on {transcription.device} ({transcription.compute_type})"
    meta_bits = [
        model,
        language,
        formats.format_duration(transcription.duration),
        f"{transcription.speed:.1f}× realtime" if transcription.elapsed else "",
    ]
    meta = " · ".join(bit for bit in meta_bits if bit)

    timestamp = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    title = f"{audio_name} — transcript vs original"
    audio_label = html.escape(audio_name)
    reference_label = html.escape(reference_name)

    stat_cards = "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>"
        for label, value in (
            ("WER", wer_text),
            ("Reference words", f"{stats.reference_words:,}"),
            ("Matched", f"{stats.matched:,}"),
            ("Substituted", f"{stats.substitutions:,}"),
            ("Missing", f"{stats.deletions:,}"),
            ("Extra", f"{stats.insertions:,}"),
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">Whisper Lab · transcript comparison</p>
    <h1>{audio_label}</h1>
    <p class="meta">{html.escape(meta)}</p>
  </header>

  <section class="stats" aria-label="Summary">{stat_cards}</section>

  <p class="legend" aria-label="Legend">
    <span class="same">letters appear in both texts</span>
    <span class="diff">letters differ</span>
    <span class="neutral">punctuation, not compared</span>
  </p>

  <section class="card">
    <div class="card-head">
      <h2>Original text</h2>
      <code>{reference_label}</code>
    </div>
    <p class="text">{comparison.reference_html}</p>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>Whisper transcript</h2>
      <code>{html.escape(model)}</code>
    </div>
    <p class="text">{comparison.hypothesis_html}</p>
  </section>

  <footer>
    Generated by Whisper Lab on {html.escape(timestamp)}. Words are aligned first, then their
    letters are compared case-insensitively; punctuation and spacing are shown but not compared.
    "Missing" counts words in the original the transcript does not contain, "Extra" the reverse.
  </footer>
</main>
</body>
</html>
"""


# ------------------------------------------------------------- reference file


def find_reference(audio_path: Path, samples_dir: Path = config.SAMPLES_DIR) -> Path | None:
    """Locate the original text for ``audio_path``.

    The convention is ``<stem>.reference.txt`` next to the audio or in
    ``samples/`` -- ``samples/demo2.wav`` pairs with
    ``samples/demo2.reference.txt``. The numbered ``demo.reference1.txt`` style
    used by the older bundled clips is accepted as a fallback.
    """
    audio_path = Path(audio_path)
    stem = audio_path.stem
    candidates = [
        samples_dir / f"{stem}.reference.txt",
        audio_path.parent / f"{stem}.reference.txt",
    ]
    numbered = re.fullmatch(r"(.+?)(\d+)", stem)
    if numbered:
        candidates.append(samples_dir / f"{numbered.group(1)}.reference{numbered.group(2)}.txt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
