"""Thin, testable wrapper around faster-whisper's ``WhisperModel``.

Nothing in this module knows about the CLI, the web server, or the summarizer. It
takes an audio path and returns a ``Transcription`` with plain Python objects,
which keeps both entry points small and makes the pipeline easy to reuse.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import config

# The CUDA DLL directories must be registered before CTranslate2 tries to load
# cublas/cudnn. prepare_cuda_dlls() is a no-op on CPU-only machines and macOS.
from .gpu import prepare_cuda_dlls

prepare_cuda_dlls()

from faster_whisper import WhisperModel


@dataclass(slots=True)
class Word:
    start: float
    end: float
    word: str
    probability: float | None = None

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "word": self.word,
            "probability": self.probability,
        }


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    no_speech_probability: float | None = None

    def to_dict(self) -> dict:
        data = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text.strip(),
        }
        if self.words:
            data["words"] = [word.to_dict() for word in self.words]
        return data


@dataclass(slots=True)
class Transcription:
    text: str
    segments: list[Segment]
    language: str
    language_probability: float
    duration: float
    elapsed: float
    model: str
    device: str
    compute_type: str
    task: str = "transcribe"

    @property
    def rtf(self) -> float:
        """Real-time factor: processing seconds per second of audio."""
        return self.elapsed / self.duration if self.duration else 0.0

    @property
    def speed(self) -> float:
        """How many seconds of audio are transcribed per second of compute."""
        return self.duration / self.elapsed if self.elapsed else 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "elapsed": self.elapsed,
            "rtf": self.rtf,
            "speed": self.speed,
            "model": self.model,
            "device": self.device,
            "compute_type": self.compute_type,
            "task": self.task,
            "segments": [segment.to_dict() for segment in self.segments],
        }


def cuda_device_count() -> int:
    """Number of CUDA devices CTranslate2 can see (0 on CPU-only machines)."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # noqa: BLE001 - any import/driver failure means "no GPU"
        return 0


def resolve_device(requested: str = config.DEFAULT_DEVICE) -> str:
    if requested and requested != "auto":
        return requested
    return "cuda" if cuda_device_count() > 0 else "cpu"


def resolve_compute_type(device: str, requested: str = config.DEFAULT_COMPUTE_TYPE) -> str:
    if requested and requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


class Transcriber:
    """Loads one Whisper model and transcribes files with it.

    Model construction is the expensive part (download + load), so the server
    caches one instance per (model, device, compute type) combination.
    """

    def __init__(
        self,
        model_name: str = config.DEFAULT_MODEL,
        device: str = config.DEFAULT_DEVICE,
        compute_type: str = config.DEFAULT_COMPUTE_TYPE,
        download_root: Path = config.MODELS_DIR,
        allow_cpu_fallback: bool = True,
    ) -> None:
        self.model_name = model_name
        self.requested_device = device
        self.device = resolve_device(device)
        self.compute_type = resolve_compute_type(self.device, compute_type)
        self._download_root = download_root
        self._allow_cpu_fallback = allow_cpu_fallback
        self.model = self._load()

    def _load(self) -> WhisperModel:
        prepare_cuda_dlls()
        self._download_root.mkdir(parents=True, exist_ok=True)
        try:
            return WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=str(self._download_root),
            )
        except (RuntimeError, ValueError) as exc:
            if self.device != "cuda" or not self._allow_cpu_fallback:
                raise
            warnings.warn(
                "CUDA could not be initialised, falling back to CPU/int8. "
                "On Windows install requirements-cuda.txt for GPU support. "
                f"Original error: {exc}",
                stacklevel=2,
            )
            self.device = "cpu"
            self.compute_type = "int8"
            return WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(self._download_root),
            )

    @property
    def label(self) -> str:
        return f"{self.model_name} on {self.device} ({self.compute_type})"

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = config.BEAM_SIZE,
        vad_filter: bool = config.VAD_FILTER,
        vad_min_silence_ms: int = config.VAD_MIN_SILENCE_MS,
        initial_prompt: str | None = None,
        word_timestamps: bool = config.WORD_TIMESTAMPS,
        on_segment: Callable[[Segment], None] | None = None,
    ) -> Transcription:
        """Transcribe ``audio_path`` and return the finished transcript.

        Segments are decoded lazily by faster-whisper; ``on_segment`` is called
        as each one is produced so a UI can show progress on long recordings.
        """
        if language in (None, "", "auto"):
            language = None
        if task not in ("transcribe", "translate"):
            raise ValueError("task must be 'transcribe' or 'translate'")

        vad_parameters = (
            {"min_silence_duration_ms": vad_min_silence_ms} if vad_filter else None
        )

        started = time.perf_counter()
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            language=language,
            task=task,
            beam_size=beam_size,
            vad_filter=vad_filter,
            vad_parameters=vad_parameters,
            initial_prompt=initial_prompt or None,
            word_timestamps=word_timestamps,
        )
        info_duration = float(getattr(info, "duration", 0.0) or 0.0)

        segments: list[Segment] = []
        for raw in segments_iter:
            segment = Segment(
                start=float(raw.start),
                end=float(raw.end),
                text=raw.text,
                words=[
                    Word(
                        start=float(word.start),
                        end=float(word.end),
                        word=word.word,
                        probability=getattr(word, "probability", None),
                    )
                    for word in (raw.words or [])
                ],
                no_speech_probability=getattr(raw, "no_speech_prob", None),
            )
            segments.append(segment)
            if on_segment is not None:
                on_segment(segment)

        elapsed = time.perf_counter() - started
        text = "".join(segment.text for segment in segments).strip()

        return Transcription(
            text=text,
            segments=segments,
            language=info.language,
            language_probability=float(info.language_probability),
            duration=info_duration,
            elapsed=elapsed,
            model=self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            task=task,
        )


def transcribe(
    audio_path: str | Path,
    *,
    model_name: str = config.DEFAULT_MODEL,
    device: str = config.DEFAULT_DEVICE,
    compute_type: str = config.DEFAULT_COMPUTE_TYPE,
    **options,
) -> Transcription:
    """One-shot convenience wrapper used by scripts and examples."""
    return Transcriber(model_name, device, compute_type).transcribe(audio_path, **options)
