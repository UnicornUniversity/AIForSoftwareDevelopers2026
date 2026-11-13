"""The only module that talks to the Gemini transcription API.

Responsibilities: key handling (environment only), Files API upload, waiting
for the file to become active, the Interactions call, uploading-file cleanup,
and translating SDK errors into student-readable failures.

Tests inject a fake ``client`` object; no test performs a network call and no
test constructs a real ``genai.Client``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src import config
from src.asr.gemini.parse import interaction_to_mapping
from src.asr.gemini.request import TranscribeOptions, build_request


class TranscribeError(RuntimeError):
    """Base class for cloud transcription failures."""


class MissingAPIKeyError(TranscribeError):
    """No ``GEMINI_API_KEY``/``GOOGLE_API_KEY`` is present in the environment."""


class APIKeyRejectedError(TranscribeError):
    """The API rejected the supplied key (401)."""


class ModelAccessError(TranscribeError):
    """The model is not available to this key or project (403/404)."""


class QuotaError(TranscribeError):
    """Rate limit or quota exhausted (429)."""


class UploadError(TranscribeError):
    """The audio upload failed or the file never became active."""


class TranscribeAPIError(TranscribeError):
    """Any other API rejection, with the documented status and message."""


class TranscribeResponseError(TranscribeError):
    """The interaction finished without a usable transcription result."""


@dataclass(frozen=True)
class TranscribeResult:
    raw: Mapping[str, Any]
    interaction_id: str | None
    uploaded_file: str | None
    file_deleted: bool
    timings: Mapping[str, float]


def load_api_key(env: Mapping[str, str] | None = None) -> str | None:
    """Read the key from the environment only; never from a file or argument."""

    source = os.environ if env is None else env
    for name in (config.GEMINI_API_KEY_ENV, config.GOOGLE_API_KEY_ENV):
        value = source.get(name, "").strip()
        if value:
            return value
    return None


def load_environment(path: Path | None = None) -> None:
    """Load ``.env`` if python-dotenv is available; called by the CLI only."""

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - requirements installs it
        return
    load_dotenv(path if path is not None else config.ENV_FILE, override=False)


def _state_name(state: Any) -> str:
    if state is None:
        return ""
    name = getattr(state, "name", None)
    if isinstance(name, str):
        return name.upper()
    text = str(state)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.upper()


def translate_api_error(exc: Exception) -> TranscribeError:
    """Map an SDK/API exception to a friendly error without leaking the key."""

    code = getattr(exc, "code", None)
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    status = str(getattr(exc, "status", "") or "").strip()
    detail = str(getattr(exc, "message", "") or exc).strip()
    label = f"{code or '?'} {status}".strip()

    if code == 401:
        return APIKeyRejectedError(
            f"The Gemini API rejected the key ({label}). Check that "
            f"{config.GEMINI_API_KEY_ENV} in .env is current and belongs to the "
            f"project you expect. The key value is never printed.\n"
            f"Service message: {detail}"
        )
    if code == 403:
        return ModelAccessError(
            f"Access denied ({label}). The API key does not have access to "
            f"{config.TRANSCRIBE_MODEL!r}. Confirm model availability for the "
            f"key's project and check {config.TRANSCRIBE_DOCS_URL}.\n"
            f"Service message: {detail}"
        )
    if code == 404:
        return ModelAccessError(
            f"Model or resource not found ({label}). {config.TRANSCRIBE_MODEL!r} "
            f"may be retired or unavailable to this key; re-verify the model id "
            f"at {config.TRANSCRIBE_DOCS_URL}.\nService message: {detail}"
        )
    if code == 429:
        return QuotaError(
            f"Rate limit or quota exhausted ({label}). Wait and retry, check "
            f"usage at {config.USAGE_URL}, and avoid re-running a whole "
            f"transcription in a loop.\nService message: {detail}"
        )
    if code == 413:
        return UploadError(
            f"The request was too large ({label}). The meeting WAV exceeds the "
            f"documented request size; split the audio below the limit and "
            f"reconcile the parts.\nService message: {detail}"
        )
    if code == 400:
        return TranscribeAPIError(
            f"The API rejected the request ({label}). Check the documented "
            f"transcription options at {config.TRANSCRIBE_DOCS_URL}.\n"
            f"Service message: {detail}"
        )
    if code is not None and 500 <= int(code) < 600:
        return TranscribeAPIError(
            f"Google reported a server error ({label}). This is usually "
            f"transient; retry once, then check the status page.\n"
            f"Service message: {detail}"
        )
    return TranscribeAPIError(f"Gemini transcription failed ({label}): {detail}")


class GeminiTranscribeClient:
    """Thin adapter around ``google-genai`` Files + Interactions APIs."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = config.TRANSCRIBE_REQUEST_TIMEOUT_SECONDS,
        active_timeout: float = config.TRANSCRIBE_UPLOAD_ACTIVE_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model or config.TRANSCRIBE_MODEL
        self.timeout = timeout
        self.active_timeout = active_timeout
        self._sleep = sleep
        if client is not None:
            self._client = client
            return

        key = api_key or load_api_key()
        if not key:
            raise MissingAPIKeyError(
                f"no Gemini API key found. Put {config.GEMINI_API_KEY_ENV}=... "
                "in .env (see .env.example) or export it in the environment. "
                "The key is read from the environment only and is never logged."
            )
        from google import genai

        self._client = genai.Client(
            api_key=key,
            http_options={"api_version": config.TRANSCRIBE_API_VERSION},
        )

    def _upload(self, audio_path: Path) -> Any:
        try:
            return self._client.files.upload(
                file=str(audio_path),
                config={
                    "mime_type": "audio/wav",
                    "display_name": audio_path.name,
                },
            )
        except Exception as exc:  # SDK errors share no useful base here
            raise UploadError(
                f"uploading {audio_path.name} failed: "
                f"{translate_api_error(exc)}"
            ) from exc

    def _wait_until_active(self, uploaded: Any) -> None:
        deadline = time.monotonic() + self.active_timeout
        while True:
            state = _state_name(getattr(uploaded, "state", None))
            if state in {"ACTIVE", "FILE_STATE_ACTIVE"}:
                return
            if state in {"FAILED", "FILE_STATE_FAILED"}:
                raise UploadError(
                    "the uploaded audio was processed but the service marked "
                    "it FAILED; check the file format and size"
                )
            if state in {"", "STATE_UNSPECIFIED"}:
                # Some test doubles do not model file state; treat as ready.
                return
            if time.monotonic() >= deadline:
                raise UploadError(
                    f"the uploaded audio did not become ACTIVE within "
                    f"{self.active_timeout:.0f}s (last state: {state or 'unknown'})"
                )
            self._sleep(2.0)
            uploaded = self._client.files.get(name=uploaded.name)

    def _delete(self, uploaded: Any) -> bool:
        name = getattr(uploaded, "name", None)
        if not name:
            return False
        try:
            self._client.files.delete(name=name)
            return True
        except Exception:
            return False

    def transcribe(
        self,
        audio_path: Path,
        options: TranscribeOptions,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> TranscribeResult:
        """Upload, transcribe, return the raw interaction dump, delete the file."""

        path = Path(audio_path)
        timings: dict[str, float] = {}
        uploaded = None
        try:
            started = time.perf_counter()
            if progress:
                progress(f"uploading {path.name}")
            uploaded = self._upload(path)
            self._wait_until_active(uploaded)
            timings["upload"] = round(time.perf_counter() - started, 3)

            uri = getattr(uploaded, "uri", None)
            if not uri:
                raise UploadError(
                    "the Files API response contains no URI, so the audio "
                    "cannot be referenced by the transcription request"
                )
            mime_type = str(
                getattr(uploaded, "mime_type", None) or "audio/wav"
            )
            body = build_request(uri, mime_type, options)

            started = time.perf_counter()
            if progress:
                progress(f"transcribing with {options.model}")
            try:
                interaction = self._client.interactions.create(
                    timeout=self.timeout, **body
                )
            except TranscribeError:
                raise
            except Exception as exc:
                raise translate_api_error(exc) from exc
            timings["transcribe"] = round(time.perf_counter() - started, 3)

            status = str(getattr(interaction, "status", "") or "").lower()
            raw = interaction_to_mapping(interaction)
            if status and status != "completed":
                errors = raw.get("errors") or []
                raise TranscribeResponseError(
                    f"the transcription interaction finished with status "
                    f"{status!r} instead of 'completed'. Errors: {errors}"
                )

            file_name = getattr(uploaded, "name", None)
            started = time.perf_counter()
            deleted = self._delete(uploaded)
            timings["delete"] = round(time.perf_counter() - started, 3)
            uploaded = None  # the file is gone; nothing left for the finally block

            return TranscribeResult(
                raw=raw,
                interaction_id=getattr(interaction, "id", None),
                uploaded_file=file_name,
                file_deleted=deleted,
                timings=timings,
            )
        finally:
            if uploaded is not None:
                # Never leave a private recording on the service after a failure.
                self._delete(uploaded)


def cloud_call_notice(
    *,
    audio_path: Path,
    size_bytes: int,
    duration_seconds: float | None,
    options: TranscribeOptions,
) -> list[str]:
    """Plain-language privacy and cost notice shown before the upload."""

    minutes = (
        f"{duration_seconds / 60:.1f} min" if duration_seconds else "unknown"
    )
    features = []
    features.append("verbatim mode")
    if options.diarize:
        features.append("speaker diarization")
    if options.word_timestamps:
        features.append("word timestamps")
    return [
        "Gemini Transcribe confirmation",
        f"  Model: {options.model}",
        f"  Uploaded: {audio_path} ({size_bytes:,} bytes, {minutes})",
        "  Uploaded content: the audio waveform only.",
        "  Not uploaded: ground truth, participant names, roles, the turn map,",
        "  the script, or the meeting metadata.",
        f"  Requested: {', '.join(features)}.",
        "  Retention: the uploaded file is deleted right after the run and the",
        f"  interaction is created with store={str(options.store_remote).lower()}.",
        f"  Cost: billed by Google. No price is quoted because it changes; see "
        f"{config.PRICING_URL} and {config.USAGE_URL}.",
        "  Privacy: the controlled fixture is fictional. Do not upload a real",
        "  private recording without permission.",
    ]
