"""Small helpers shared by both ASR routes."""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path


def sha256_file(path: Path | str) -> str:
    """SHA-256 of a file, streamed so a long recording does not load at once."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_versions() -> dict[str, str]:
    """Python and platform versions recorded in every run manifest."""

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
