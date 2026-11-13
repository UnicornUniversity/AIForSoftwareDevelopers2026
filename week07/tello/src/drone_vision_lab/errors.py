"""Application-level exceptions.

Every exception carries a ``user_message`` suitable for a dialog box. Internal
details stay in the exception and the log; the UI shows the actionable part and
never a raw traceback.
"""

from __future__ import annotations

__all__ = [
    "AppError",
    "ConfigurationError",
    "HardwareUnavailableError",
    "OllamaResponseError",
    "OllamaUnavailableError",
    "VisionError",
    "user_message",
]


class AppError(Exception):
    """Base class for expected, user-facing failures."""

    default_user_message = "An unexpected error occurred."

    def __init__(self, message: str = "", *, user_message: str | None = None) -> None:
        super().__init__(message or user_message or self.default_user_message)
        self.user_message = user_message or message or self.default_user_message


class ConfigurationError(AppError):
    """A profile, setting or path is missing or invalid."""

    default_user_message = "The configuration is invalid or incomplete."


class HardwareUnavailableError(AppError):
    """The drone, camera or input device is missing, disconnected or unresponsive."""

    default_user_message = "The requested hardware is not available."


class VisionError(AppError):
    """A detector, model or vision service failed."""

    default_user_message = "The vision component failed."


class OllamaUnavailableError(VisionError):
    """Ollama is not running, not reachable, or timed out."""

    default_user_message = (
        "The Ollama service is not reachable. Start Ollama and check the base URL."
    )


class OllamaResponseError(VisionError):
    """Ollama answered, but not with something this client understands."""

    default_user_message = "Ollama returned an unexpected response."


def user_message(exc: BaseException) -> str:
    """Best human-readable description available for an exception."""
    if isinstance(exc, AppError):
        return exc.user_message
    return f"Unexpected error: {type(exc).__name__}: {exc}"
