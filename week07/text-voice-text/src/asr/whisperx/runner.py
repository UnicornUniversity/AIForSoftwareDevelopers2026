"""Orchestrate one local ASR run: decode, transcribe, align, diarize, export.

The runner owns the filesystem and the run manifest. The engine owns the vendor
API. Normalization and export never see a WhisperX type.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src import config
from src.asr.audio import LoadedAudio, load_audio_16k
from src.asr.common import sha256_file
from src.asr.tokens import load_hf_token
from src.asr.whisperx.engine import (
    EngineOptions,
    EngineResult,
    run_engine,
)
from src.asr.whisperx.export import export_all
from src.asr.whisperx.normalize import normalize_result
from src.fixtures import load_fixture
from src.schema import NormalizedTranscript, write_json
from src.tts.segments import utc_now


class RunError(RuntimeError):
    """Raised when a local ASR run cannot start or finish."""


@dataclass(frozen=True)
class RunSettings:
    audio_path: Path = config.MEETING_WAV_PATH
    out_dir: Path = config.WHISPERX_OUTPUT_DIR
    model: str = config.WHISPERX_MODEL
    language: str = config.WHISPERX_LANGUAGE
    device: str = config.WHISPERX_DEVICE_AUTO
    compute_type: str | None = None
    batch_size: int = config.WHISPERX_BATCH_SIZE
    align: bool = True
    diarize: bool = True
    align_model: str | None = config.WHISPERX_ALIGN_MODEL
    diarization_model: str = config.WHISPERX_DIARIZATION_MODEL
    min_speakers: int | None = None
    max_speakers: int | None = None
    cache_dir: Path | None = None
    local_files_only: bool = False


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    transcript: NormalizedTranscript
    manifest: Mapping[str, Any]
    paths: Mapping[str, Path]
    engine: EngineResult


def run_local_asr(
    settings: RunSettings,
    *,
    env: Mapping[str, str] | None = None,
    module: Any | None = None,
    cuda_available: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> RunResult:
    """Run the local route and write every artifact into ``settings.out_dir``."""

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
    if progress:
        progress(f"decoding {audio_path}")
    decode_started = time.perf_counter()
    audio: LoadedAudio = load_audio_16k(audio_path)
    decode_seconds = round(time.perf_counter() - decode_started, 3)
    audio_sha256 = sha256_file(audio_path)

    options = EngineOptions(
        audio=audio.samples,
        model=settings.model,
        language=settings.language,
        device=settings.device,
        compute_type=settings.compute_type,
        batch_size=settings.batch_size,
        align=settings.align,
        diarize=settings.diarize,
        align_model=settings.align_model,
        diarization_model=settings.diarization_model,
        min_speakers=settings.min_speakers,
        max_speakers=settings.max_speakers,
        cache_dir=settings.cache_dir,
        local_files_only=settings.local_files_only,
    )
    engine_result = run_engine(
        options,
        env=env,
        module=module,
        cuda_available=cuda_available,
        progress=progress,
    )

    out_dir = Path(settings.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "whisperx_raw.json"

    timings = dict(engine_result.timings)
    timings["audio_decode"] = decode_seconds

    transcript = normalize_result(
        engine_result.raw,
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        model=engine_result.model,
        language=engine_result.language,
        raw_output_file=str(raw_path),
        manifest={
            "audio_file": str(audio_path),
            "audio_sha256": audio_sha256,
            "device": engine_result.device,
            "compute_type": engine_result.compute_type,
            "align_model": engine_result.align_model,
            "diarization_model": engine_result.diarization_model,
            "timing_seconds": dict(timings),
        },
    )

    export_started = time.perf_counter()
    paths = export_all(out_dir, transcript, engine_result.raw)
    timings["export"] = round(time.perf_counter() - export_started, 3)
    timings["total_pipeline"] = round(time.perf_counter() - pipeline_started, 3)

    word_count = sum(len(segment.words) for segment in transcript.segments)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "fixture_id": fixture.script.fixture_id,
        "meeting_id": fixture.script.meeting_id,
        "system": "whisperx",
        "created_utc": utc_now(),
        "audio": {
            "file": str(audio_path),
            "sha256": audio_sha256,
            "source_sample_rate": audio.source_rate,
            "channels": audio.channels,
            "duration_seconds": round(audio.duration_seconds, 6),
            "model_sample_rate": audio.sample_rate,
        },
        "asr": {
            "model": engine_result.model,
            "language": engine_result.language,
            "device": engine_result.device,
            "compute_type": engine_result.compute_type,
            "batch_size": settings.batch_size,
            "align": settings.align,
            "align_model": engine_result.align_model,
        },
        "diarization": {
            "enabled": settings.diarize,
            "model": engine_result.diarization_model,
            "hf_token_present": bool(load_hf_token(env)),
            "min_speakers": settings.min_speakers,
            "max_speakers": settings.max_speakers,
            "labels": list(engine_result.speaker_labels),
        },
        "versions": dict(engine_result.versions),
        "timing_seconds": timings,
        "counts": {
            "segments": len(transcript.segments),
            "words": word_count,
            "speaker_labels": len(engine_result.speaker_labels),
        },
        "outputs": {name: str(path) for name, path in paths.items()},
        "notes": [
            "The meeting WAV was decoded in memory and was not modified.",
            "Only audio was given to WhisperX and pyannote; no transcript, "
            "participant names, roles, or ground truth were provided.",
            "Speaker labels are anonymous diarization clusters; this stage "
            "never renames them to participants.",
            "Raw WhisperX output is preserved separately from the normalized "
            "transcript.",
        ],
    }
    if not settings.diarize:
        manifest["notes"].append(
            "Diarization was disabled; every segment keeps the UNKNOWN label."
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
        engine=engine_result,
    )
