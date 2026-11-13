"""Turn planning, per-turn synthesis, and the segment manifest.

The manifest is the bridge between TTS and evaluation: it records exactly which
file belongs to which turn, how long it is, and which voice produced it. A later
assembly step turns that into both the meeting WAV and the time-aligned
reference timeline.
"""

from __future__ import annotations

import logging
import platform
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable, Iterable

from src import config
from src.schema import (
    MeetingMetadata,
    MeetingScript,
    SegmentManifest,
    SegmentRecord,
    SchemaError,
    Turn,
    load_json,
    write_json,
)
from src.tts.audio import AudioError, inspect_wav, sha256_file
from src.tts.voices import VoiceAssignment, voice_assignments

logger = logging.getLogger(__name__)


class SegmentError(RuntimeError):
    """Raised when a segment set is incomplete or inconsistent."""


@dataclass(frozen=True)
class SegmentPlan:
    turn: Turn
    voice: VoiceAssignment

    @property
    def index(self) -> int:
        return self.turn.index

    @property
    def speaker_id(self) -> str:
        return self.turn.speaker_id

    @property
    def text(self) -> str:
        return self.turn.text

    @property
    def section(self) -> str:
        return self.turn.section

    @property
    def filename(self) -> str:
        return segment_filename(self.index, self.speaker_id)


def segment_filename(index: int, speaker_id: str) -> str:
    """Deterministic filename shared by the API and manual workflows."""

    return f"turn_{index:03d}_{speaker_id}.wav"


def plan_segments(
    script: MeetingScript,
    metadata: MeetingMetadata,
    plan: dict[str, config.VoiceProfile] | None = None,
) -> list[SegmentPlan]:
    assignments = {
        assignment.speaker_id: assignment
        for assignment in voice_assignments(script, metadata, plan)
    }
    return [
        SegmentPlan(turn=turn, voice=assignments[turn.speaker_id])
        for turn in script.turns
    ]


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def environment_info() -> dict[str, str]:
    """Versions and platform recorded in every manifest."""

    packages = ["google-genai", "numpy", "soundfile"]
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": ", ".join(
            f"{name}={version}" for name, version in versions.items()
        ),
    }


def load_segment_manifest(path: Path | str) -> SegmentManifest:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise SegmentError(
            f"segment manifest not found: {manifest_path}. Run synthesis or "
            "import the manually generated segments first."
        )
    try:
        return SegmentManifest.from_dict(load_json(manifest_path))
    except (SchemaError, ValueError, KeyError, TypeError) as exc:
        raise SegmentError(
            f"segment manifest is unreadable: {manifest_path}: {exc}. "
            "Regenerate the segments, or pass --overwrite to ignore the file."
        ) from exc


def write_segment_manifest(manifest: SegmentManifest, path: Path | str) -> None:
    write_json(Path(path), manifest.to_dict())


def _record_is_current(record: SegmentRecord, segments_dir: Path) -> bool:
    path = segments_dir / record.file
    if not path.exists():
        return False
    try:
        return sha256_file(path) == record.sha256
    except OSError:
        return False


def _render_turn(
    plan: SegmentPlan,
    client: object,
    directory: Path,
    progress: Callable[[str], None] | None,
    resolved_model: str,
) -> SegmentRecord:
    """Synthesize one turn and write its WAV. Safe to run in a worker thread.

    Each turn owns its own file and its own ``.part`` temporary, so parallel
    workers never touch the same path. The manifest is written by the caller.
    """

    started = time.perf_counter()
    if progress:
        progress(
            f"turn {plan.index:03d}: synthesizing {plan.speaker_id} "
            f"with {plan.voice.voice_name}"
        )
    result = client.synthesize(plan.text, plan.voice)
    elapsed = time.perf_counter() - started

    target = directory / plan.filename
    temporary = target.with_suffix(".wav.part")
    temporary.write_bytes(result.audio_bytes)
    try:
        info = inspect_wav(temporary)
    except AudioError:
        temporary.unlink(missing_ok=True)
        raise
    if info.frames == 0:
        temporary.unlink(missing_ok=True)
        raise SegmentError(
            f"turn {plan.index}: the API returned an empty audio segment"
        )
    temporary.replace(target)

    return SegmentRecord(
        index=plan.index,
        speaker_id=plan.speaker_id,
        voice=plan.voice.voice_name,
        text=plan.text,
        file=plan.filename,
        sample_rate=info.sample_rate,
        channels=info.channels,
        sample_width_bytes=info.sample_width_bytes,
        duration_seconds=info.duration_seconds,
        sha256=sha256_file(target),
        model=getattr(result, "model", resolved_model),
        created_utc=utc_now(),
        synthesis_seconds=round(elapsed, 3),
    )


