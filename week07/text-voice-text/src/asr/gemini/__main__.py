"""Command-line entry point for the Gemini cloud transcription route.

Run from the project root:

    python -m src.asr.gemini check
    python -m src.asr.gemini run --yes
    python -m src.asr.gemini run --no-diarize --no-timestamps
"""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
import sys
from pathlib import Path

from src import config
from src.asr.gemini.client import (
    APIKeyRejectedError,
    GeminiTranscribeClient,
    MissingAPIKeyError,
    ModelAccessError,
    QuotaError,
    TranscribeAPIError,
    TranscribeError,
    UploadError,
    cloud_call_notice,
    load_api_key,
    load_environment,
)
from src.asr.gemini.parse import ParseError
from src.asr.gemini.request import TranscribeRequestError
from src.asr.gemini.runner import (
    RunError,
    TranscribeSettings,
    custom_vocabulary_from,
    dependency_versions,
    probe_wav,
    run_cloud_asr,
)

logger = logging.getLogger("src.asr.gemini")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.asr.gemini",
        description="Gemini cloud transcription route (gemini-3.5-transcribe)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check",
        help="report key, SDK, model, and audio status without uploading anything",
    )
    check.add_argument("--audio", type=Path, default=config.MEETING_WAV_PATH)
    check.add_argument("--verbose", action="store_true")

    run = sub.add_parser(
        "run", help="upload the meeting WAV, transcribe it, and export"
    )
    run.add_argument("--audio", type=Path, default=config.MEETING_WAV_PATH)
    run.add_argument("--out-dir", type=Path, default=config.GEMINI_OUTPUT_DIR)
    run.add_argument("--model", default=config.TRANSCRIBE_MODEL)
    run.add_argument(
        "--language",
        action="append",
        default=None,
        help="BCP-47 language hint, repeatable (default: en-US)",
    )
    run.add_argument(
        "--auto-language",
        action="store_true",
        help="omit language hints and let the model detect the language",
    )
    run.add_argument("--no-diarize", dest="diarize", action="store_false")
    run.add_argument("--no-timestamps", dest="timestamps", action="store_false")
    run.add_argument(
        "--custom-vocabulary",
        action="append",
        default=None,
        metavar="TERM",
        help="bias terms; cannot be combined with diarization or timestamps "
        "(documented limit), so this is a separate labelled experiment",
    )
    run.add_argument(
        "--store",
        action="store_true",
        help="ask the API to retain the interaction (default: do not store)",
    )
    run.add_argument(
        "--timeout",
        type=float,
        default=config.TRANSCRIBE_REQUEST_TIMEOUT_SECONDS,
    )
    run.add_argument(
        "--yes",
        action="store_true",
        help="confirm the upload after reading the printed notice",
    )
    run.add_argument("--verbose", action="store_true")
    run.set_defaults(diarize=True, timestamps=True)

    return parser


def _sdk_version() -> str:
    try:
        return importlib.metadata.version("google-genai")
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def cmd_check(args: argparse.Namespace) -> int:
    print("Gemini transcription environment")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  google-genai: {_sdk_version()}")
    print(f"  Model: {config.TRANSCRIBE_MODEL} "
          f"(verified {config.TRANSCRIBE_MODEL_VERIFIED_ON})")
    print(f"  API version: {config.TRANSCRIBE_API_VERSION}")
    print(
        f"  API key present: "
        f"{'yes' if load_api_key() else 'no'} (value never shown)"
    )
    print("  Mode: verbatim; diarization and word timestamps are requested by "
          "default")

    audio = Path(args.audio)
    print(f"  Meeting WAV: {audio}")
    if not audio.exists():
        print(
            "    not found. Generate it with `python -m src.tts run --yes` or "
            "import one with `python -m src.tts import-wav <file>`."
        )
    else:
        try:
            probe = probe_wav(audio)
        except Exception as exc:
            print(f"    cannot read the WAV: {exc}", file=sys.stderr)
            return 1
        print(
            f"    {probe.size_bytes:,} bytes, "
            f"{probe.duration_seconds / 60:.1f} min, "
            f"{probe.sample_rate} Hz, {probe.channels} channel(s)"
        )
        limit = config.TRANSCRIBE_DIARIZATION_MAX_SECONDS
        if probe.duration_seconds > limit:
            print(
                f"    warning: over the documented {limit // 60}-minute limit "
                "for diarization/word timestamps; run will refuse it."
            )
    print(
        "\ncheck does not upload audio and does not call the API. Model access, "
        f"quota, and pricing: {config.TRANSCRIBE_DOCS_URL} and {config.USAGE_URL}."
    )
    return 0


