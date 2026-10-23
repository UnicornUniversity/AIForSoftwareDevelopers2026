"""Subject parsing and prompt composition for image-forge.

A *task* pairs one prompt template with a list of *subjects*. Subjects come
from three places, in order: `source` files, an inline `subjects` list, and an
inline `subjects` mapping. A subject becomes one generated image; its filename
stem is derived from its name according to the task's `naming` rules.

Prompts are assembled in this order, separated by blank lines:

    1. global `style` (or the task's own `style` override)
    2. task `style_extra`
    3. task `prompt` with {subject}, {name}, {stem}, {task} substituted
    4. subject `extra`

A subject `prompt` replaces all four with a verbatim prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import ConfigError, Settings, resolve_naming

# Words that are table headers rather than subject names.
_HEADER_WORDS = {"id", "name", "subject", "asset", "title"}


@dataclass
class Subject:
    """One image to generate."""

    raw: str
    stem: str
    description: str = ""
    prompt: str | None = None
    extra: str = ""
    base: str | None = None
    base_is_file: bool = False
    appearance: Any = None


_IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def _looks_like_path(value: str) -> bool:
    return (
        Path(value).suffix.lower() in _IMAGE_SUFFIXES
        or "/" in value
        or "\\" in value
    )


def normalize_stem(raw: str, case: str = "lower", separator: str = "_") -> str:
    """Turn a human name into a portable filename stem."""
    stem = raw.strip()
    stem = re.sub(r"\s+", separator, stem)
    stem = stem.replace("-", separator)
    if case == "upper":
        stem = stem.upper()
    elif case == "lower":
        stem = stem.lower()
    stem = re.sub(r"[^A-Za-z0-9_\-]", "", stem)
    stem = re.sub(re.escape(separator) + r"{2,}", separator, stem)
    stem = stem.strip(separator)
    if not stem:
        raise ConfigError(f"subject name {raw!r} produces an empty filename")
    return stem


def parse_markdown_table(text: str) -> list[tuple[str, str]]:
    """Read the first two columns of every Markdown table row.

    The first column is the subject name. The optional second column is the
    description used in the prompt; leave it out and the name is used instead.
    """
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        # Separator row: |---|---| or |:--|--:|
        if set(stripped.replace("|", "").strip()) <= set("-: "):
            in_table = True
            continue
        if not in_table:
            continue
        cells = [cell.strip().strip("`").strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        raw = cells[0]
        if not raw or raw.lower() in _HEADER_WORDS:
            continue
        description = cells[1] if len(cells) > 1 else ""
        rows.append((raw, description))
    return rows


def parse_line_list(text: str) -> list[tuple[str, str]]:
    """Read `name` or `name | description` lines, ignoring blanks and #."""
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        raw, sep, description = stripped.partition("|")
        raw = raw.strip().strip("`").strip()
        if not raw:
            continue
        rows.append((raw, description.strip() if sep else ""))
    return rows


