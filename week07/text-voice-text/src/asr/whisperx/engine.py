"""The only module that knows the WhisperX and pyannote APIs.

Everything else consumes ``EngineResult``. Imports are lazy so normalization and
export tests run without the multi-gigabyte ASR stack installed.

The meeting WAV is decoded with ``soundfile`` and passed to WhisperX as an
in-memory 16 kHz array. That deliberately avoids WhisperX's ``ffmpeg``
subprocess and pyannote's torchcodec decoder, so this lab needs neither.
"""

from __future__ import annotations

import importlib.metadata as metadata
import logging
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from src import config
from src.asr.tokens import require_hf_token

logger = logging.getLogger(__name__)


class LocalASRError(RuntimeError):
    """Base class for readable local-ASR failures."""


class UnsupportedDeviceError(LocalASRError):
    """Raised when the requested device cannot be used."""


class WhisperXDependencyError(LocalASRError):
    """Raised when the installed WhisperX stack is missing or incompatible."""


class ModelDownloadError(LocalASRError):
    """Raised when a model cannot be downloaded or loaded."""


COMPUTE_TYPES = (
    "int8",
    "int8_float32",
    "int8_float16",
    "int8_bfloat16",
    "float16",
    "float32",
    "bfloat16",
    "default",
)

TRACKED_PACKAGES = (
    "whisperx",
    "pyannote-audio",
    "torch",
    "torchaudio",
    "torchcodec",
    "faster-whisper",
    "ctranslate2",
    "transformers",
    "numpy",
    "soundfile",
)


@dataclass(frozen=True)
class EngineOptions:
    """Inputs that change model behavior. Never contains a token."""

    audio: np.ndarray
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
class EngineResult:
    raw: dict[str, Any]
    language: str
    model: str
    device: str
    compute_type: str
    align_model: str | None
    diarization_model: str | None
    speaker_labels: tuple[str, ...]
    timings: Mapping[str, float] = field(default_factory=dict)
    versions: Mapping[str, str] = field(default_factory=dict)


def dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    versions["python"] = sys.version.split()[0]
    versions["platform"] = platform.platform()
    return versions


def _cuda_available_default() -> bool:
    try:
        import torch
    except ImportError as exc:
        raise WhisperXDependencyError(
            "PyTorch is not installed. Install the local ASR route with "
            "`uv pip install --python .venv\\Scripts\\python.exe -r "
            "requirements-asr.txt`."
        ) from exc
    return bool(torch.cuda.is_available())


def resolve_device(
    requested: str,
    *,
    cuda_available: Callable[[], bool] | None = None,
) -> str:
    """Resolve ``auto`` to ``cuda`` or ``cpu``, and reject impossible choices."""

    choice = (requested or config.WHISPERX_DEVICE_AUTO).strip().lower()
    if choice not in config.WHISPERX_DEVICES:
        allowed = ", ".join(config.WHISPERX_DEVICES)
        raise UnsupportedDeviceError(
            f"unsupported device {requested!r}; choose one of: {allowed}"
        )
    if choice == "cpu":
        return "cpu"

    available = (
        cuda_available() if cuda_available is not None else _cuda_available_default()
    )
    if choice == "cuda":
        if not available:
            raise UnsupportedDeviceError(
                "CUDA was requested but PyTorch reports no usable GPU. Check "
                "`python -c \"import torch; print(torch.cuda.is_available())\"`. "
                "A CPU-only PyTorch wheel cannot use CUDA; install the CUDA "
                "build from https://pytorch.org/get-started/locally/ that "
                "matches your driver, or rerun with --device cpu."
            )
        return "cuda"
    return "cuda" if available else "cpu"


def default_compute_type(device: str) -> str:
    return (
        config.WHISPERX_CPU_COMPUTE_TYPE
        if device == "cpu"
        else config.WHISPERX_CUDA_COMPUTE_TYPE
    )


def load_whisperx() -> Any:
    try:
        import whisperx
    except ImportError as exc:
        raise WhisperXDependencyError(
            "WhisperX is not installed. Run `uv pip install --python "
            ".venv\\Scripts\\python.exe -r requirements-asr.txt` first."
        ) from exc
    except Exception as exc:  # a broken native dependency raises here
        raise WhisperXDependencyError(
            f"WhisperX is installed but failed to import: {exc}. Reinstall the "
            "versions recorded in requirements-asr.txt; do not mix a different "
            "PyTorch build with this WhisperX release."
        ) from exc
    return whisperx


