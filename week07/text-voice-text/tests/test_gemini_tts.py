from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from src import config
from src.tts.gemini_tts import (
    GeminiTTSClient,
    MissingAPIKeyError,
    TTSError,
    TTSResponseError,
    build_request,
    cloud_call_notice,
    ensure_wav,
    extract_audio,
    load_api_key,
)
from tests.conftest import wav_bytes


def _interaction(audio: bytes, mime: str = "audio/wav", sample_rate: int = 24_000):
    return SimpleNamespace(
        id="interaction-1",
        output_audio=SimpleNamespace(
            data=base64.b64encode(audio).decode("ascii"),
            mime_type=mime,
            sample_rate=sample_rate,
        ),
    )


def test_request_is_single_speaker_with_one_voice(dummy_voice) -> None:
    request = build_request("Hello there.", dummy_voice.voice_name, dummy_voice.style)
    assert request["model"] == config.TTS_MODEL
    assert request["input"][0]["type"] == "user_input"
    content = request["input"][0]["content"][0]
    assert content["type"] == "text"
    assert content["text"] == "Hello there."
    assert content["annotations"] == [
        {"type": "speech_metadata", "style": "calm"}
    ]
    assert request["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert request["response_format"]["type"] == "audio"
    assert request["response_format"]["mime_type"] == "audio/wav"


def test_request_omits_empty_style(dummy_voice) -> None:
    request = build_request("Hi.", dummy_voice.voice_name, "")
    assert request["input"][0]["content"][0]["annotations"] == [
        {"type": "speech_metadata"}
    ]


def test_request_never_contains_participant_metadata(dummy_voice) -> None:
    request = build_request("The migration is on track.", dummy_voice.voice_name)
    serialized = str(request)
    for forbidden in ("Ann Smith", "ANN", "female", "ground_truth", "meeting_id"):
        assert forbidden not in serialized


def test_empty_text_is_rejected(dummy_voice) -> None:
    with pytest.raises(TTSError):
        build_request("   ", dummy_voice.voice_name)


def test_extract_audio_decodes_base64(dummy_voice) -> None:
    audio = wav_bytes(0.1)
    decoded, mime, rate = extract_audio(_interaction(audio))
    assert decoded == audio
    assert mime == "audio/wav"
    assert rate == 24_000


def test_extract_audio_tolerates_wrapped_base64() -> None:
    audio = wav_bytes(0.1)
    encoded = base64.b64encode(audio).decode("ascii")
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    interaction = SimpleNamespace(
        output_audio=SimpleNamespace(data=wrapped, mime_type="audio/wav")
    )
    decoded, _, _ = extract_audio(interaction)
    assert decoded == audio


def test_extract_audio_rejects_missing_output() -> None:
    with pytest.raises(TTSResponseError, match="no audio"):
        extract_audio(SimpleNamespace(output_audio=None))


def test_extract_audio_rejects_bad_base64() -> None:
    interaction = SimpleNamespace(
        output_audio=SimpleNamespace(data="not-base64!!", mime_type="audio/wav")
    )
    with pytest.raises(TTSResponseError):
        extract_audio(interaction)


def test_ensure_wav_passes_wav_through() -> None:
    audio = wav_bytes(0.1)
    assert ensure_wav(audio, "audio/wav") == audio


def test_ensure_wav_wraps_l16() -> None:
    frames = np.zeros((2_400, 1), dtype=np.int16)
    raw = frames.tobytes()
    wrapped = ensure_wav(raw, "audio/l16", 24_000)
    data, rate = sf.read(io.BytesIO(wrapped), dtype="int16", always_2d=True)
    assert rate == 24_000
    assert data.shape == (2_400, 1)


def test_ensure_wav_rejects_unsupported_mime() -> None:
    with pytest.raises(TTSResponseError, match="unsupported audio MIME"):
        ensure_wav(b"x", "audio/ogg_opus")


def test_client_synthesizes_through_injected_sdk(dummy_voice) -> None:
    audio = wav_bytes(0.2)

    class FakeInteractions:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        def create(self, **body):
            self.requests.append(body)
            return _interaction(audio)

    class FakeSDK:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    sdk = FakeSDK()
    client = GeminiTTSClient(client=sdk, model="gemini-3.8-flash-tts")
    result = client.synthesize("Hello.", dummy_voice)
    assert result.audio_bytes == audio
    assert result.model == "gemini-3.8-flash-tts"
    assert result.interaction_id == "interaction-1"
    body = sdk.interactions.requests[0]
    assert body["model"] == "gemini-3.8-flash-tts"
    assert body["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert body["timeout"] == config.TTS_REQUEST_TIMEOUT_SECONDS


def test_client_pins_the_interactions_api_version(monkeypatch) -> None:
    import google.genai as genai

    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(genai, "Client", FakeClient)

    GeminiTTSClient(api_key="test-key")

    assert captured["api_key"] == "test-key"
    assert captured["http_options"] == {"api_version": config.TTS_API_VERSION}
    assert config.TTS_API_VERSION == "v1beta"


def test_client_without_key_raises(monkeypatch) -> None:
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    with pytest.raises(MissingAPIKeyError):
        GeminiTTSClient()


def test_load_api_key_precedence(monkeypatch) -> None:
    monkeypatch.setenv(config.GOOGLE_API_KEY_ENV, "fallback")
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    assert load_api_key() == "fallback"
    monkeypatch.setenv(config.GEMINI_API_KEY_ENV, "primary")
    assert load_api_key() == "primary"


def test_cloud_notice_mentions_cost_and_privacy() -> None:
    text = "\n".join(cloud_call_notice(config.TTS_MODEL, 39))
    assert "39" in text
    assert "billed" in text
    assert "privacy" in text.lower()
    assert "names" in text.lower()


def test_cloud_notice_never_contains_a_key() -> None:
    text = "\n".join(cloud_call_notice(config.TTS_MODEL, 1))
    assert "AIza" not in text
    assert "api_key=" not in text.lower()