def parse_source(path: Path) -> list[tuple[str, str]]:
    """Read a `.md` table or a plain `name | description` list."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read source file {path}: {exc}") from exc

    if path.suffix.lower() in {".md", ".markdown"}:
        rows = parse_markdown_table(text)
        if rows:
            return rows
    return parse_line_list(text)


def _subject_from_options(
    raw: str, description: str, options: dict[str, Any]
) -> Subject:
    return Subject(
        raw=raw,
        stem="",  # filled in by collect_subjects
        description=options.get("description", options.get("subject", description)),
        prompt=options.get("prompt"),
        extra=options.get("extra") or "",
        base=options.get("base"),
        appearance=options.get("appearance"),
    )


def collect_subjects(settings: Settings, task_name: str) -> list[Subject]:
    """Resolve every subject declared by a task, with stems and bases."""
    task = settings.tasks[task_name]
    where = f"tasks.{task_name}"
    naming = resolve_naming(task, where)
    case, separator = naming["case"], naming["separator"]

    subjects: list[Subject] = []
    seen: dict[str, str] = {}

    def add(raw: str, description: str = "", options: dict[str, Any] | None = None) -> None:
        raw = raw.strip()
        if not raw:
            raise ConfigError(f"{where}: empty subject name")
        stem = normalize_stem(raw, case, separator)
        if stem in seen:
            raise ConfigError(
                f"{where}: subjects {seen[stem]!r} and {raw!r} both map to "
                f"filename {stem!r}; rename one or change `naming.separator`"
            )
        seen[stem] = raw
        subject = _subject_from_options(raw, description, options or {})
        subject.stem = stem
        subjects.append(subject)

    source = task.get("source")
    if source:
        paths = [source] if isinstance(source, str) else list(source)
        for entry in paths:
            path = (settings.base_dir / entry).resolve()
            if not path.exists():
                raise ConfigError(f"{where}.source: file not found: {path}")
            for raw, description in parse_source(path):
                add(raw, description)

    inline = task.get("subjects")
    if isinstance(inline, list):
        for raw in inline:
            add(raw)
    elif isinstance(inline, dict):
        for raw, value in inline.items():
            if value is None:
                add(str(raw))
            elif isinstance(value, str):
                add(str(raw), value)
            elif isinstance(value, dict):
                add(str(raw), "", value)
            else:
                raise ConfigError(
                    f"{where}.subjects[{raw!r}]: must be a description string or a mapping"
                )

    if not subjects:
        raise ConfigError(
            f"{where}: no subjects. Add `subjects:` or point `source:` at a list."
        )

    by_key: dict[str, Subject] = {}
    for subject in subjects:
        by_key[subject.raw] = subject
        by_key[subject.stem] = subject

    for subject in subjects:
        if not subject.base:
            continue
        raw_base = str(subject.base)
        target = by_key.get(raw_base) or by_key.get(
            normalize_stem(raw_base, case, separator)
        )
        if target is subject:
            raise ConfigError(f"{where}: subject {subject.raw!r} cannot use itself as `base`")
        if target is not None:
            subject.base = target.stem
        elif _looks_like_path(raw_base):
            # An explicit reference image, resolved from the settings file.
            subject.base = raw_base
            subject.base_is_file = True
        else:
            # A base generated by an earlier run: keep the normalized stem so
            # the planner can look it up on disk.
            subject.base = normalize_stem(raw_base, case, separator)

    return subjects


def _render(text: str, subject_text: str, stem: str, task_name: str) -> str:
    return (
        text.replace("{subject}", subject_text)
        .replace("{name}", subject_text)
        .replace("{stem}", stem)
        .replace("{task}", task_name)
    )


def build_prompt(settings: Settings, task_name: str, subject: Subject) -> str:
    """Compose the final prompt for one subject."""
    task = settings.tasks[task_name]

    if subject.prompt is not None:
        prompt = subject.prompt.strip()
        if not prompt:
            raise ConfigError(f"tasks.{task_name}: subject {subject.raw!r} has an empty prompt")
        return prompt

    style = task["style"] if "style" in task else settings.style
    style = (style or "").strip()
    style_extra = (task.get("style_extra") or "").strip()
    template = (task.get("prompt") or "").strip()
    subject_text = (subject.description or subject.raw).strip()

    parts = [
        _render(style, subject_text, subject.stem, task_name),
        _render(style_extra, subject_text, subject.stem, task_name),
        _render(template, subject_text, subject.stem, task_name),
        _render(subject.extra, subject_text, subject.stem, task_name),
    ]
    prompt = "\n\n".join(part for part in parts if part).strip()
    if not prompt:
        raise ConfigError(
            f"tasks.{task_name}: subject {subject.raw!r} has no prompt text. "
            f"Add `prompt:` to the task, `extra:` to the subject, or a global `style:`."
        )
    return prompt
