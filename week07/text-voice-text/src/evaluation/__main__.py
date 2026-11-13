"""Command-line entry point for evaluation and comparison.

Run from the project root after one or both ASR routes have produced output:

    python -m src.evaluation build
    python -m src.evaluation build --whisperx-dir outputs/whisperx
    python -m src.evaluation build --meeting-manifest audio/meeting_manifest.json

It reads ``transcript.json`` and ``run_manifest.json`` from each route's output
directory, the fixture's ground truth, and — when it exists — the meeting
timeline. It writes ``comparison.json``, ``comparison.md`` and
``comparison.html`` under ``outputs/comparison/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import config
from src.evaluation.compare import ComparisonError, build_comparison
from src.evaluation.report import SYSTEM_LABELS, write_reports


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.evaluation",
        description=(
            "Compare the WhisperX and Gemini transcripts with the ground truth"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="write comparison.json, .md, and .html")
    build.add_argument(
        "--whisperx-dir", type=Path, default=config.WHISPERX_OUTPUT_DIR
    )
    build.add_argument("--gemini-dir", type=Path, default=config.GEMINI_OUTPUT_DIR)
    build.add_argument("--out-dir", type=Path, default=config.COMPARISON_OUTPUT_DIR)
    build.add_argument(
        "--meeting-manifest",
        type=Path,
        default=config.MEETING_MANIFEST_PATH,
        help="generated timeline for DER; absent means DER is unavailable",
    )
    return parser


def _fmt(value, places: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def cmd_build(args: argparse.Namespace) -> int:
    try:
        document = build_comparison(
            whisperx_dir=args.whisperx_dir,
            gemini_dir=args.gemini_dir,
            meeting_manifest_path=args.meeting_manifest,
        )
    except ComparisonError as exc:
        print(f"\nCannot build the comparison:\n\n{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"\nCannot build the comparison:\n\n{exc}", file=sys.stderr)
        return 1

    paths = write_reports(document, args.out_dir)

    fixture = document["fixture"]
    print(
        f"Reference: {fixture['turn_count']} turns, "
        f"{fixture['reference_words']} words ({fixture['meeting_id']})"
    )
    print()
    print(f"{'system':<22}{'WER':>8}{'S':>6}{'D':>6}{'I':>6}{'DER':>9}")
    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        label = SYSTEM_LABELS[system]
        if not block.get("available"):
            print(f"{label:<22}{'not run':>8}")
            continue
        wer = block["wer_verbatim"]
        der = (block.get("speaker") or {}).get("der") or {}
        der_text = _fmt(der.get("der")) if der.get("available") else "n/a"
        print(
            f"{label:<22}{_fmt(wer.get('wer')):>8}"
            f"{wer.get('substitutions'):>6}{wer.get('deletions'):>6}"
            f"{wer.get('insertions'):>6}{der_text:>9}"
        )
    print()
    print("WER is word-level and does not measure speaker diarization.")
    for system in ("whisperx", "gemini"):
        block = document["systems"][system]
        if block.get("available"):
            speaker = block.get("speaker") or {}
            der = speaker.get("der") or {}
            if der.get("available") is False:
                print(
                    f"  {SYSTEM_LABELS[system]}: DER unavailable "
                    f"({der.get('reason')}); reported as unavailable, not zero."
                )
            elif speaker.get("method") == "text_alignment":
                print(
                    f"  {SYSTEM_LABELS[system]}: speaker comparison used word "
                    "alignment because no generated timeline exists."
                )

    print()
    for name in ("json", "markdown", "html"):
        print(f"  {name:8} {paths[name]}")
    return 0


COMMANDS = {"build": cmd_build}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
