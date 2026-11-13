"""Decode the meeting WAV into the waveform WhisperX expects.

WhisperX's own ``load_audio`` shells out to ``ffmpeg``. This lab deliberately
avoids that dependency: the meeting is a single mono PCM WAV, so ``soundfile``
can decode it directly and NumPy can resample it to 16 kHz. The file on disk is
never modified; both ASR routes still receive the same unchanged WAV.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from src import config


class AudioLoadError(RuntimeError):
    """Raised when the meeting audio cannot be decoded for ASR."""


@dataclass(frozen=True)
class LoadedAudio:
    """A mono float32 waveform ready for WhisperX and pyannote."""

    samples: np.ndarray
    sample_rate: int
    source_rate: int
    channels: int
    duration_seconds: float


def resample_linear(
    samples: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    """Resample one channel with linear interpolation.

    Adequate for the clean synthetic fixture and dependency-free. A production
    recording pipeline would use a polyphase or band-limited resampler.
    """

    if source_rate <= 0 or target_rate <= 0:
        raise AudioLoadError("sample rates must be positive")
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    if data.size == 0:
        raise AudioLoadError("cannot resample an empty waveform")
    if source_rate == target_rate:
        return data
    count = int(round(data.size * target_rate / source_rate))
    if count <= 0:
        raise AudioLoadError("resampling produced zero frames")
    positions = np.arange(count, dtype=np.float64) * (source_rate / target_rate)
    return np.interp(positions, np.arange(data.size, dtype=np.float64), data).astype(
        np.float32
    )


def load_audio_16k(
    path: Path | str, target_rate: int = config.WHISPERX_SAMPLE_RATE
) -> LoadedAudio:
    """Read a WAV file, down-mix to mono, and resample to ``target_rate``."""

    audio_path = Path(path)
    if not audio_path.exists():
        raise AudioLoadError(f"audio file not found: {audio_path}")
    if not audio_path.is_file():
        raise AudioLoadError(f"not a file: {audio_path}")

    try:
        frames, source_rate = sf.read(
            str(audio_path), dtype="float32", always_2d=True
        )
    except Exception as exc:
        raise AudioLoadError(
            f"cannot read {audio_path}: {exc}. WhisperX stage expects a WAV "
            "file; convert other formats outside this lab."
        ) from exc

    if frames.size == 0:
        raise AudioLoadError(f"{audio_path}: the WAV contains no audio frames")

    channels = int(frames.shape[1])
    mono = frames.mean(axis=1, dtype=np.float32)
    source_duration = mono.size / float(source_rate)
    if source_rate != target_rate:
        mono = resample_linear(mono, source_rate, target_rate)
    mono = np.ascontiguousarray(mono, dtype=np.float32)

    return LoadedAudio(
        samples=mono,
        sample_rate=target_rate,
        source_rate=int(source_rate),
        channels=channels,
        duration_seconds=float(source_duration),
    )
