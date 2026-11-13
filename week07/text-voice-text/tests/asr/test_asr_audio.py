from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.asr.audio import AudioLoadError, load_audio_16k, resample_linear
from tests.conftest import write_wav


def test_loads_24k_mono_and_resamples_to_16k(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "meeting.wav", seconds=0.5, sample_rate=24_000)
    audio = load_audio_16k(path)
    assert audio.sample_rate == 16_000
    assert audio.source_rate == 24_000
    assert audio.channels == 1
    assert audio.samples.dtype == np.float32
    assert abs(audio.samples.size - 8_000) <= 1
    assert audio.duration_seconds == pytest.approx(0.5, rel=0.01)


def test_downmixes_stereo(tmp_path: Path) -> None:
    path = write_wav(
        tmp_path / "stereo.wav", seconds=0.2, sample_rate=24_000, channels=2
    )
    audio = load_audio_16k(path)
    assert audio.channels == 2
    assert audio.samples.ndim == 1


def test_native_16k_needs_no_resampling(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", seconds=0.2, sample_rate=16_000)
    audio = load_audio_16k(path)
    assert audio.source_rate == 16_000
    assert audio.samples.size == 3_200


def test_resample_preserves_a_constant_signal() -> None:
    data = np.full(2_400, 0.25, dtype=np.float32)
    result = resample_linear(data, 24_000, 16_000)
    assert result.size == 1_600
    np.testing.assert_allclose(result, 0.25, atol=1e-6)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(AudioLoadError, match="not found"):
        load_audio_16k(tmp_path / "missing.wav")


def test_non_wav_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "not.wav"
    path.write_bytes(b"not audio")
    with pytest.raises(AudioLoadError, match="cannot read"):
        load_audio_16k(path)


def test_empty_waveform_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty.wav"
    import soundfile as sf

    sf.write(str(path), np.zeros((0,), dtype=np.int16), 16_000, format="WAV")
    with pytest.raises(AudioLoadError, match="no audio frames"):
        load_audio_16k(path)


def test_resample_rejects_bad_rates() -> None:
    with pytest.raises(AudioLoadError):
        resample_linear(np.zeros(10, dtype=np.float32), 0, 16_000)
