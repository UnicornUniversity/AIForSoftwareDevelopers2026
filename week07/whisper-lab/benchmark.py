#!/usr/bin/env python
"""Compare Whisper model sizes on one recording.

For each model this measures:
  * load time        - download/initialise cost (first run includes the download)
  * transcription    - seconds of compute for the whole file
  * speed            - seconds of audio per second of compute
  * WER              - word error rate against a reference transcript, if given

This is the week 7 lesson in miniature: quality, cost, and latency are a
trade-off, and the right model depends on the job.

Examples:
    python benchmark.py samples/demo.wav --models tiny base small --reference samples/demo.reference.txt
    python benchmark.py talk.mp3 --models small large-v3-turbo --device cuda
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import time
from pathlib import Path

import config
from whisper_lab.engine import Transcriber, cuda_device_count


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace before scoring.

    Punctuation and capitalisation are style choices; WER should measure what
    was heard, not how it was typed.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_error_rate(reference: str, hypothesis: str) -> float:
    try:
        import jiwer
    except ImportError:
        raise SystemExit("jiwer is not installed. Run: python -m pip install -r requirements.txt") from None
    return float(jiwer.wer(normalize(reference), normalize(hypothesis)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path, help="Recording to benchmark")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["tiny", "base", "small"],
        help="Model names to compare (default: tiny base small)",
    )
    parser.add_argument("--reference", type=Path, help="Text file with the correct transcript (for WER)")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--device", default=config.DEFAULT_DEVICE, choices=["auto", "cuda", "cpu"])
    parser.add_argument("--compute-type", default=config.DEFAULT_COMPUTE_TYPE)
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.audio.exists():
        print(f"error: file not found: {args.audio}", file=sys.stderr)
        return 2

    if args.reference and not args.reference.exists():
        print(f"error: reference not found: {args.reference}", file=sys.stderr)
        return 2
    reference = args.reference.read_text(encoding="utf-8") if args.reference else None

    print(f"Audio: {args.audio}  |  CUDA devices: {cuda_device_count()}")
    rows: list[dict] = []

    for model_name in args.models:
        print(f"\n== {model_name} ==")
        load_started = time.perf_counter()
        try:
            transcriber = Transcriber(
                model_name=model_name,
                device=args.device,
                compute_type=args.compute_type,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped: {exc}", file=sys.stderr)
            rows.append({"model": model_name, "error": str(exc)})
            continue
        load_seconds = time.perf_counter() - load_started

        try:
            result = transcriber.transcribe(
                args.audio,
                language=args.language,
                vad_filter=not args.no_vad,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}", file=sys.stderr)
            rows.append({"model": model_name, "error": str(exc)})
            continue

        row = {
            "model": model_name,
            "device": result.device,
            "compute_type": result.compute_type,
            "duration_s": round(result.duration, 2),
            "load_s": round(load_seconds, 2),
            "transcribe_s": round(result.elapsed, 2),
            "speed_x": round(result.speed, 2),
            "rtf": round(result.rtf, 3),
            "language": result.language,
            "language_probability": round(result.language_probability, 3),
            "characters": len(result.text),
        }
        if reference is not None:
            row["wer"] = round(word_error_rate(reference, result.text), 4)
        rows.append(row)

        print(
            f"  load {load_seconds:.1f}s  |  transcribe {result.elapsed:.1f}s  |  "
            f"{result.speed:.1f}x realtime"
            + (f"  |  WER {row['wer']:.1%}" if "wer" in row else "")
        )

        # Release VRAM before loading the next model.
        del transcriber
        gc.collect()

    print("\n## Results\n")
    headers = ["Model", "Device", "Load (s)", "Transcribe (s)", "Speed", "WER"]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        if "error" in row:
            print(f"| {row['model']} | error | - | - | - | - |")
            continue
        wer = f"{row['wer']:.1%}" if "wer" in row else "-"
        print(
            f"| {row['model']} | {row['device']}/{row['compute_type']} | "
            f"{row['load_s']} | {row['transcribe_s']} | {row['speed_x']}x | {wer} |"
        )

    args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved raw results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
