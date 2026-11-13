from __future__ import annotations

from pathlib import Path

import pytest

from src import config
from src.asr.gemini.client import (
    APIKeyRejectedError,
    GeminiTranscribeClient,
    MissingAPIKeyError,
    ModelAccessError,
    QuotaError,
    TranscribeAPIError,
    TranscribeResponseError,
    UploadError,
    translate_api_error,
)
from src.asr.gemini.request import TranscribeOptions
from tests.asr.gemini.fakes import FakeInteraction, FakeSDK, FakeUploadedFile
from tests.conftest import write_wav

pytest.importorskip("google.genai.errors")


def _api_error(code: int, message: str = "boom"):
    from google.genai.errors import APIError

    return APIError(code, {"error": {"code": code, "message": message}})


def test_missing_api_key_raises_a_clear_error(monkeypatch) -> None:
    monkeypatch.delenv(config.GEMINI_API_KEY_ENV, raising=False)
    monkeypatch.delenv(config.GOOGLE_API_KEY_ENV, raising=False)
    with pytest.raises(MissingAPIKeyError) as excinfo:
        GeminiTranscribeClient()
    assert config.GEMINI_API_KEY_ENV in str(excinfo.value)


def test_transcribe_uploads_transcribes_and_deletes(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.2)
    interaction = FakeInteraction(
        output_text="Hello.",
        steps=[
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "Hello.",
                        "annotations": [
                            {
                                "type": "word_info",
                                "text": "Hello.",
                                "speaker": "spk_1",
                                "start_offset": "0.100s",
                                "end_offset": "0.400s",
                            }
                        ],
                    }
                ],
            }
        ],
    )
    sdk = FakeSDK(interaction=interaction)
    client = GeminiTranscribeClient(client=sdk, timeout=30)

    result = client.transcribe(audio, TranscribeOptions())

    assert sdk.files.upload_calls
    assert sdk.files.upload_calls[0]["config"]["mime_type"] == "audio/wav"
    body = sdk.interactions.bodies[0]
    assert body["model"] == config.TRANSCRIBE_MODEL
    assert body["input"][0]["uri"].startswith("https://")
    assert body["store"] is False
    assert body["timeout"] == 30
    assert sdk.files.deleted == [sdk.files.file.name]
    assert result.file_deleted is True
    assert result.uploaded_file == sdk.files.file.name
    assert result.raw["output_text"] == "Hello."
    assert set(result.timings) >= {"upload", "transcribe", "delete"}


def test_waiting_for_processing_state_polls_until_active(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    uploaded = FakeUploadedFile(state="PROCESSING")
    sdk = FakeSDK(uploaded=uploaded)
    sdk.files.states = ["ACTIVE"]
    client = GeminiTranscribeClient(
        client=sdk, sleep=lambda _seconds: None
    )

    client.transcribe(audio, TranscribeOptions())

    assert sdk.files.get_calls == [uploaded.name]


def test_failed_file_upload_is_reported(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    sdk = FakeSDK(uploaded=FakeUploadedFile(state="FAILED"))
    client = GeminiTranscribeClient(client=sdk)

    with pytest.raises(UploadError) as excinfo:
        client.transcribe(audio, TranscribeOptions())
    assert "FAILED" in str(excinfo.value)
    assert sdk.interactions.bodies == []


def test_delete_is_attempted_even_when_transcription_fails(
    tmp_path: Path,
) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    sdk = FakeSDK()
    sdk.interactions.error = _api_error(500, "server exploded")
    client = GeminiTranscribeClient(client=sdk)

    with pytest.raises(Exception):
        client.transcribe(audio, TranscribeOptions())
    assert sdk.files.deleted == [sdk.files.file.name]


def test_delete_failure_is_recorded_not_hidden(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    sdk = FakeSDK()
    sdk.files.fail_delete = True
    client = GeminiTranscribeClient(client=sdk)

    result = client.transcribe(audio, TranscribeOptions())

    assert result.file_deleted is False


def test_non_completed_status_is_a_response_error(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    sdk = FakeSDK(interaction=FakeInteraction(status="failed"))
    client = GeminiTranscribeClient(client=sdk)

    with pytest.raises(TranscribeResponseError) as excinfo:
        client.transcribe(audio, TranscribeOptions())
    assert "failed" in str(excinfo.value)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, APIKeyRejectedError),
        (403, ModelAccessError),
        (404, ModelAccessError),
        (429, QuotaError),
        (400, TranscribeAPIError),
        (500, TranscribeAPIError),
    ],
)
def test_api_errors_are_translated(code, expected) -> None:
    error = translate_api_error(_api_error(code, "service detail"))
    assert isinstance(error, expected)
    assert "service detail" in str(error)


def test_key_is_never_in_a_translated_error() -> None:
    error = translate_api_error(_api_error(400, "bad request"))
    assert "hf_" not in str(error)
