"""English micro-typography: smart quotes, dashes, and a matcher for quotes.

The rules come from the assignment brief: English “66–99” double quotes (both
glyphs at the top), no Czech „…“ quotes, no straight typewriter quotes, an
unspaced em dash or spaced en dash for sentence breaks, an unspaced en dash for
ranges, and no non-breaking spaces around single-letter words.
"""

from __future__ import annotations

import re
import unicodedata

_OPEN_CONTEXT = set(" \t\n\r([{—–-/")


def _smart_double(text: str) -> str:
    out: list[str] = []
    is_open = False
    for index, char in enumerate(text):
        previous = text[index - 1] if index else ""
        if char == '"':
            opens = not is_open and (not previous or previous in _OPEN_CONTEXT)
            if opens:
                out.append("“")
                is_open = True
            else:
                out.append("”")
                is_open = False
        elif char == "„":  # Czech opening quote
            out.append("“")
            is_open = True
        elif char == "“":
            if is_open:
                out.append("”")
                is_open = False
            else:
                out.append("“")
                is_open = True
        elif char == "”":
            out.append("”")
            is_open = False
        else:
            out.append(char)
    return "".join(out)


def _smart_single(text: str) -> str:
    out: list[str] = []
    for index, char in enumerate(text):
        previous = text[index - 1] if index else ""
        if char == "'":
            if previous.isalnum():
                out.append("’")
            elif not previous or previous in _OPEN_CONTEXT:
                out.append("‘")
            else:
                out.append("’")
        else:
            out.append(char)
    return "".join(out)


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_PROTECT = ""


def _dashes(text: str, config: dict) -> str:
    sentence = config.get("dashes", {}).get("sentence", "em")
    range_style = config.get("dashes", {}).get("range", "en")

    # A full ISO date is not a range: keep 2026-10-23 intact while 1998-2024
    # still becomes 1998–2024.
    guarded: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        key = f"{_PROTECT}{len(guarded)}{_PROTECT}"
        guarded[key] = match.group(0)
        return key

    text = _ISO_DATE.sub(protect, text)

    text = text.replace("--", "—")
    if sentence == "em":
        text = text.replace(" - ", "—")
    elif sentence == "en":
        text = text.replace(" - ", " – ")
    # else: leave a spaced hyphen alone (explicitly configured)

    if range_style == "en":
        text = re.sub(r"(?<=\d)-(?=\d)", "–", text)
    elif range_style == "em":
        text = re.sub(r"(?<=\d)-(?=\d)", "—", text)

    for key, original in guarded.items():
        text = text.replace(key, original)
    return text


def apply(text: str, config: dict) -> str:
    """Apply the configured English typography to one piece of text."""

    if not text:
        return text
    text = _smart_double(text)
    text = _smart_single(text)
    text = _dashes(text, config)
    # The brief explicitly says single-letter words may sit at a line end.
    # No NBSP insertion happens here; the setting is recorded so a future
    # renderer cannot quietly disagree with it.
    return text


def residual_issues(text: str) -> list[str]:
    """Report typographic problems that survive normalisation."""

    issues: list[str] = []
    if '"' in text:
        issues.append("straight double quote (use English smart quotes)")
    if "'" in text:
        issues.append("straight single quote or apostrophe")
    if "„" in text:
        issues.append("Czech opening quote „")
    if re.search(r"(?<=\S) - (?=\S)", text):
        issues.append("spaced hyphen used as a dash (use an em or en dash)")
    if " " in text:
        issues.append("non-breaking space (not wanted for single-letter words)")
    return issues


def normalise_for_match(text: str) -> str:
    """Fold glyph differences so verbatim checks compare wording, not fonts."""

    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def split_elision(text: str) -> list[str]:
    """Split a quotation on ellipses so elided quotes can still be checked."""

    parts = re.split(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*", text)
    return [part for part in (p.strip() for p in parts) if part]
