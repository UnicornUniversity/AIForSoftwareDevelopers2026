"""Audio primitives that do not need FFmpeg.

Gemini TTS returns 24 kHz, mono, 16-bit PCM WAV. ``soundfile`` (libsndfile) can
read and write that without a system FFmpeg install, which matters because this
course's Windows environment does not put ``ffmpeg`` on PATH.

All samples are handled as ``int16`` arrays shaped ``(frames, channels)``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from src import config

_INT16_MIN = -32768
_INT16_MAX = 32767


class AudioError(RuntimeError):
    """Raised when an audio file cannot be read or does not match the target."""


@dataclass(frozen=True)
class AudioInfo:
    path: Path
    sample_rate: int
    channels: int
    frames: int
    sample_width_bytes: int
    duration_seconds: float
    format: str
    subtype: str


def read_wav(path: Path | str) -> tuple[np.ndarray, AudioInfo]:
    """Read a WAV file as int16 samples shaped ``(frames, channels)``."""

    audio_path = Path(path)
    try:
        data, sample_rate = sf.read(
            audio_path, dtype="int16", always_2d=True, frames=-1
        )
    except Exception as exc:  # soundfile raises several exception types
        raise AudioError(f"cannot read audio file {audio_path}: {exc}") from exc

    try:
        info = sf.info(audio_path)
    except Exception as exc:
        raise AudioError(f"cannot inspect audio file {audio_path}: {exc}") from exc

    return data, AudioInfo(
        path=audio_path,
        sample_rate=int(sample_rate),
        channels=int(data.shape[1]),
        frames=int(data.shape[0]),
        sample_width_bytes=2,
        duration_seconds=float(info.frames) / float(info.samplerate),
        format=str(info.format),
        subtype=str(info.subtype),
    )


def inspect_wav(path: Path | str) -> AudioInfo:
    """Read header information without decoding the whole file."""

    audio_path = Path(path)
    try:
        info = sf.info(audio_path)
    except Exception as exc:
        raise AudioError(f"cannot inspect audio file {audio_path}: {exc}") from exc
    width = _subtype_width_bytes(str(info.subtype))
    return AudioInfo(
        path=audio_path,
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        frames=int(info.frames),
        sample_width_bytes=width,
        duration_seconds=float(info.frames) / float(info.samplerate),
        format=str(info.format),
        subtype=str(info.subtype),
    )


def _subtype_width_bytes(subtype: str) -> int:
    if subtype in {"PCM_16", "PCM_S8"}:
        return 2 if subtype == "PCM_16" else 1
    if subtype in {"PCM_24"}:
        return 3
    if subtype in {"PCM_32", "FLOAT", "DOUBLE"}:
        return 4
    if subtype in {"ULAW", "ALAW"}:
        return 1
    # Vorbis/MP3-like compressed subtypes are not valid WAV sample widths.
    return 2


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Downmix to one channel by averaging; no-op for mono input."""

    if samples.ndim == 1:
        return samples.reshape(-1, 1)
    if samples.shape[1] == 1:
        return samples
    mixed = samples.astype(np.float64).mean(axis=1)
    return _to_int16(mixed.reshape(-1, 1))


