"""WhisperX exports.

The implementation moved to :mod:`src.asr.export` so both ASR routes write the
same TXT/SRT/VTT layout. This module keeps the WhisperX-facing names and the
historic ``whisperx_raw.json`` default, so existing callers and tests are
unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.asr.export import (
    ExportError,
    format_timestamp,
    jsonable,
    raw_json_text,
    render_srt,
    render_txt,
    render_vtt,
    system_label,
    write_normalized_json,
    write_raw_json,
)
from src.asr.export import export_all as _export_all
from src.schema import NormalizedTranscript


def export_all(
    out_dir: Path | str,
    transcript: NormalizedTranscript,
    raw: Mapping[str, Any],
    *,
    raw_filename: str = "whisperx_raw.json",
) -> dict[str, Path]:
    """Write raw JSON, normalized JSON, TXT, SRT, and VTT. Returns the paths."""

    return _export_all(
        out_dir, transcript, raw, raw_filename=raw_filename
    )


__all__ = [
    "ExportError",
    "export_all",
    "format_timestamp",
    "jsonable",
    "raw_json_text",
    "render_srt",
    "render_txt",
    "render_vtt",
    "system_label",
    "write_normalized_json",
    "write_raw_json",
]
