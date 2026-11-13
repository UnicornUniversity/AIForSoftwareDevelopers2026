"""Shared offline test helpers: no network, no API key, no model download."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fixtures import load_fixture  # noqa: E402
from src.tts.voices import VoiceAssignment  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_from_dotenv(monkeypatch) -> None:
    """Never let a test read a developer's ``.env``.

    The CLI entry points load ``.env`` on start. A real key there would turn
    the offline suite into a live one, so tests neutralize the loader. The
    loader itself is exercised with temporary files in ``test_tokens.py``.
    """

    for target in (
        "src.tts.__main__.load_environment",
        "src.asr.gemini.__main__.load_environment",
        "src.asr.whisperx.__main__.load_environment",
    ):
        monkeypatch.setattr(target, lambda: None)


def wav_bytes(
    seconds: float,
    sample_rate: int = 24_000,
    frequency: float = 440.0,
    channels: int = 1,
) -> bytes:
    """Render a quiet sine tone as 16-bit PCM WAV bytes."""

    frames = max(1, int(round(seconds * sample_rate)))
    time = np.arange(frames, dtype=np.float64) / sample_rate
    tone = 0.1 * np.sin(2 * np.pi * frequency * time)
    samples = np.round(tone * 32767).astype(np.int16)
    if channels > 1:
        samples = np.repeat(samples[:, None], channels, axis=1)
    else:
        samples = samples[:, None]
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def write_wav(
    path: Path,
    seconds: float,
    sample_rate: int = 24_000,
    frequency: float = 440.0,
    channels: int = 1,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        wav_bytes(seconds, sample_rate, frequency, channels)
    )
    return path


@dataclass(frozen=True)
class FakeResult:
    audio_bytes: bytes
    mime_type: str = "audio/wav"
    model: str = "fake-tts-model"
    interaction_id: str = "fake-interaction"


class FakeTTSClient:
    """Deterministic stand-in for :class:`GeminiTTSClient`.

    Segment duration is derived from text length so tests can prove that the
    assembled order follows the script, not the call order.
    """

    def __init__(
        self,
        sample_rate: int = 24_000,
        channels: int = 1,
        fail_on: int | None = None,
    ) -> None:
        self.model = "fake-tts-model"
        self.sample_rate = sample_rate
        self.channels = channels
        self.fail_on = fail_on
        self.calls: list[tuple[str, VoiceAssignment]] = []

    def synthesize(self, text: str, voice: VoiceAssignment) -> FakeResult:
        if self.fail_on is not None and len(self.calls) + 1 == self.fail_on:
            raise RuntimeError("simulated API failure")
        self.calls.append((text, voice))
        seconds = max(0.08, len(text) / 80)
        return FakeResult(
            audio_bytes=wav_bytes(
                seconds,
                sample_rate=self.sample_rate,
                frequency=220.0 + 40.0 * len(self.calls),
                channels=self.channels,
            )
        )


@pytest.fixture()
def fixture():
    return load_fixture()


@pytest.fixture()
def dummy_voice() -> VoiceAssignment:
    return VoiceAssignment(
        speaker_id="ANN",
        full_name="Ann Smith",
        gender="female",
        voice_name="Kore",
        style="calm",
        rationale="test",
    )
