from __future__ import annotations

import pytest

from src import config
from src.asr.gemini.request import (
    TranscribeOptions,
    TranscribeRequestError,
    build_request,
    build_transcription_config,
)


def _body(**overrides):
    options = TranscribeOptions(**overrides)
    return build_request("files/fake-123", "audio/wav", options)


def test_default_request_uses_verbatim_diarization_and_word_timestamps() -> None:
    body = _body()

    assert body["model"] == config.TRANSCRIBE_MODEL
    assert body["store"] is False
    assert body["input"] == [
        {
            "type": "audio",
            "uri": "files/fake-123",
            "mime_type": "audio/wav",
        }
    ]
    mode = body["generation_config"]["transcription_config"]["mode"]
    assert mode["type"] == "verbatim"
    assert mode["diarization_mode"] == "speaker"
    assert mode["timestamp_granularities"] == ["word"]
    assert (
        body["generation_config"]["transcription_config"]["language_codes"]
        == ["en-US"]
    )


def test_no_diarization_and_no_timestamps_leave_plain_verbatim() -> None:
    body = _body(diarize=False, word_timestamps=False)
    mode = body["generation_config"]["transcription_config"]["mode"]
    assert mode == {"type": "verbatim"}


def test_empty_language_codes_means_automatic_detection() -> None:
    body = _body(language_codes=())
    config_body = body["generation_config"]["transcription_config"]
    assert "language_codes" not in config_body


def test_custom_vocabulary_alone_is_allowed_for_a_labelled_experiment() -> None:
    options = TranscribeOptions(
        diarize=False,
        word_timestamps=False,
        custom_vocabulary=("Brightline", "Atlas"),
    )
    config_body = build_transcription_config(options)
    assert config_body["custom_vocabulary"] == ["Brightline", "Atlas"]


def test_custom_vocabulary_with_diarization_is_refused() -> None:
    with pytest.raises(TranscribeRequestError) as excinfo:
        _body(custom_vocabulary=("Atlas",))
    assert "cannot be combined" in str(excinfo.value)


def test_custom_vocabulary_with_timestamps_is_refused() -> None:
    with pytest.raises(TranscribeRequestError) as excinfo:
        _body(diarize=False, custom_vocabulary=("Atlas",))
    assert "cannot be combined" in str(excinfo.value)


def test_unsupported_mime_type_is_refused() -> None:
    with pytest.raises(TranscribeRequestError) as excinfo:
        build_request(
            "files/fake-123", "video/mp4", TranscribeOptions()
        )
    assert "unsupported audio MIME type" in str(excinfo.value)


def test_missing_uri_is_refused() -> None:
    with pytest.raises(TranscribeRequestError):
        build_request("", "audio/wav", TranscribeOptions())


def test_empty_custom_vocabulary_term_is_refused() -> None:
    with pytest.raises(TranscribeRequestError):
        _body(
            diarize=False,
            word_timestamps=False,
            custom_vocabulary=("Atlas", "  "),
        )
