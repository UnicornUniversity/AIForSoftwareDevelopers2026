"""Command-line workflow for the TTS stage.

Run from the project root:

    python -m src.tts plan
    python -m src.tts synthesize --yes
    python -m src.tts assemble
    python -m src.tts run --yes
    python -m src.tts ingest --from manual_segments
    python -m src.tts import-wav path\\to\\meeting.wav
    python -m src.tts status
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src import config
from src.fixtures import load_fixture
from src.schema import SchemaError
from src.tts.assemble import assemble_meeting, describe_segment_set, wav_summary
from src.tts.gemini_tts import (
    GeminiTTSClient,
    MissingAPIKeyError,
    TTSError,
    cloud_call_notice,
    load_environment,
)
from src.tts.importer import WavImportError, import_meeting_wav
from src.tts.segments import (
    SegmentError,
    ingest_manual_segments,
    plan_segments,
    synthesize_segments,
)

logger = logging.getLogger("src.tts")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=config.FIXTURE_DIR,
        help="directory containing meeting_script.json and meeting_metadata.json",
    )
    parser.add_argument(
        "--segments-dir",
        type=Path,
        default=config.SEGMENTS_DIR,
        help="directory for per-turn WAV files and manifest.json",
    )


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audio-out",
        type=Path,
        default=config.MEETING_WAV_PATH,
        help="assembled meeting WAV path",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=config.MEETING_MANIFEST_PATH,
        help="assembled meeting manifest path",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.tts",
        description="Meeting Voice AI Lab - Text-to-Speech stage",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show per-turn progress"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="show the voice and segment plan (offline)")
    _add_common(plan)

    synth = sub.add_parser("synthesize", help="call Gemini TTS per turn")
    _add_common(synth)
    synth.add_argument("--model", default=config.TTS_MODEL)
    synth.add_argument("--limit", type=int, default=None, help="first N turns only")
    synth.add_argument(
        "--concurrency",
        type=int,
        default=config.TTS_CONCURRENCY,
        help="turns in flight at once (1 = strict serial; order is preserved)",
    )
    synth.add_argument(
        "--overwrite", action="store_true", help="regenerate existing segments"
    )
    synth.add_argument(
        "--yes",
        action="store_true",
        help="confirm the cloud call without an interactive prompt",
    )

    assemble = sub.add_parser("assemble", help="concatenate segments into one WAV")
    _add_common(assemble)
    _add_output(assemble)
    assemble.add_argument("--sample-rate", type=int, default=config.MEETING_SAMPLE_RATE)
    assemble.add_argument("--turn-pause-ms", type=int, default=config.TURN_PAUSE_MS)
    assemble.add_argument(
        "--section-pause-ms", type=int, default=config.SECTION_PAUSE_MS
    )

    run = sub.add_parser("run", help="synthesize then assemble")
    _add_common(run)
    _add_output(run)
    run.add_argument("--model", default=config.TTS_MODEL)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--concurrency", type=int, default=config.TTS_CONCURRENCY)
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--yes", action="store_true")
    run.add_argument("--sample-rate", type=int, default=config.MEETING_SAMPLE_RATE)
    run.add_argument("--turn-pause-ms", type=int, default=config.TURN_PAUSE_MS)
    run.add_argument("--section-pause-ms", type=int, default=config.SECTION_PAUSE_MS)

    ingest = sub.add_parser(
        "ingest", help="manifest WAVs generated manually in Google AI Studio"
    )
    _add_common(ingest)
    ingest.add_argument(
        "--from",
        dest="source_dir",
        type=Path,
        required=True,
        help="directory containing turn_001_ANN.wav, ...",
    )
    ingest.add_argument("--overwrite", action="store_true")

    import_wav = sub.add_parser(
        "import-wav", help="import an externally generated meeting WAV unchanged"
    )
    import_wav.add_argument("source", type=Path)
    import_wav.add_argument(
        "--audio-out", type=Path, default=config.MEETING_WAV_PATH
    )
    import_wav.add_argument(
        "--manifest-out", type=Path, default=config.MEETING_MANIFEST_PATH
    )
    import_wav.add_argument("--force", action="store_true")

    status = sub.add_parser("status", help="show what has been generated")
    _add_common(status)
    _add_output(status)

    return parser


def _fmt_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:05.2f}" if minutes else f"{seconds:.2f}s"


def cmd_plan(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture_dir)
    plans = plan_segments(fixture.script, fixture.metadata)

    print(f"Fixture: {fixture.script.title} ({fixture.script.fixture_id})")
    print(f"Project: {fixture.metadata.project.get('name', '?')} - release "
          f"{fixture.metadata.project.get('release', '?')}")
    print(f"Turns: {len(plans)}   Voice per participant: one stable prebuilt voice")
    print()
    print("Voice plan")
    print("  ID    Participant     Gender  Voice    Style")
    print("  ----  --------------  ------  -------  --------------------------------")
    seen: set[str] = set()
    for plan in plans:
        if plan.speaker_id in seen:
            continue
        seen.add(plan.speaker_id)
        voice = plan.voice
        print(
            f"  {voice.speaker_id:4}  {voice.full_name:14}  "
            f"{voice.gender:6}  {voice.voice_name:7}  {voice.style}"
        )
    print()
    print("Turn plan")
    print("  #    Speaker  Voice    Words  File")
    for plan in plans:
        print(
            f"  {plan.index:03d}  {plan.speaker_id:7}  {plan.voice.voice_name:7}  "
            f"{len(plan.text.split()):5}  {plan.filename}"
        )
    print()
    print(
        "Note: no three-speaker request is made. Each turn is synthesized "
        "separately, then concatenated with pauses."
    )
    print(
        f"Pauses: {config.TURN_PAUSE_MS} ms between turns, "
        f"{config.SECTION_PAUSE_MS} ms at section boundaries."
    )
    return 0


def _confirm_cloud_call(turn_count: int, model: str, assume_yes: bool) -> bool:
    for line in cloud_call_notice(model, turn_count):
        print(line)
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            "\nRefusing to call the cloud API without confirmation. "
            "Re-run with --yes after reading the notice.",
            file=sys.stderr,
        )
        return False
    answer = input("\nType 'yes' to continue: ").strip().lower()
    return answer in {"yes", "y"}


def _synthesize(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture_dir)
    plans = plan_segments(fixture.script, fixture.metadata)
    turn_count = args.limit if args.limit is not None else len(plans)

    if not _confirm_cloud_call(turn_count, args.model, args.yes):
        return 2

    try:
        client = GeminiTTSClient(model=args.model)
    except MissingAPIKeyError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 3

    def progress(message: str) -> None:
        if args.verbose:
            print(f"  {message}")

    try:
        manifest = synthesize_segments(
            plans,
            args.segments_dir,
            client,
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
            model=args.model,
            overwrite=args.overwrite,
            limit=args.limit,
            concurrency=args.concurrency,
            progress=progress,
        )
    except (TTSError, SegmentError) as exc:
        print(f"\nSynthesis failed: {exc}", file=sys.stderr)
        return 4

    total = sum(segment.duration_seconds for segment in manifest.segments)
    print(
        f"\nWrote {len(manifest.segments)} segments to {args.segments_dir} "
        f"({_fmt_seconds(total)} of speech)."
    )
    if args.limit is not None and args.limit < len(plans):
        print("Partial run: assemble will refuse until every turn exists.")
    return 0


def _assemble(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture_dir)
    try:
        manifest = assemble_meeting(
            fixture.script,
            args.segments_dir,
            args.audio_out,
            output_manifest=args.manifest_out,
            sample_rate=args.sample_rate,
            turn_pause_ms=args.turn_pause_ms,
            section_pause_ms=args.section_pause_ms,
        )
    except (SegmentError, SchemaError) as exc:
        print(f"\nAssembly failed: {exc}", file=sys.stderr)
        return 4
    print(
        f"Wrote {args.audio_out} ({_fmt_seconds(manifest.duration_seconds)}, "
        f"{manifest.sample_rate} Hz, {manifest.channels} ch)."
    )
    print(f"Timeline manifest: {args.manifest_out}")
    print(
        "The reference timeline comes from segment durations plus configured "
        "pauses; it never reaches an ASR system."
    )
    return 0


def cmd_synthesize(args: argparse.Namespace) -> int:
    return _synthesize(args)


def cmd_assemble(args: argparse.Namespace) -> int:
    return _assemble(args)


def cmd_run(args: argparse.Namespace) -> int:
    code = _synthesize(args)
    if code != 0:
        return code
    fixture = load_fixture(args.fixture_dir)
    if args.limit is not None and args.limit < len(fixture.script.turns):
        print(
            "\nPartial run requested; skipping assembly. Remove --limit to "
            "build the full meeting WAV."
        )
        return 0
    return _assemble(args)


def cmd_ingest(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture_dir)
    plans = plan_segments(fixture.script, fixture.metadata)
    try:
        manifest = ingest_manual_segments(
            plans,
            args.source_dir,
            args.segments_dir,
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
            overwrite=args.overwrite,
        )
    except SegmentError as exc:
        print(f"\nIngest failed: {exc}", file=sys.stderr)
        return 4
    print(
        f"Recorded {len(manifest.segments)} manually generated segments in "
        f"{args.segments_dir / 'manifest.json'}."
    )
    print("Next: python -m src.tts assemble")
    return 0


def cmd_import_wav(args: argparse.Namespace) -> int:
    fixture = load_fixture()
    try:
        manifest = import_meeting_wav(
            args.source,
            args.audio_out,
            fixture_id=fixture.script.fixture_id,
            meeting_id=fixture.script.meeting_id,
            manifest_path=args.manifest_out,
            force=args.force,
        )
    except WavImportError as exc:
        print(f"\nImport failed: {exc}", file=sys.stderr)
        return 4
    print(
        f"Imported {args.audio_out} unchanged "
        f"({_fmt_seconds(manifest.duration_seconds)}, "
        f"{manifest.sample_rate} Hz, {manifest.channels} ch)."
    )
    print(
        "No timeline is available for an imported meeting; DER must be "
        "reported as unavailable."
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture_dir)
    print(f"Fixture: {fixture.script.fixture_id} - {fixture.script.title}")
    print(f"Turns: {len(fixture.script.turns)}   "
          f"Participants: {', '.join(fixture.script.participant_ids)}")
    print()
    info = describe_segment_set(args.segments_dir)
    print(f"Segments: {info}")
    if args.audio_out.exists():
        print(f"Meeting WAV: {wav_summary(args.audio_out)}")
    else:
        print(f"Meeting WAV: not found at {args.audio_out}")
    print(f"API key present: {'yes' if _key_present() else 'no'} (never printed)")
    return 0


def _key_present() -> bool:
    import os

    return bool(
        os.environ.get(config.GEMINI_API_KEY_ENV)
        or os.environ.get(config.GOOGLE_API_KEY_ENV)
    )


COMMANDS = {
    "plan": cmd_plan,
    "synthesize": cmd_synthesize,
    "assemble": cmd_assemble,
    "run": cmd_run,
    "ingest": cmd_ingest,
    "import-wav": cmd_import_wav,
    "status": cmd_status,
}


def main(argv: list[str] | None = None) -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return COMMANDS[args.command](args)
    except (FileNotFoundError, SchemaError) as exc:
        print(f"\nFixture error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
