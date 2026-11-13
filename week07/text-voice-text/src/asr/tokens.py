"""Hugging Face token access for gated pyannote models.

The token is read from the environment (``HF_TOKEN``) only. There is no
command-line flag and no configuration field, so a token cannot be pasted into
a shell history, a manifest, or a notebook cell in this project.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from src import config


class MissingHFTokenError(RuntimeError):
    """Raised when diarization is requested without a Hugging Face token."""


DIARIZATION_MODEL_URL = (
    "https://huggingface.co/pyannote/speaker-diarization-community-1"
)
TOKEN_URL = "https://huggingface.co/settings/tokens"
JOIN_URL = "https://huggingface.co/join"


def load_environment(path: Path | None = None) -> None:
    """Load ``.env`` if python-dotenv is available; called by the CLI only.

    The token itself is still read from the environment, and an already-set
    environment variable wins over the file (``override=False``).
    """

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - requirements installs it
        return
    load_dotenv(path if path is not None else config.ENV_FILE, override=False)


def load_hf_token(env: Mapping[str, str] | None = None) -> str | None:
    """Return the token from the environment, or ``None``. Never logs it."""

    source = os.environ if env is None else env
    value = source.get(config.HF_TOKEN_ENV, "").strip()
    return value or None


def missing_token_message() -> str:
    """Instructor-facing setup steps, with no secret material."""

    return (
        f"{config.HF_TOKEN_ENV} is not set, so pyannote diarization cannot "
        "download its gated model.\n\n"
        "1. Create a free Hugging Face account: " + JOIN_URL + "\n"
        "2. Sign in and accept the model conditions at:\n"
        "   " + DIARIZATION_MODEL_URL + "\n"
        "   (If the pipeline asks for another gated model, accept that page too.)\n"
        "3. Create a read token: " + TOKEN_URL + "\n"
        f"4. Put {config.HF_TOKEN_ENV}=... in .env (see .env.example) or set it\n"
        "   in the environment, then rerun.\n\n"
        "Never commit the token. Use --no-diarize to run ASR and alignment "
        "without diarization."
    )


def require_hf_token(env: Mapping[str, str] | None = None) -> str:
    token = load_hf_token(env)
    if not token:
        raise MissingHFTokenError(missing_token_message())
    return token
