"""Orchestrate one cloud ASR run: confirm, upload, transcribe, normalize, export.

The runner owns the filesystem and the run manifest. The client owns the vendor
API. Normalization and export never see an SDK type.
"""

from __future__ import annotations

import importlib.metadata
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src import config
from src.asr.common import base_versions, sha256_file
from src.asr.export import export_all
from src.asr.gemini.client import (
    GeminiTranscribeClient,
    MissingAPIKeyError,
    TranscribeResult,
    load_api_key,
)
from src.asr.gemini.parse import normalize_interaction
from src.asr.gemini.request import TranscribeOptions
from src.fixtures import load_fixture
from src.schema import NormalizedTranscript, write_json
from src.tts.segments import utc_now


class RunError(RuntimeError):
    """Raised when a cloud ASR run cannot start or finish."""


@dataclass(frozen=True)
class TranscribeSettings:
    audio_path: Path = config.MEETING_WAV_PATH
    out_dir: Path = config.GEMINI_OUTPUT_DIR
    model: str = config.TRANSCRIBE_MODEL
    language_codes: tuple[str, ...] = config.TRANSCRIBE_DEFAULT_LANGUAGE_CODES
    diarize: bool = config.TRANSCRIBE_DEFAULT_DIARIZE
    word_timestamps: bool = config.TRANSCRIBE_DEFAULT_WORD_TIMESTAMPS
    custom_vocabulary: tuple[str, ...] = ()
    store_remote: bool = config.TRANSCRIBE_DEFAULT_STORE_REMOTE
    timeout: float = config.TRANSCRIBE_REQUEST_TIMEOUT_SECONDS


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    transcript: NormalizedTranscript
    manifest: Mapping[str, Any]
    paths: Mapping[str, Path]
    response: TranscribeResult


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float
    sample_rate: int
    channels: int
    size_bytes: int


def probe_wav(path: Path | str) -> AudioProbe:
    """Read duration and format without loading the samples into memory."""

    import soundfile as sf

    target = Path(path)
    info = sf.info(str(target))
    frames = int(info.frames)
    rate = int(info.samplerate)
    duration = frames / float(rate) if rate else 0.0
    return AudioProbe(
        duration_seconds=duration,
        sample_rate=rate,
        channels=int(info.channels),
        size_bytes=target.stat().st_size,
    )


def check_duration_limits(
    duration_seconds: float,
    *,
    diarize: bool,
    word_timestamps: bool,
) -> None:
    """Refuse audio the documented limits would silently truncate."""

    if duration_seconds > config.TRANSCRIBE_UNARY_MAX_SECONDS:
        raise RunError(
            f"the audio is {duration_seconds / 60:.1f} minutes; the documented "
            f"unary limit is {config.TRANSCRIBE_UNARY_MAX_SECONDS // 60} "
            "minutes. Split the recording below the limit and reconcile the "
            "transcripts; do not let the service truncate it."
        )
    if (diarize or word_timestamps) and (
        duration_seconds > config.TRANSCRIBE_DIARIZATION_MAX_SECONDS
    ):
        raise RunError(
            f"the audio is {duration_seconds / 60:.1f} minutes; with "
            "diarization or word timestamps the documented limit is "
            f"{config.TRANSCRIBE_DIARIZATION_MAX_SECONDS // 60} minutes and "
            "audio past it is truncated while still reporting success. Split "
            "the recording (the archived long transcript path must chunk) and "
            "label each part."
        )