def _gated_or_network_error(
    exc: Exception, *, what: str, diarization: bool
) -> LocalASRError:
    text = f"{exc}".lower()
    gated_hints = (
        "401",
        "403",
        "gated",
        "authorization",
        "authenticated",
        "access to model",
        "user agreement",
        "token",
    )
    network_hints = (
        "connection",
        "connect",
        "timed out",
        "timeout",
        "download",
        "offline",
        "network",
        "proxy",
        "ssl",
        "certificate",
        "name resolution",
        "temporary failure",
        "couldn't reach",
        "huggingface.co",
        "404",
    )
    if diarization and any(hint in text for hint in gated_hints):
        return ModelDownloadError(
            f"could not load the gated {what}: {exc}\n"
            "Accept the model conditions on its Hugging Face page and use a "
            "read token that belongs to that account. Put the token in "
            "HF_TOKEN (environment only); run --no-diarize to skip this step."
        )
    if any(hint in text for hint in network_hints):
        return ModelDownloadError(
            f"could not download or load {what}: {exc}. Check the network, "
            "proxy, disk space, and the Hugging Face cache, then rerun. Models "
            "are cached after the first successful download."
        )
    return LocalASRError(f"{what} failed: {exc}")


def _align_error(exc: Exception, language: str, model: str | None) -> LocalASRError:
    text = f"{exc}".lower()
    if "no default align-model" in text or "could not be found" in text:
        return WhisperXDependencyError(
            f"no usable alignment model for language {language!r} "
            f"(requested {model or 'the default'}). Pass --align-model with a "
            "wav2vec2 model from https://huggingface.co/models, or rerun with "
            "--no-align to skip word-level alignment."
        )
    return _gated_or_network_error(
        exc, what=f"alignment model {model or '(default)'}", diarization=False
    )


def collect_speaker_labels(raw: Mapping[str, Any]) -> tuple[str, ...]:
    labels: set[str] = set()
    for segment in raw.get("segments", []) or []:
        if not isinstance(segment, Mapping):
            continue
        speaker = segment.get("speaker")
        if speaker:
            labels.add(str(speaker))
        for word in segment.get("words", []) or []:
            if isinstance(word, Mapping) and word.get("speaker"):
                labels.add(str(word["speaker"]))
    return tuple(sorted(labels))


def _diarization_api(module: Any) -> tuple[Any, Any]:
    if hasattr(module, "DiarizationPipeline") and hasattr(
        module, "assign_word_speakers"
    ):
        return module.DiarizationPipeline, module.assign_word_speakers
    try:
        from whisperx.diarize import DiarizationPipeline, assign_word_speakers
    except ImportError as exc:
        raise WhisperXDependencyError(
            "WhisperX diarization support is not installed correctly; "
            "reinstall requirements-asr.txt."
        ) from exc
    return DiarizationPipeline, assign_word_speakers


