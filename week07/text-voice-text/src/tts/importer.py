"""Import an externally generated meeting WAV without changing it.

The manual fallback exists so an instructor can build the whole meeting in
Google AI Studio, or bring a recording made elsewhere, and still run both ASR
routes. The file is copied byte-for-byte: the one-WAV rule means neither ASR
system may receive a different rendition.

An imported WAV has no per-turn segment manifest, so no time-aligned reference
timeline can be derived. The manifest says so explicitly; DER must then be
reported as unavailable.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from src.schema import MeetingAudioManifest, write_json
from src.tts.audio import AudioError, inspect_wav, sha256_file
from src.tts.segments import environment_info, utc_now

logger = logging.getLogger(__name__)


class WavImportError(RuntimeError):
    """Raised when an imported WAV is missing, unreadable, or unsupported."""


_SUPPORTED_SUBTYPES = {
    "PCM_16",
    "PCM_24",
    "PCM_32",
    "FLOAT",
    "DOUBLE",
}


def import_meeting_wav(
    source: Path | str,
    destination: Path | str,
    *,
    fixture_id: str,
    meeting_id: str,
    manifest_path: Path | str | None = None,
    force: bool = False,
) -> MeetingAudioManifest:
    """Copy a WAV unchanged and record how it was obtained."""

    source_path = Path(source)
    destination_path = Path(destination)

    if not source_path.exists():
        raise WavImportError(f"audio file not found: {source_path}")
    if not source_path.is_file():
        raise WavImportError(f"not a file: {source_path}")
    if destination_path.exists() and source_path.resolve() == destination_path.resolve():
        raise WavImportError("source and destination are the same file")
    if destination_path.exists() and not force:
        raise WavImportError(
            f"{destination_path} already exists; pass --force to replace it"
        )

    try:
        info = inspect_wav(source_path)
    except AudioError as exc:
        raise WavImportError(str(exc)) from exc

    if info.format.upper() != "WAV":
        raise WavImportError(
            f"{source_path}: expected a WAV file, got {info.format}. Convert "
            "outside this lab, or use the per-turn Google AI Studio workflow."
        )
    if info.subtype not in _SUPPORTED_SUBTYPES:
        raise WavImportError(
            f"{source_path}: unsupported WAV encoding {info.subtype!r}. Export "
            "16-bit PCM WAV (or 24/32-bit PCM / float) before importing."
        )
    if info.frames == 0:
        raise WavImportError(f"{source_path}: the WAV contains no audio frames")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination_path)

    manifest_path = (
        Path(manifest_path)
        if manifest_path is not None
        else destination_path.with_name("meeting_manifest.json")
    )
    manifest = MeetingAudioManifest(
        schema_version="1.0",
        fixture_id=fixture_id,
        meeting_id=meeting_id,
        audio_file=str(destination_path),
        source="imported",
        model=None,
        sample_rate=info.sample_rate,
        channels=info.channels,
        sample_width_bytes=info.sample_width_bytes,
        duration_seconds=info.duration_seconds,
        turn_pause_ms=0,
        section_pause_ms=0,
        timeline=(),
        environment=environment_info(),
        notes=(
            "Imported file copied unchanged; both ASR routes must use this exact file.",
            "No segment manifest exists for an imported meeting: a time-aligned "
            "reference timeline is unavailable, so DER cannot be reported.",
            f"Imported on {utc_now()} from {source_path}.",
            f"SHA-256: {sha256_file(destination_path)}",
        ),
    )
    write_json(manifest_path, manifest.to_dict())
    logger.info("imported %s -> %s", source_path, destination_path)
    return manifest