def dependency_versions() -> dict[str, str]:
    versions = base_versions()
    for package in ("google-genai",):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def run_cloud_asr(
    settings: TranscribeSettings,
    *,
    client: GeminiTranscribeClient | None = None,
    env: Mapping[str, str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunResult:
    """Run the cloud route and write every artifact into ``settings.out_dir``."""

    pipeline_started = time.perf_counter()

    audio_path = Path(settings.audio_path)
    if not audio_path.exists():
        raise RunError(
            f"meeting WAV not found: {audio_path}\n"
            "Generate it first with `python -m src.tts run --yes` (needs "
            "GEMINI_API_KEY) or `python -m src.tts ingest --from <dir>` / "
            "`python -m src.tts import-wav <file>`."
        )

    fixture = load_fixture()
    probe = probe_wav(audio_path)
    check_duration_limits(
        probe.duration_seconds,
        diarize=settings.diarize,
        word_timestamps=settings.word_timestamps,
    )
    audio_sha256 = sha256_file(audio_path)

    options = TranscribeOptions(
        model=settings.model,
        diarize=settings.diarize,
        word_timestamps=settings.word_timestamps,
        language_codes=settings.language_codes,
        custom_vocabulary=settings.custom_vocabulary,
        store_remote=settings.store_remote,
    )

    key_present = bool(load_api_key(env))
    active_client = client
    if active_client is None:
        if env is not None and not key_present:
            raise MissingAPIKeyError(
                f"no Gemini API key found in the provided environment. Set "
                f"{config.GEMINI_API_KEY_ENV}=... in .env or in the environment."
            )
        active_client = GeminiTranscribeClient(
            model=settings.model,
            timeout=settings.timeout,
        )

    response = active_client.transcribe(
        audio_path, options, progress=progress
    )

    out_dir = Path(settings.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "gemini_raw.json"

    language = (
        settings.language_codes[0] if settings.language_codes else "unknown"
    )
    timings = dict(response.timings)
    transcript = normalize_interaction(
        response.raw,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        model=settings.model,
        language=language,
        duration_seconds=probe.duration_seconds,
        raw_output_file=str(raw_path),
        manifest={
            "audio_file": str(audio_path),
            "audio_sha256": audio_sha256,
            "timing_seconds": dict(timings),
        },
    )

    export_started = time.perf_counter()
    paths = export_all(
        out_dir, transcript, response.raw, raw_filename="gemini_raw.json"
    )
    timings["export"] = round(time.perf_counter() - export_started, 3)
    timings["total_pipeline"] = round(time.perf_counter() - pipeline_started, 3)

    word_count = sum(len(segment.words) for segment in transcript.segments)
    speaker_labels = sorted(
        {
            segment.speaker_label
            for segment in transcript.segments
            if segment.speaker_label != config.UNKNOWN_SPEAKER
        }
    )

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_id": fixture.script.fixture_id,
        "meeting_id": fixture.script.meeting_id,
        "system": "gemini",
        "created_utc": utc_now(),
        "audio": {
            "file": str(audio_path),
            "sha256": audio_sha256,
            "size_bytes": probe.size_bytes,
            "source_sample_rate": probe.sample_rate,
            "channels": probe.channels,
            "duration_seconds": round(probe.duration_seconds, 6),
        },
        "asr": {
            "model": settings.model,
            "model_verified_on": config.TRANSCRIBE_MODEL_VERIFIED_ON,
            "api_version": config.TRANSCRIBE_API_VERSION,
            "language_codes": list(settings.language_codes),
            "verbatim": True,
            "diarize": settings.diarize,
            "word_timestamps": settings.word_timestamps,
            "custom_vocabulary": list(settings.custom_vocabulary),
        },
        "privacy": {
            "uploaded_file": response.uploaded_file,
            "uploaded_bytes": probe.size_bytes,
            "file_deleted": response.file_deleted,
            "store_remote": bool(settings.store_remote),
            "interaction_id": response.interaction_id,
            "api_key_present": key_present,
        },
        "limits": {
            "unary_max_seconds": config.TRANSCRIBE_UNARY_MAX_SECONDS,
            "diarization_max_seconds": config.TRANSCRIBE_DIARIZATION_MAX_SECONDS,
            "max_speakers": config.TRANSCRIBE_MAX_SPEAKERS,
        },
        "versions": dependency_versions(),
        "timing_seconds": timings,
        "counts": {
            "segments": len(transcript.segments),
            "words": word_count,
            "speaker_labels": len(speaker_labels),
        },
        "outputs": {name: str(path) for name, path in paths.items()},
        "notes": [
            "Only the meeting WAV was uploaded; no transcript, participant "
            "names, roles, or ground truth were sent.",
            "Speaker labels are anonymous diarization clusters (spk_1, spk_2); "
            "this stage never renames them to participants.",
            "Raw interaction output is preserved separately from the "
            "normalized transcript.",
            "Diarization supports up to eight speakers; attribution for three "
            "or more is documented as experimental.",
            "Word timestamps may reduce transcription accuracy; they are "
            "enabled so both routes expose the same fields.",
        ],
    }
    if settings.diarize:
        manifest["notes"].append(
            "Speaker labels: " + (", ".join(speaker_labels) or "none returned")
        )
    else:
        manifest["notes"].append(
            "Diarization was disabled; every segment keeps the UNKNOWN label."
        )
    if not response.file_deleted:
        manifest["notes"].append(
            "Warning: the uploaded file could not be deleted by this run. "
            "Delete it manually in the Files API; files expire automatically."
        )

    manifest_path = out_dir / "run_manifest.json"
    write_json(manifest_path, manifest)
    paths = dict(paths)
    paths["manifest"] = manifest_path

    return RunResult(
        out_dir=out_dir,
        transcript=transcript,
        manifest=manifest,
        paths=paths,
        response=response,
    )


def custom_vocabulary_from(values: Sequence[str] | None) -> tuple[str, ...]:
    """Parse ``--custom-vocabulary`` repeats into a tuple."""

    if not values:
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())
