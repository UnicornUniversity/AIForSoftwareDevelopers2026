"""Convert a ``Transcription`` into the formats people actually use.

TXT for notes, SRT/VTT for players and YouTube, JSON when another program
consumes the result.
"""

from __future__ import annotations

import json

from .engine import Transcription


def _clock(seconds: float, *, srt: bool) -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def srt_timestamp(seconds: float) -> str:
    return _clock(seconds, srt=True)


def vtt_timestamp(seconds: float) -> str:
    return _clock(seconds, srt=False)


def to_txt(transcription: Transcription) -> str:
    return transcription.text + "\n"


def to_srt(transcription: Transcription) -> str:
    blocks = []
    for index, segment in enumerate(transcription.segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{srt_timestamp(segment.start)} --> {srt_timestamp(segment.end)}\n"
            f"{segment.text.strip()}\n"
        )
    return "\n".join(blocks)


def to_vtt(transcription: Transcription) -> str:
    lines = ["WEBVTT", ""]
    for segment in transcription.segments:
        lines.append(f"{vtt_timestamp(segment.start)} --> {vtt_timestamp(segment.end)}")
        lines.append(segment.text.strip())
        lines.append("")
    return "\n".join(lines)


def to_json(transcription: Transcription) -> str:
    return json.dumps(transcription.to_dict(), ensure_ascii=False, indent=2)


def to_markdown(transcription: Transcription, *, timestamps: bool = True) -> str:
    """A readable transcript with one paragraph per segment."""
    lines = [
        "# Transcript",
        "",
        (
            f"**Language:** {transcription.language} "
            f"({transcription.language_probability:.0%} confidence)  "
        ),
        f"**Duration:** {format_duration(transcription.duration)}  ",
        (
            f"**Model:** {transcription.model} on {transcription.device} "
            f"({transcription.compute_type})"
        ),
        "",
    ]
    for segment in transcription.segments:
        prefix = f"**[{format_timestamp(segment.start)}]** " if timestamps else ""
        lines.append(prefix + segment.text.strip())
        lines.append("")
    return "\n".join(lines)


def format_timestamp(seconds: float) -> str:
    """mm:ss for short audio, h:mm:ss for long audio."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes} min {secs} s"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


FORMATTERS = {
    "txt": to_txt,
    "srt": to_srt,
    "vtt": to_vtt,
    "json": to_json,
    "md": to_markdown,
}


def render(transcription: Transcription, fmt: str) -> str:
    try:
        formatter = FORMATTERS[fmt]
    except KeyError:
        supported = ", ".join(sorted(FORMATTERS))
        raise ValueError(f"Unsupported format {fmt!r}; choose one of: {supported}") from None
    return formatter(transcription)
