#!/usr/bin/env python
"""Transcribe audio or video files from the command line.

When a reference transcript exists (<name>.reference.txt in samples/ or next to
the audio), a static comparison page <name>.diff.html is written next to the
transcript, with matching letters in green and differing letters in red.

Examples:
    python transcribe.py samples/demo.wav
    python transcribe.py samples/demo2.wav --model small   # + demo2.diff.html
    python transcribe.py talk.mp4 --model large-v3-turbo --format srt --output-dir out
    python transcribe.py lecture.m4a --format all --words
    python transcribe.py meeting.mp3 --summarize
    python transcribe.py --list-models
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config
from whisper_lab import diff, formats
from whisper_lab.engine import Transcriber, cuda_device_count
from whisper_lab.llm import LLMUnavailable, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe audio/video with faster-whisper (local, no API key).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("audio", nargs="*", type=Path, help="Audio or video file(s) to transcribe")
    parser.add_argument(
        "--model",
        default=config.DEFAULT_MODEL,
        help=f"Whisper model name (default: {config.DEFAULT_MODEL}). See --list-models.",
    )
    parser.add_argument(
        "--device",
        default=config.DEFAULT_DEVICE,
        choices=["auto", "cuda", "cpu"],
        help="Compute device (default: auto)",
    )
    parser.add_argument(
        "--compute-type",
        default=config.DEFAULT_COMPUTE_TYPE,
        choices=["auto", "float16", "int8", "int8_float16", "float32"],
        help="Numeric precision (default: auto -> float16 on GPU, int8 on CPU)",
    )
    parser.add_argument("--language", default="auto", help="Language code such as en or cs (default: auto)")
    parser.add_argument(
        "--task",
        default="transcribe",
        choices=["transcribe", "translate"],
        help="transcribe in the source language, or translate to English",
    )
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=sorted(formats.FORMATTERS) + ["all"],
        help="Output format; repeat for several (default: txt)",
    )
    parser.add_argument("--output-dir", type=Path, help="Where to write transcripts (default: next to input)")
    parser.add_argument("--beam-size", type=int, default=config.BEAM_SIZE)
    parser.add_argument("--words", action="store_true", help="Include word-level timestamps")
    parser.add_argument("--initial-prompt", default=config.INITIAL_PROMPT, help="Vocabulary hint, e.g. names or acronyms")
    parser.add_argument("--no-vad", action="store_true", help="Disable voice-activity filtering")
    parser.add_argument("--summarize", action="store_true", help="Also summarize the transcript with Ollama")
    parser.add_argument("--quiet", action="store_true", help="Do not print segments while transcribing")
    parser.add_argument("--list-models", action="store_true", help="Show the model catalog and exit")
    return parser


def print_model_catalog() -> None:
    print(f"{'Model':<18} {'Download':<10} {'Speed':<8} Note")
    print("-" * 78)
    for model in config.MODEL_CATALOG:
        marker = " *" if model["name"] == config.DEFAULT_MODEL else ""
        print(
            f"{model['name'] + marker:<18} {model['size']:<10} "
            f"{model['speed']:<8} {model['note']}"
        )
    print("\n* default. Speed is relative to large-v3 on the same machine.")
    print(f"CUDA devices visible: {cuda_device_count()}")


def resolve_formats(requested: list[str] | None) -> list[str]:
    requested = requested or ["txt"]
    if "all" in requested:
        return ["txt", "srt", "vtt", "json", "md"]
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(requested))


def write_outputs(transcription, audio_path: Path, output_dir: Path, fmt_list: list[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in fmt_list:
        target = output_dir / f"{audio_path.stem}.{fmt}"
        target.write_text(formats.render(transcription, fmt), encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_models:
        print_model_catalog()
        return 0

    if not args.audio:
        print("error: give at least one audio file (or use --list-models)", file=sys.stderr)
        return 2

    missing = [path for path in args.audio if not path.exists()]
    if missing:
        for path in missing:
            print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    fmt_list = resolve_formats(args.formats)

    try:
        transcriber = Transcriber(
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
        )
    except Exception as exc:  # noqa: BLE001 - setup errors need a readable message
        print(f"error: could not load model {args.model!r}: {exc}", file=sys.stderr)
        return 1

    print(f"Model: {transcriber.label}")
    exit_code = 0

    for audio_path in args.audio:
        print(f"\n== {audio_path.name} ==")

        def on_segment(segment) -> None:
            if not args.quiet:
                print(
                    f"[{formats.format_timestamp(segment.start)} -> "
                    f"{formats.format_timestamp(segment.end)}] {segment.text.strip()}",
                    flush=True,
                )

        try:
            transcription = transcriber.transcribe(
                audio_path,
                language=args.language,
                task=args.task,
                beam_size=args.beam_size,
                vad_filter=not args.no_vad,
                initial_prompt=args.initial_prompt,
                word_timestamps=args.words,
                on_segment=on_segment,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"error: {audio_path.name}: {exc}", file=sys.stderr)
            exit_code = 1
            continue

        output_dir = args.output_dir or audio_path.parent
        written = write_outputs(transcription, audio_path, output_dir, fmt_list)

        print(
            f"\nLanguage: {transcription.language} "
            f"({transcription.language_probability:.0%}), "
            f"duration {formats.format_duration(transcription.duration)}, "
            f"processed in {transcription.elapsed:.1f} s "
            f"({transcription.speed:.1f}x realtime, RTF {transcription.rtf:.3f})"
        )
        print("Wrote: " + ", ".join(str(path) for path in written))

        reference_path = diff.find_reference(audio_path)
        if reference_path is not None:
            comparison = diff.compare(
                reference_path.read_text(encoding="utf-8-sig"),
                transcription.text,
            )
            page_path = output_dir / f"{audio_path.stem}.diff.html"
            page_path.write_text(
                diff.render_page(
                    comparison,
                    transcription,
                    audio_name=audio_path.name,
                    reference_name=reference_path.name,
                ),
                encoding="utf-8",
            )
            wer = comparison.stats.wer
            suffix = f" (WER {wer:.1%})" if wer is not None else ""
            print(f"Comparison: {page_path}{suffix}")

        if args.summarize:
            try:
                notes = summarize(transcription.text)
            except LLMUnavailable as exc:
                print(f"\nsummary skipped: {exc}", file=sys.stderr)
            else:
                notes_path = output_dir / f"{audio_path.stem}.notes.md"
                notes_path.write_text(notes + "\n", encoding="utf-8")
                print(f"Summary: {notes_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
