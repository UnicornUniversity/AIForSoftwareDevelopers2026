from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.tts.audio import (
    AudioError,
    concatenate_with_pauses,
    duration_seconds,
    ensure_native_format,
    inspect_wav,
    read_wav,
    resample_linear,
    sha256_file,
    silence,
    to_mono,
    write_wav,
)
from tests.conftest import write_wav as write_tone_wav


def test_resample_changes_frame_count_proportionally() -> None:
    samples = np.zeros((24_000, 1), dtype=np.int16)
    result = resample_linear(samples, 24_000, 16_000)
    assert result.shape[1] == 1
    assert abs(result.shape[0] - 16_000) <= 1


def test_resample_same_rate_is_identity() -> None:
    samples = np.arange(100, dtype=np.int16).reshape(-1, 1)
    np.testing.assert_array_equal(resample_linear(samples, 24_000, 24_000), samples)


def test_resample_preserves_a_constant_signal() -> None:
    samples = np.full((1_000, 1), 1_000, dtype=np.int16)
    result = resample_linear(samples, 24_000, 8_000)
    assert np.all(result == 1_000)


def test_resample_each_channel_independently() -> None:
    left = np.full((100, 1), 1000, dtype=np.int16)
    right = np.full((100, 1), -1000, dtype=np.int16)
    stereo = np.concatenate([left, right], axis=1)
    result = resample_linear(stereo, 24_000, 12_000)
    assert result.shape[1] == 2
    assert np.all(result[:, 0] == 1000)
    assert np.all(result[:, 1] == -1000)


def test_to_mono_averages_stereo() -> None:
    stereo = np.array([[100, 300], [200, 400]], dtype=np.int16)
    mono = to_mono(stereo)
    assert mono.shape == (2, 1)
    assert mono[0, 0] == 200
    assert mono[1, 0] == 300


def test_to_mono_leaves_mono_unchanged() -> None:
    mono = np.array([[1], [2]], dtype=np.int16)
    assert to_mono(mono) is mono


def test_silence_length_in_frames() -> None:
    assert silence(500, 24_000).shape == (12_000, 1)
    assert silence(0, 24_000).shape == (0, 1)
    with pytest.raises(AudioError):
        silence(-1, 24_000)


def test_concatenate_with_pauses_inserts_exact_silence() -> None:
    first = np.ones((100, 1), dtype=np.int16)
    second = np.full((50, 1), 2, dtype=np.int16)
    result = concatenate_with_pauses([first, second], [250], 24_000)
    assert result.shape[0] == 100 + 6_000 + 50
    assert np.all(result[100:6_100] == 0)
    assert np.all(result[:100] == 1)
    assert np.all(result[-50:] == 2)


def test_concatenate_with_pauses_has_no_trailing_silence() -> None:
    part = np.ones((10, 1), dtype=np.int16)
    result = concatenate_with_pauses([part, part], [100], 1_000)
    assert result.shape[0] == 10 + 100 + 10
    assert result[-1, 0] == 1


def test_concatenate_with_pauses_rejects_wrong_pause_count() -> None:
    part = np.ones((10, 1), dtype=np.int16)
    with pytest.raises(AudioError):
        concatenate_with_pauses([part, part, part], [10], 1_000)


def test_wav_roundtrip_is_pcm16(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    samples, _ = read_wav(write_tone_wav(path, seconds=0.25, sample_rate=24_000))
    assert samples.dtype == np.int16
    assert samples.shape == (6_000, 1)


def test_write_wav_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "out.wav"
    write_wav(path, samples=np.zeros((10, 1), dtype=np.int16), sample_rate=24_000)
    assert path.exists()


def test_inspect_wav_reports_format(tmp_path: Path) -> None:
    path = write_tone_wav(tmp_path / "a.wav", seconds=0.1, sample_rate=16_000)
    info = inspect_wav(path)
    assert info.sample_rate == 16_000
    assert info.channels == 1
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.sample_width_bytes == 2
    assert info.duration_seconds == pytest.approx(0.1, rel=0.01)


def test_duration_seconds() -> None:
    assert duration_seconds(np.zeros((24_000, 1)), 24_000) == pytest.approx(1.0)


def test_native_format_warnings_flag_resampling_and_downmix(tmp_path: Path) -> None:
    path = write_tone_wav(
        tmp_path / "odd.wav", seconds=0.05, sample_rate=16_000, channels=2
    )
    warnings = ensure_native_format(inspect_wav(path))
    joined = " ".join(warnings)
    assert "sample rate" in joined
    assert "channels" in joined


def test_native_format_has_no_warnings(tmp_path: Path) -> None:
    path = write_tone_wav(tmp_path / "ok.wav", seconds=0.05)
    assert ensure_native_format(inspect_wav(path)) == []


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"hello")
    assert sha256_file(path) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_read_wav_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AudioError):
        read_wav(tmp_path / "missing.wav")


def test_write_wav_rejects_zero_sample_rate(tmp_path: Path) -> None:
    with pytest.raises(AudioError):
        write_wav(tmp_path / "x.wav", np.zeros((1, 1), dtype=np.int16), 0)