def resample_linear(
    samples: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    """Resample with linear interpolation.

    This is intentionally simple and dependency-free. It is adequate for the
    lab's one conversion (Gemini 24 kHz -> an ASR-friendly rate) and for tests.
    It is not a production resampler: linear interpolation can alias, so the
    default target equals the native rate and no conversion happens.
    """

    if source_rate <= 0 or target_rate <= 0:
        raise AudioError("sample rates must be positive")
    if source_rate == target_rate:
        return samples

    data = samples if samples.ndim == 2 else samples.reshape(-1, 1)
    frame_count = data.shape[0]
    if frame_count == 0:
        return np.zeros((0, data.shape[1]), dtype=np.int16)

    target_frames = int(round(frame_count * target_rate / source_rate))
    target_frames = max(target_frames, 1)
    old_positions = np.arange(frame_count, dtype=np.float64)
    new_positions = np.linspace(0.0, frame_count - 1, target_frames)

    channels: list[np.ndarray] = []
    for channel in range(data.shape[1]):
        resampled = np.interp(
            new_positions, old_positions, data[:, channel].astype(np.float64)
        )
        channels.append(resampled)
    stacked = np.stack(channels, axis=1)
    return _to_int16(stacked)


def _to_int16(values: np.ndarray) -> np.ndarray:
    rounded = np.rint(values)
    clipped = np.clip(rounded, _INT16_MIN, _INT16_MAX)
    return clipped.astype(np.int16)


def silence(duration_ms: int, sample_rate: int, channels: int = 1) -> np.ndarray:
    if duration_ms < 0:
        raise AudioError("pause duration cannot be negative")
    frames = int(round(sample_rate * duration_ms / 1000))
    return np.zeros((frames, channels), dtype=np.int16)


def concatenate(parts: list[np.ndarray]) -> np.ndarray:
    if not parts:
        return np.zeros((0, 1), dtype=np.int16)
    channels = {part.shape[1] for part in parts}
    if len(channels) != 1:
        raise AudioError(f"cannot concatenate mixed channel counts: {sorted(channels)}")
    return np.concatenate(parts, axis=0)


def concatenate_with_pauses(
    parts: list[np.ndarray],
    pause_ms: list[int],
    sample_rate: int,
) -> np.ndarray:
    """Concatenate parts, inserting one silence between each pair.

    ``pause_ms`` has ``len(parts) - 1`` entries. There is no trailing silence;
    the reference timeline therefore ends exactly at the last spoken word.
    """

    if len(pause_ms) != max(len(parts) - 1, 0):
        raise AudioError(
            f"expected {max(len(parts) - 1, 0)} pauses, got {len(pause_ms)}"
        )
    if not parts:
        return np.zeros((0, 1), dtype=np.int16)

    channels = parts[0].shape[1]
    pieces: list[np.ndarray] = []
    for index, part in enumerate(parts):
        pieces.append(part)
        if index < len(parts) - 1:
            pieces.append(silence(pause_ms[index], sample_rate, channels))
    return concatenate(pieces)


def write_wav(
    path: Path | str,
    samples: np.ndarray,
    sample_rate: int,
    *,
    subtype: str = "PCM_16",
) -> None:
    audio_path = Path(path)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    data = samples if samples.ndim == 2 else samples.reshape(-1, 1)
    try:
        sf.write(
            audio_path,
            data,
            sample_rate,
            subtype=subtype,
            format="WAV",
        )
    except Exception as exc:
        raise AudioError(f"cannot write WAV file {audio_path}: {exc}") from exc


def duration_seconds(samples: np.ndarray, sample_rate: int) -> float:
    if sample_rate <= 0:
        raise AudioError("sample rate must be positive")
    frames = samples.shape[0] if samples.ndim >= 1 else 0
    return frames / sample_rate


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_native_format(info: AudioInfo) -> list[str]:
    """Return warnings when a segment is not the documented native format."""

    warnings: list[str] = []
    if info.format.upper() != "WAV":
        warnings.append(f"{info.path.name}: format is {info.format}, expected WAV")
    if info.sample_rate != config.TTS_NATIVE_SAMPLE_RATE:
        warnings.append(
            f"{info.path.name}: sample rate is {info.sample_rate} Hz, "
            f"expected {config.TTS_NATIVE_SAMPLE_RATE} Hz; it will be resampled"
        )
    if info.channels != config.TTS_NATIVE_CHANNELS:
        warnings.append(
            f"{info.path.name}: {info.channels} channels, expected mono; "
            "it will be downmixed"
        )
    if info.subtype != "PCM_16":
        warnings.append(
            f"{info.path.name}: subtype is {info.subtype}, expected PCM_16"
        )
    return warnings
