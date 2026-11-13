"""Build and validate the documented Gemini transcription request.

Only the waveform URI, the MIME type, and explicit model settings are sent.
Participant names, roles, the turn map, the script, and ``ground_truth.json``
are never part of a request body; the blind-run rule is enforced here as well as
in the runner.

Documented shape (verified 2026-11-12, ``gemini-3.5-transcribe``)::

    client.interactions.create(
        model="gemini-3.5-transcribe",
        input=[{"type": "audio", "uri": file.uri, "mime_type": "audio/wav"}],
        generation_config={"transcription_config": {
            "mode": {
                "type": "verbatim",
                "diarization_mode": "speaker",
                "timestamp_granularities": ["word"],
            },
            "language_codes": ["en-US"],
        }},
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from src import config


class TranscribeRequestError(RuntimeError):
    """Raised when transcription options are invalid or incompatible."""


#: MIME types accepted by the documented audio content block.
AUDIO_MIME_TYPES = frozenset(
    {
        "audio/wav",
        "audio/mp3",
        "audio/aiff",
        "audio/aac",
        "audio/ogg",
        "audio/flac",
        "audio/mpeg",
        "audio/m4a",
        "audio/l16",
        "audio/opus",
        "audio/alaw",
        "audio/mulaw",
        "audio/webm",
    }
)

#: The documented compatibility caveat, quoted in the error so a student sees
#: the rule instead of a mystery rejection from the API.
CUSTOM_VOCABULARY_CAVEAT = (
    "Documented limitation: custom_vocabulary cannot be combined with speaker "
    "diarization or word-level timestamps. The API rejects such requests, so "
    "the lab refuses to build one. Run the primary comparison without custom "
    "vocabulary, or disable diarization and timestamps and label the run as a "
    "separate vocabulary experiment."
)


@dataclass(frozen=True)
class TranscribeOptions:
    """Explicit model settings for one transcription request."""

    model: str = config.TRANSCRIBE_MODEL
    diarize: bool = config.TRANSCRIBE_DEFAULT_DIARIZE
    word_timestamps: bool = config.TRANSCRIBE_DEFAULT_WORD_TIMESTAMPS
    language_codes: tuple[str, ...] = config.TRANSCRIBE_DEFAULT_LANGUAGE_CODES
    custom_vocabulary: tuple[str, ...] = ()
    store_remote: bool = config.TRANSCRIBE_DEFAULT_STORE_REMOTE


def _clean_codes(codes: Sequence[str]) -> list[str]:
    cleaned = [str(code).strip() for code in codes if str(code).strip()]
    return cleaned


def validate_options(options: TranscribeOptions) -> None:
    """Reject invalid or documented-incompatible combinations early."""

    if not str(options.model).strip():
        raise TranscribeRequestError("a transcription model id is required")
    if options.custom_vocabulary and (
        options.diarize or options.word_timestamps
    ):
        raise TranscribeRequestError(CUSTOM_VOCABULARY_CAVEAT)
    if options.custom_vocabulary:
        terms = [str(term).strip() for term in options.custom_vocabulary]
        if any(not term for term in terms):
            raise TranscribeRequestError(
                "custom vocabulary contains an empty term"
            )
        if len(terms) > 1000:
            raise TranscribeRequestError(
                "custom vocabulary is limited to 1,000 terms; the documentation "
                "recommends about 100 for best results"
            )
    if len(_clean_codes(options.language_codes)) > 4:
        raise TranscribeRequestError(
            "at most four language hints are useful; pass a BCP-47 list such "
            "as ['en-US'] or leave it empty for automatic detection"
        )


def build_transcription_config(options: TranscribeOptions) -> dict[str, Any]:
    """Build the ``transcription_config`` object for verbatim mode."""

    mode: dict[str, Any] = {"type": "verbatim"}
    if options.diarize:
        mode["diarization_mode"] = config.TRANSCRIBE_DIARIZATION_MODE
    if options.word_timestamps:
        mode["timestamp_granularities"] = ["word"]

    transcription_config: dict[str, Any] = {"mode": mode}
    codes = _clean_codes(options.language_codes)
    if codes:
        transcription_config["language_codes"] = codes
    if options.custom_vocabulary:
        transcription_config["custom_vocabulary"] = [
            str(term).strip() for term in options.custom_vocabulary
        ]
    return transcription_config


def build_request(
    audio_uri: str,
    mime_type: str,
    options: TranscribeOptions,
) -> dict[str, Any]:
    """Build the full Interactions API request body.

    ``audio_uri`` is the URI returned by the Files API. The raw bytes are never
    inlined here; a meeting WAV can be tens of megabytes.
    """

    if not str(audio_uri).strip():
        raise TranscribeRequestError("an uploaded audio URI is required")

    normalized_mime = str(mime_type or "audio/wav").lower().split(";")[0].strip()
    if normalized_mime not in AUDIO_MIME_TYPES:
        supported = ", ".join(sorted(AUDIO_MIME_TYPES))
        raise TranscribeRequestError(
            f"unsupported audio MIME type {mime_type!r}. Supported: {supported}"
        )

    validate_options(options)

    return {
        "model": options.model,
        "input": [
            {
                "type": "audio",
                "uri": audio_uri,
                "mime_type": normalized_mime,
            }
        ],
        "generation_config": {
            "transcription_config": build_transcription_config(options)
        },
        "store": bool(options.store_remote),
    }
