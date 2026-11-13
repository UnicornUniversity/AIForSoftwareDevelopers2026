"""Export raw and normalized ASR results.

Both ASR routes share this module so their artifacts are byte-comparable: the
same normalized schema produces the same TXT, SRT, and VTT layout. Every export
is derived from the normalized transcript, never from vendor types, except the
raw JSON file, which preserves the vendor result exactly for auditability.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.schema import NormalizedTranscript, write_json


class ExportError(RuntimeError):
    """Raised when a transcript cannot be written."""


#: Human-readable names for the ``system`` field. Unknown systems fall back to
#: the raw value so a future route does not need a code change just to export.
SYSTEM_LABELS = {
    "whisperx": "WhisperX",
    "gemini": "Gemini",
}


def jsonable(value: Any) -> Any:
    """Convert numpy scalars, paths, tuples, and non-finite floats for JSON."""

    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def format_timestamp(seconds: float, *, comma: bool = False) -> str:
    """Format ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT)."""

    if not math.isfinite(seconds):
        raise ExportError(f"timestamp is not finite: {seconds!r}")
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    separator = "," if comma else "."
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        f"{separator}{milliseconds:03d}"
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def system_label(system: str) -> str:
    return SYSTEM_LABELS.get(system, system or "ASR")


def _header(transcript: NormalizedTranscript) -> list[str]:
    audio = transcript.manifest.get("audio_file", "unknown")
    return [
        f"# {system_label(transcript.system)} transcript",
        f"# System: {transcript.system}",
        f"# Model: {transcript.model}",
        f"# Language: {transcript.language}",
        f"# Audio: {audio}",
        f"# Segments: {len(transcript.segments)}",
        "# Speaker labels are anonymous diarization clusters, not participant",
        "# names. UNKNOWN means the diarizer did not attribute the segment.",
        "",
    ]


def render_txt(transcript: NormalizedTranscript) -> str:
    lines = _header(transcript)
    for segment in transcript.segments:
        lines.append(
            f"{segment.speaker_label}: {_one_line(segment.text)}"
        )
    return "\n".join(lines) + "\n"


def render_srt(transcript: NormalizedTranscript) -> str:
    blocks: list[str] = []
    for number, segment in enumerate(transcript.segments, start=1):
        blocks.append(
            f"{number}\n"
            f"{format_timestamp(segment.start, comma=True)} --> "
            f"{format_timestamp(segment.end, comma=True)}\n"
            f"{segment.speaker_label}: {_one_line(segment.text)}\n"
        )
    return "\n".join(blocks) if blocks else ""


def render_vtt(transcript: NormalizedTranscript) -> str:
    blocks = ["WEBVTT\n"]
    for segment in transcript.segments:
        blocks.append(
            f"{format_timestamp(segment.start)} --> "
            f"{format_timestamp(segment.end)}\n"
            f"{segment.speaker_label}: {_one_line(segment.text)}\n"
        )
    return "\n".join(blocks)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_raw_json(path: Path | str, raw: Mapping[str, Any]) -> Path:
    target = Path(path)
    write_json(target, jsonable(raw))
    return target


def write_normalized_json(
    path: Path | str, transcript: NormalizedTranscript
) -> Path:
    target = Path(path)
    write_json(target, transcript.to_dict())
    return target


def export_all(
    out_dir: Path | str,
    transcript: NormalizedTranscript,
    raw: Mapping[str, Any],
    *,
    raw_filename: str,
) -> dict[str, Path]:
    """Write raw JSON, normalized JSON, TXT, SRT, and VTT. Returns the paths."""

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "raw": write_raw_json(directory / raw_filename, raw),
        "json": write_normalized_json(directory / "transcript.json", transcript),
        "txt": directory / "transcript.txt",
        "srt": directory / "transcript.srt",
        "vtt": directory / "transcript.vtt",
    }
    _write_text(paths["txt"], render_txt(transcript))
    _write_text(paths["srt"], render_srt(transcript))
    _write_text(paths["vtt"], render_vtt(transcript))
    return paths


def raw_json_text(raw: Mapping[str, Any]) -> str:
    """Raw JSON as text, used by tests and by the manifest's integrity note."""

    return json.dumps(jsonable(raw), ensure_ascii=False, indent=2) + "\n"
