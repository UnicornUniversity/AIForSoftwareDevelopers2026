"""Errors that carry enough context for the CLI to print an actionable message."""

from __future__ import annotations

from pathlib import Path

# Exit codes shared by the whole CLI.
EXIT_USAGE = 2
EXIT_CORPUS = 3
EXIT_CONTENT = 4
EXIT_RENDER = 5


class BookError(Exception):
    """A failure the user can act on.

    ``file``, ``line`` and ``key`` are optional locators; the formatted message
    names whichever are known, e.g. ``settings.json: page.margins_cm.left:
    must be between 0 and 10``.
    """

    def __init__(
        self,
        message: str,
        *,
        file: Path | str | None = None,
        line: int | None = None,
        key: str | None = None,
        exit_code: int = EXIT_USAGE,
    ) -> None:
        self.message = message
        self.file = Path(file) if file is not None else None
        self.line = line
        self.key = key
        self.exit_code = exit_code
        super().__init__(self.formatted)

    @property
    def formatted(self) -> str:
        parts: list[str] = []
        if self.file is not None:
            parts.append(str(self.file))
        if self.line is not None:
            parts.append(f"line {self.line}")
        if self.key is not None:
            parts.append(self.key)
        prefix = ": ".join(parts)
        return f"{prefix}: {self.message}" if prefix else self.message


class SettingsError(BookError):
    """Invalid or unreadable settings file."""


class CorpusError(BookError):
    """Missing corpus, manifest or source file."""

    def __init__(self, message: str, **kwargs) -> None:
        kwargs.setdefault("exit_code", EXIT_CORPUS)
        super().__init__(message, **kwargs)


class ContentError(BookError):
    """Invalid plan, front matter or chapter file."""

    def __init__(self, message: str, **kwargs) -> None:
        kwargs.setdefault("exit_code", EXIT_CONTENT)
        super().__init__(message, **kwargs)


class RenderError(BookError):
    """The Word document could not be produced."""

    def __init__(self, message: str, **kwargs) -> None:
        kwargs.setdefault("exit_code", EXIT_RENDER)
        super().__init__(message, **kwargs)