def _confirm(notice: list[str], assume_yes: bool) -> bool:
    print("\n".join(notice))
    if assume_yes:
        print("\nProceeding (--yes).")
        return True
    if not sys.stdin.isatty():
        print(
            "\nRefusing to upload without confirmation. Re-run with --yes "
            "after reading the notice.",
            file=sys.stderr,
        )
        return False
    answer = input("\nType 'yes' to upload and transcribe: ").strip().lower()
    return answer in {"yes", "y"}


def cmd_run(args: argparse.Namespace) -> int:
    if args.auto_language:
        language_codes: tuple[str, ...] = ()
    elif args.language:
        language_codes = tuple(args.language)
    else:
        language_codes = config.TRANSCRIBE_DEFAULT_LANGUAGE_CODES

    settings = TranscribeSettings(
        audio_path=args.audio,
        out_dir=args.out_dir,
        model=args.model,
        language_codes=language_codes,
        diarize=args.diarize,
        word_timestamps=args.timestamps,
        custom_vocabulary=custom_vocabulary_from(args.custom_vocabulary),
        store_remote=args.store,
        timeout=args.timeout,
    )

    audio = Path(args.audio)
    if not audio.exists():
        print(
            f"meeting WAV not found: {audio}\n"
            "Generate it first with `python -m src.tts run --yes` or "
            "`python -m src.tts import-wav <file>`.",
            file=sys.stderr,
        )
        return 1

    try:
        probe = probe_wav(audio)
    except Exception as exc:
        print(f"cannot read {audio}: {exc}", file=sys.stderr)
        return 1

    notice = cloud_call_notice(
        audio_path=audio,
        size_bytes=probe.size_bytes,
        duration_seconds=probe.duration_seconds,
        options=settings_to_options(settings),
    )
    if not _confirm(notice, args.yes):
        return 1

    print()
    try:
        result = run_cloud_asr(
            settings, progress=lambda message: print(f"  {message}", flush=True)
        )
    except MissingAPIKeyError as exc:
        print(f"\nMissing Gemini API key:\n\n{exc}", file=sys.stderr)
        return 3
    except APIKeyRejectedError as exc:
        print(f"\nAuthentication failed:\n\n{exc}", file=sys.stderr)
        return 3
    except ModelAccessError as exc:
        print(f"\nModel access error:\n\n{exc}", file=sys.stderr)
        return 5
    except QuotaError as exc:
        print(f"\nQuota or rate limit:\n\n{exc}", file=sys.stderr)
        return 7
    except UploadError as exc:
        print(f"\nUpload failed:\n\n{exc}", file=sys.stderr)
        return 4
    except TranscribeRequestError as exc:
        print(f"\nInvalid transcription options:\n\n{exc}", file=sys.stderr)
        return 1
    except (TranscribeAPIError, TranscribeError, ParseError, RunError) as exc:
        print(f"\nCloud transcription failed:\n\n{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # SDK import problems and unexpected failures
        print(f"\nCloud transcription failed: {exc}", file=sys.stderr)
        print(
            "If the SDK is missing, install it with "
            "`uv pip install --python .venv\\Scripts\\python.exe -r "
            "requirements.txt`.",
            file=sys.stderr,
        )
        return 6

    manifest = result.manifest
    counts = manifest["counts"]
    timings = manifest["timing_seconds"]
    print(
        f"\nWrote {counts['segments']} segments / {counts['words']} words to "
        f"{result.out_dir}"
    )
    print(
        f"  Model: {manifest['asr']['model']} "
        f"({manifest['asr']['api_version']}); "
        f"file deleted: {'yes' if manifest['privacy']['file_deleted'] else 'no'}"
    )
    print(
        f"  Timing: "
        + ", ".join(f"{key}={value:.2f}s" for key, value in timings.items())
    )
    print("  Files:")
    for name in ("manifest", "json", "txt", "srt", "vtt", "raw"):
        path = result.paths.get(name)
        if path:
            print(f"    {name:8} {path}")

    if not manifest["privacy"]["file_deleted"]:
        print(
            "\nWarning: the uploaded file was not deleted. Remove it in the "
            "Files API; it also expires automatically.",
            file=sys.stderr,
        )
    print(
        "\nSpeaker labels are anonymous clusters (spk_1, spk_2, ...). No "
        "participant name was supplied to the model; mapping is a separate step."
    )
    return 0


def settings_to_options(settings: TranscribeSettings):
    from src.asr.gemini.request import TranscribeOptions

    return TranscribeOptions(
        model=settings.model,
        diarize=settings.diarize,
        word_timestamps=settings.word_timestamps,
        language_codes=settings.language_codes,
        custom_vocabulary=settings.custom_vocabulary,
        store_remote=settings.store_remote,
    )


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