def run_engine(
    options: EngineOptions,
    *,
    env: Mapping[str, str] | None = None,
    module: Any | None = None,
    cuda_available: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> EngineResult:
    """Run ASR, alignment, and optional diarization with clear failures."""

    if options.compute_type is not None and options.compute_type not in COMPUTE_TYPES:
        raise WhisperXDependencyError(
            f"unsupported compute type {options.compute_type!r}; choose one of: "
            + ", ".join(COMPUTE_TYPES)
        )
    if options.batch_size <= 0:
        raise LocalASRError("batch size must be positive")
    if (
        options.min_speakers is not None
        and options.max_speakers is not None
        and options.min_speakers > options.max_speakers
    ):
        raise LocalASRError("min speakers cannot exceed max speakers")

    device = resolve_device(options.device, cuda_available=cuda_available)
    compute_type = options.compute_type or default_compute_type(device)
    if device == "cpu" and compute_type in {
        "float16",
        "bfloat16",
        "int8_float16",
    }:
        raise WhisperXDependencyError(
            f"compute type {compute_type!r} needs CUDA; on CPU use int8 "
            "(the default) or float32."
        )
    token = require_hf_token(env) if options.diarize else None
    wx = module if module is not None else load_whisperx()

    timings: dict[str, float] = {}
    started = time.perf_counter()

    if progress:
        progress(
            f"loading WhisperX model {options.model!r} on {device} "
            f"({compute_type})"
        )
    step = time.perf_counter()
    try:
        model = wx.load_model(
            options.model,
            device=device,
            compute_type=compute_type,
            language=options.language,
            download_root=str(options.cache_dir) if options.cache_dir else None,
            local_files_only=options.local_files_only,
        )
    except Exception as exc:
        raise _gated_or_network_error(
            exc, what=f"ASR model {options.model!r}", diarization=False
        ) from exc
    timings["load_model"] = round(time.perf_counter() - step, 3)

    if progress:
        progress("transcribing (verbatim)")
    step = time.perf_counter()
    try:
        raw = dict(
            model.transcribe(
                options.audio,
                batch_size=options.batch_size,
                language=options.language,
                task="transcribe",
                print_progress=False,
                verbose=False,
            )
        )
    except Exception as exc:
        text = f"{exc}".lower()
        if "compute type" in text or "ctranslate2" in text or "cuda" in text:
            raise WhisperXDependencyError(
                f"the WhisperX stack rejected device {device!r} / compute type "
                f"{compute_type!r}: {exc}. See docs/whisperx_local_guide.md for "
                "the verified PyTorch/CUDA combination."
            ) from exc
        raise LocalASRError(f"transcription failed: {exc}") from exc
    timings["transcribe"] = round(time.perf_counter() - step, 3)

    detected_language = str(raw.get("language") or options.language)
    align_model_name: str | None = None
    if options.align and raw.get("segments"):
        if progress:
            progress(f"aligning words with the {detected_language} wav2vec2 model")
        step = time.perf_counter()
        try:
            align_model, align_metadata = wx.load_align_model(
                language_code=detected_language,
                device=device,
                model_name=options.align_model,
                model_dir=str(options.cache_dir) if options.cache_dir else None,
                model_cache_only=options.local_files_only,
            )
        except Exception as exc:
            raise _align_error(exc, detected_language, options.align_model) from exc
        align_model_name = (
            options.align_model
            or f"whisperx-default-wav2vec2-{detected_language}"
        )
        try:
            aligned = wx.align(
                raw.get("segments", []),
                align_model,
                align_metadata,
                options.audio,
                device,
                return_char_alignments=False,
            )
        except Exception as exc:
            raise LocalASRError(f"word alignment failed: {exc}") from exc
        aligned["language"] = detected_language
        raw = dict(aligned)
        timings["align"] = round(time.perf_counter() - step, 3)
    else:
        raw["language"] = detected_language

    diarization_model: str | None = None
    if options.diarize:
        diarization_model = options.diarization_model
        if progress:
            progress(
                f"diarizing with {diarization_model} (anonymous speaker labels)"
            )
        step = time.perf_counter()
        try:
            pipeline_class, assign_word_speakers = _diarization_api(wx)
            pipeline = pipeline_class(
                model_name=diarization_model,
                token=token,
                device=device,
                cache_dir=str(options.cache_dir) if options.cache_dir else None,
            )
            diarization = pipeline(
                options.audio,
                min_speakers=options.min_speakers,
                max_speakers=options.max_speakers,
            )
            raw = dict(
                assign_word_speakers(
                    diarization, raw, fill_nearest=True
                )
            )
        except LocalASRError:
            raise
        except Exception as exc:
            raise _gated_or_network_error(
                exc, what=f"diarization model {diarization_model}", diarization=True
            ) from exc
        timings["diarize"] = round(time.perf_counter() - step, 3)

    timings["total"] = round(time.perf_counter() - started, 3)
    return EngineResult(
        raw=raw,
        language=detected_language,
        model=options.model,
        device=device,
        compute_type=compute_type,
        align_model=align_model_name,
        diarization_model=diarization_model,
        speaker_labels=collect_speaker_labels(raw),
        timings=timings,
        versions=dependency_versions(),
    )
