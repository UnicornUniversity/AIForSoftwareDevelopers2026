"""Command-line entry point for the local WhisperX + pyannote route.

Run from the project root:

    python -m src.asr.whisperx check
    python -m src.asr.whisperx run
    python -m src.asr.whisperx run --device cpu --no-diarize
    python -m src.asr.whisperx run --model large-v3 --device cuda
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from pathlib import Path

from src import config
from src.asr.audio import AudioLoadError
from src.asr.tokens import (
    MissingHFTokenError,
    load_environment,
    load_hf_token,
)
from src.asr.whisperx.engine import (
    COMPUTE_TYPES,
    LocalASRError,
    ModelDownloadError,
    UnsupportedDeviceError,
    WhisperXDependencyError,
    default_compute_type,
    dependency_versions,
    load_whisperx,
    resolve_device,
)
from src.asr.whisperx.runner import RunError, RunSettings, run_local_asr

logger = logging.getLogger("src.asr.whisperx")


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=config.WHISPERX_MODEL)
    parser.add_argument("--language", default=config.WHISPERX_LANGUAGE)
    parser.add_argument(
        "--device",
        choices=config.WHISPERX_DEVICES,
        default=config.WHISPERX_DEVICE_AUTO,
    )
    parser.add_argument("--compute-type", choices=COMPUTE_TYPES, default=None)
    parser.add_argument("--batch-size", type=int, default=config.WHISPERX_BATCH_SIZE)
    parser.add_argument("--align-model", default=config.WHISPERX_ALIGN_MODEL)
    parser.add_argument(
        "--diarization-model", default=config.WHISPERX_DIARIZATION_MODEL
    )
    parser.add_argument("--no-align", dest="align", action="store_false")
    parser.add_argument("--no-diarize", dest="diarize", action="store_false")
    parser.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="optional pyannote hint; off by default because a speaker count "
        "is fixture metadata and a blind run should not receive it",
    )
    parser.add_argument("--max-speakers", type=int, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="use only already-cached models; never download",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(align=True, diarize=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.asr.whisperx",
        description="Local WhisperX + pyannote ASR route",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check",
        help="report device, token, package, and audio status (no model download)",
    )
    _add_model_options(check)
    check.add_argument("--audio", type=Path, default=config.MEETING_WAV_PATH)

    run = sub.add_parser("run", help="transcribe, align, diarize, and export")
    _add_model_options(run)
    run.add_argument("--audio", type=Path, default=config.MEETING_WAV_PATH)
    run.add_argument("--out-dir", type=Path, default=config.WHISPERX_OUTPUT_DIR)

    return parser


def _cuda_status() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def cmd_check(args: argparse.Namespace) -> int:
    print("Local ASR environment (WhisperX)")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {dependency_versions().get('platform', '?')}")
    print(f"  Host: {socket.gethostname()}")
    print(f"  CUDA available: {'yes' if _cuda_status() else 'no'}")

    try:
        device = resolve_device(args.device, cuda_available=_cuda_status)
    except LocalASRError as exc:
        print(f"\nDevice error: {exc}", file=sys.stderr)
        return 5

    compute = args.compute_type or default_compute_type(device)
    print(f"  Device requested: {args.device} -> {device}")
    print(f"  Compute type: {compute}")
    print(f"  ASR model: {args.model}")
    print(f"  Language: {args.language}")
    print(
        "  Alignment: "
        + ("off" if not args.align else (args.align_model or "WhisperX default"))
    )
    print(
        "  Diarization: "
        + ("off" if not args.diarize else args.diarization_model)
    )
    print(
        f"  HF token present: {'yes' if load_hf_token() else 'no'} (value never shown)"
    )

    versions = dependency_versions()
    print("  Versions: " + ", ".join(f"{k}={v}" for k, v in versions.items()))

    missing = [
        package
        for package in ("whisperx", "torch", "pyannote-audio")
        if versions.get(package) == "not-installed"
    ]
    if missing:
        print(
            "\nMissing packages: " + ", ".join(missing) + ". Install with "
            "`uv pip install --python .venv\\Scripts\\python.exe -r "
            "requirements-asr.txt`.",
            file=sys.stderr,
        )
        return 6

    try:
        load_whisperx()
        print("  WhisperX import: OK")
    except WhisperXDependencyError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 6

    audio = Path(args.audio)
    if audio.exists():
        print(f"  Meeting WAV: {audio} ({audio.stat().st_size:,} bytes)")
    else:
        print(f"  Meeting WAV: not found at {audio}")
        print(
            "    Generate it with `python -m src.tts run --yes` or import one "
            "with `python -m src.tts import-wav <file>`."
        )
    print(
        "\ncheck does not download models or contact Hugging Face. A live run "
        "downloads the ASR/alignment models once (and the gated diarization "
        "model when an HF token is present)."
    )
    return 0


def _print_progress(message: str) -> None:
    print(f"  {message}", flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    settings = RunSettings(
        audio_path=args.audio,
        out_dir=args.out_dir,
        model=args.model,
        language=args.language,
        device=args.device,
        compute_type=args.compute_type,
        batch_size=args.batch_size,
        align=args.align,
        diarize=args.diarize,
        align_model=args.align_model,
        diarization_model=args.diarization_model,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        cache_dir=args.cache_dir,
        local_files_only=args.local_only,
    )

    print("Local WhisperX run")
    print(f"  Audio: {args.audio}")
    print(f"  Output: {args.out_dir}")
    print(
        "  Upload: none. This route runs locally; only model downloads touch "
        "the network."
    )
    print()

    try:
        result = run_local_asr(settings, progress=_print_progress)
    except MissingHFTokenError as exc:
        print(f"\nMissing Hugging Face token:\n\n{exc}", file=sys.stderr)
        return 3
    except UnsupportedDeviceError as exc:
        print(f"\nDevice error: {exc}", file=sys.stderr)
        return 5
    except ModelDownloadError as exc:
        print(f"\nModel download/load failed: {exc}", file=sys.stderr)
        return 4
    except WhisperXDependencyError as exc:
        print(f"\nEnvironment error: {exc}", file=sys.stderr)
        return 6
    except (RunError, LocalASRError, AudioLoadError) as exc:
        print(f"\nLocal ASR failed: {exc}", file=sys.stderr)
        return 1

    manifest = result.manifest
    counts = manifest["counts"]
    timings = manifest["timing_seconds"]
    print(
        f"\nWrote {counts['segments']} segments / {counts['words']} words to "
        f"{result.out_dir}"
    )
    print(
        f"  Device: {manifest['asr']['device']} "
        f"({manifest['asr']['compute_type']}); model {manifest['asr']['model']}"
    )
    print(
        f"  Speaker labels: "
        + (", ".join(manifest["diarization"]["labels"]) or "none")
    )
    print(
        "  Timing: "
        + ", ".join(f"{key}={value:.2f}s" for key, value in timings.items())
    )
    print("  Files:")
    for name in ("manifest", "json", "txt", "srt", "vtt", "raw"):
        path = result.paths.get(name)
        if path:
            print(f"    {name:8} {path}")

    if args.diarize and not manifest["diarization"]["labels"]:
        print(
            "\nWarning: diarization returned no speaker labels. Check the "
            "pyannote model and token permissions.",
            file=sys.stderr,
        )
    print(
        "\nSpeaker labels are anonymous clusters (SPEAKER_00, ...). No "
        "participant name was supplied to the model; mapping is a separate step."
    )
    return 0


COMMANDS = {"check": cmd_check, "run": cmd_run}


def main(argv: list[str] | None = None) -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