def synthesize_segments(
    plans: Iterable[SegmentPlan],
    segments_dir: Path | str,
    client: object,
    *,
    fixture_id: str,
    meeting_id: str,
    model: str | None = None,
    overwrite: bool = False,
    limit: int | None = None,
    concurrency: int = 1,
    progress: Callable[[str], None] | None = None,
) -> SegmentManifest:
    """Synthesize one WAV per turn and write the manifest after every success.

    Passing an object with a ``synthesize(text, voice)`` method keeps this
    function testable without the SDK or a network connection. Persisting after
    each turn means an interrupted run resumes instead of starting over.

    ``concurrency`` above 1 keeps several requests in flight, which cuts a
    39-turn run from minutes to tens of seconds. Order is never taken from
    completion order: records are sorted by turn index before every manifest
    write, so a parallel run produces the same manifest as a serial one.
    """

    plan_list = list(plans)
    if limit is not None:
        if limit <= 0:
            raise SegmentError("limit must be positive")
        plan_list = plan_list[:limit]
    if not plan_list:
        raise SegmentError("no turns to synthesize")
    if concurrency < 1:
        raise SegmentError("concurrency must be at least 1")

    directory = Path(segments_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"

    existing: dict[int, SegmentRecord] = {}
    if manifest_path.exists() and not overwrite:
        try:
            existing = load_segment_manifest(manifest_path).by_index()
        except (SegmentError, OSError) as exc:
            logger.warning("ignoring unreadable existing manifest: %s", exc)

    resolved_model = model or getattr(client, "model", None) or config.TTS_MODEL
    records: list[SegmentRecord] = []
    records_lock = threading.Lock()

    def persist() -> None:
        # Sorted by index so the result never depends on which call finished
        # first, and so a resumed run rewrites the same order.
        ordered = tuple(sorted(records, key=lambda record: record.index))
        write_segment_manifest(
            SegmentManifest(
                schema_version="1.0",
                fixture_id=fixture_id,
                meeting_id=meeting_id,
                source="gemini_api",
                model=resolved_model,
                generated_utc=utc_now(),
                segments=ordered,
                environment=environment_info(),
            ),
            manifest_path,
        )

    pending: list[SegmentPlan] = []
    for plan in plan_list:
        skip = (
            not overwrite
            and plan.index in existing
            and _record_is_current(existing[plan.index], directory)
        )
        if skip:
            record = existing[plan.index]
            logger.info("turn %03d: keeping existing %s", plan.index, record.file)
            if progress:
                progress(f"turn {plan.index:03d}: kept {record.file}")
            records.append(record)
            continue
        pending.append(plan)

    def accept(record: SegmentRecord) -> None:
        with records_lock:
            records.append(record)
            # Persist after every success so an interrupted run can resume.
            persist()

    if concurrency == 1:
        for plan in pending:
            accept(
                _render_turn(plan, client, directory, progress, resolved_model)
            )
    else:
        pool = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="tts-turn"
        )
        futures = [
            pool.submit(
                _render_turn, plan, client, directory, progress, resolved_model
            )
            for plan in pending
        ]
        try:
            for future in as_completed(futures):
                accept(future.result())
        except BaseException:
            # Stop handing out new work. Requests already in flight are short
            # and finish on their own; whatever succeeded is already on disk.
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)

    final = SegmentManifest(
        schema_version="1.0",
        fixture_id=fixture_id,
        meeting_id=meeting_id,
        source="gemini_api",
        model=resolved_model,
        generated_utc=utc_now(),
        segments=tuple(sorted(records, key=lambda record: record.index)),
        environment=environment_info(),
    )
    write_segment_manifest(final, manifest_path)
    return final


def ingest_manual_segments(
    plans: Iterable[SegmentPlan],
    source_dir: Path | str,
    segments_dir: Path | str,
    *,
    fixture_id: str,
    meeting_id: str,
    overwrite: bool = False,
) -> SegmentManifest:
    """Build a manifest from WAVs generated manually in Google AI Studio.

    The files must be named ``turn_001_ANN.wav`` and so on, matching
    :func:`segment_filename`. This is the no-Python, no-API-key fallback.
    """

    source = Path(source_dir)
    destination = Path(segments_dir)
    destination.mkdir(parents=True, exist_ok=True)
    plan_list = list(plans)
    if not plan_list:
        raise SegmentError("no turns to ingest")

    missing = [
        plan.filename for plan in plan_list if not (source / plan.filename).exists()
    ]
    if missing:
        raise SegmentError(
            f"manual segment files are missing from {source}: "
            f"{', '.join(missing)}. Name each file turn_<index>_<SPEAKER>.wav."
        )

    records: list[SegmentRecord] = []
    for plan in plan_list:
        origin = source / plan.filename
        target = destination / plan.filename
        if origin.resolve() != target.resolve():
            shutil.copyfile(origin, target)
        try:
            info = inspect_wav(target)
        except AudioError as exc:
            raise SegmentError(f"{plan.filename}: {exc}") from exc
        if info.format.upper() != "WAV":
            raise SegmentError(
                f"{plan.filename}: expected a WAV file, got {info.format}"
            )
        records.append(
            SegmentRecord(
                index=plan.index,
                speaker_id=plan.speaker_id,
                voice=plan.voice.voice_name,
                text=plan.text,
                file=plan.filename,
                sample_rate=info.sample_rate,
                channels=info.channels,
                sample_width_bytes=info.sample_width_bytes,
                duration_seconds=info.duration_seconds,
                sha256=sha256_file(target),
                model=None,
                created_utc=utc_now(),
                synthesis_seconds=None,
            )
        )

    expected = {plan.filename for plan in plan_list}
    extras = sorted(
        path.name for path in source.glob("turn_*.wav") if path.name not in expected
    )
    if extras:
        logger.warning("ignoring unexpected segment files: %s", ", ".join(extras))

    manifest = SegmentManifest(
        schema_version="1.0",
        fixture_id=fixture_id,
        meeting_id=meeting_id,
        source="manual_ai_studio",
        model=None,
        generated_utc=utc_now(),
        segments=tuple(records),
        environment=environment_info(),
    )
    write_segment_manifest(manifest, destination / "manifest.json")
    return manifest
