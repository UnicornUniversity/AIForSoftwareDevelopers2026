"""Gemini TTS adapter for the Interactions API.

Only one voice is requested per call. That is deliberate: Gemini's documented
single-request multi-speaker mode supports at most two prebuilt voices, so a
three-participant meeting must be synthesized turn by turn and concatenated.

The adapter is the only module that knows the vendor schema. Tests inject a fake
``client`` object and never touch the network.
"""

from __future__ import annotations

import base64
import io
import os
import wave
from dataclasses import dataclass
from typing import Any, Mapping

from src import config
from src.tts.voices import VoiceAssignment


class TTSError(RuntimeError):
    """Base class for TTS-stage failures with student-readable messages."""


class MissingAPIKeyError(TTSError):
    """Raised when no Gemini API key is present in the environment."""


class TTSResponseError(TTSError):
    """Raised when the API response does not contain usable audio."""


@dataclass(frozen=True)
class SynthesisResult:
    audio_bytes: bytes
    mime_type: str
    model: str
    interaction_id: str | None


def load_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """Read the key from the environment only, never from a file or argument.

    ``GEMINI_API_KEY`` is the documented name for this lab; ``GOOGLE_API_KEY``
    is accepted because the Google GenAI SDK also reads it. Values are never
    logged or written to a manifest.
    """

    source = os.environ if env is None else env
    for name in (config.GEMINI_API_KEY_ENV, config.GOOGLE_API_KEY_ENV):
        value = source.get(name, "").strip()
        if value:
            return value
    return None


def load_environment(path=None) -> None:
    """Load ``.env`` if python-dotenv is available.

    Called by the CLI, not at import time, so tests stay hermetic.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - requirements installs it
        return
    load_dotenv(path if path is not None else config.ENV_FILE, override=False)


def build_request(
    text: str,
    voice_name: str,
    style: str = "",
    *,
    model: str | None = None,
    mime_type: str = config.TTS_DEFAULT_RESPONSE_MIME,
    sample_rate: int = config.TTS_NATIVE_SAMPLE_RATE,
) -> dict[str, Any]:
    """Build the documented single-speaker TTS request body.

    The annotations carry delivery style only. Participant names, genders, and
    the meeting metadata are never sent.
    """

    if not text.strip():
        raise TTSError("cannot synthesize an empty turn")
    if not voice_name.strip():
        raise TTSError("a prebuilt voice name is required")

    annotation: dict[str, str] = {"type": "speech_metadata"}
    if style.strip():
        annotation["style"] = style.strip()

    return {
        "model": model or config.TTS_MODEL,
        "input": [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [annotation],
                    }
                ],
            }
        ],
        "response_format": {
            "type": "audio",
            "mime_type": mime_type,
            "sample_rate": sample_rate,
        },
        "generation_config": {
            "speech_config": [{"voice": voice_name}],
        },
    }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def extract_audio(interaction: Any) -> tuple[bytes, str, int | None]:
    """Pull base64 audio, MIME type, and sample rate from an Interaction."""

    output = _field(interaction, "output_audio")
    if output is None:
        raise TTSResponseError(
            "the API response contains no audio; check model access and that "
            "response_format requested audio"
        )

    encoded = _field(output, "data")
    if not encoded:
        raise TTSResponseError("the API response audio payload is empty")

    # JSON base64 should not contain whitespace, but a wrapped payload is still
    # valid base64. Strip it before strict validation so a formatting change in
    # the API does not masquerade as corrupt audio.
    compact = "".join(str(encoded).split())
    try:
        audio_bytes = base64.b64decode(compact, validate=True)
    except Exception as exc:
        raise TTSResponseError(f"cannot decode base64 audio payload: {exc}") from exc

    mime_type = str(_field(output, "mime_type") or config.TTS_DEFAULT_RESPONSE_MIME)
    sample_rate = _field(output, "sample_rate")
    return audio_bytes, mime_type, int(sample_rate) if sample_rate else None


def ensure_wav(
    audio_bytes: bytes, mime_type: str, sample_rate: int | None = None
) -> bytes:
    """Return WAV bytes, wrapping headerless L16 PCM if the API returns it."""

    normalized = mime_type.lower().split(";")[0].strip()
    if normalized in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return audio_bytes
    if normalized in {"audio/l16", "audio/pcm"}:
        rate = sample_rate or config.TTS_NATIVE_SAMPLE_RATE
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(config.TTS_NATIVE_CHANNELS)
            handle.setsampwidth(config.TTS_NATIVE_SAMPLE_WIDTH_BYTES)
            handle.setframerate(rate)
            handle.writeframes(audio_bytes)
        return buffer.getvalue()
    raise TTSResponseError(
        f"unsupported audio MIME type {mime_type!r}; request audio/wav "
        "(the documented default for unary TTS)"
    )


class GeminiTTSClient:
    """Thin adapter around ``google-genai``'s Interactions API."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = config.TTS_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model or config.TTS_MODEL
        self.timeout = timeout
        self._provided_client = client is not None
        if client is not None:
            self._client = client
            return

        key = api_key or load_api_key()
        if not key:
            raise MissingAPIKeyError(
                f"no Gemini API key found. Put {config.GEMINI_API_KEY_ENV}=... "
                "in .env (see .env.example) or export it in the environment. "
                "The manual Google AI Studio workflow needs no key."
            )
        # Import lazily so offline tests and the manual route do not need the
        # SDK's import cost or network-related setup.
        from google import genai

        self._client = genai.Client(
            api_key=key,
            http_options={"api_version": config.TTS_API_VERSION},
        )

    def synthesize(
        self, text: str, voice: VoiceAssignment
    ) -> SynthesisResult:
        request = build_request(text, voice.voice_name, voice.style, model=self.model)
        try:
            interaction = self._client.interactions.create(
                timeout=self.timeout, **request
            )
        except Exception as exc:
            raise TTSError(
                f"Gemini TTS request failed for voice {voice.voice_name!r}: {exc}"
            ) from exc

        audio_bytes, mime_type, sample_rate = extract_audio(interaction)
        wav_bytes = ensure_wav(audio_bytes, mime_type, sample_rate)
        return SynthesisResult(
            audio_bytes=wav_bytes,
            mime_type="audio/wav",
            model=self.model,
            interaction_id=_field(interaction, "id"),
        )


def cloud_call_notice(model: str, turn_count: int) -> list[str]:
    """Plain-language cost and privacy notice shown before any API call."""

    return [
        "Cloud TTS confirmation",
        f"  Model: {model}",
        f"  Calls: {turn_count} (one request per turn; no three-speaker request)",
        "  Uploaded: the spoken text of each turn, plus a delivery-style hint.",
        "  Not uploaded: participant names, genders, roles, ground truth, or",
        "  the meeting metadata. The audio itself is generated, not uploaded.",
        "  Cost: TTS usage is billed by Google. No price is quoted here because",
        f"  it changes; check {config.PRICING_URL} and {config.USAGE_URL}.",
        "  Privacy: the spoken text leaves this machine. The controlled fixture",
        "  is fictional; do not use this route with a real private transcript",
        "  unless you have permission.",
    ]
