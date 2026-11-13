from __future__ import annotations

import os
from pathlib import Path

import pytest

from src import config
from src.asr.tokens import (
    MissingHFTokenError,
    load_environment,
    load_hf_token,
    missing_token_message,
    require_hf_token,
)


def test_missing_token_returns_none(monkeypatch) -> None:
    monkeypatch.delenv(config.HF_TOKEN_ENV, raising=False)
    assert load_hf_token() is None


def test_blank_token_is_treated_as_missing() -> None:
    assert load_hf_token({config.HF_TOKEN_ENV: "   "}) is None


def test_token_is_read_from_the_environment_only(monkeypatch) -> None:
    monkeypatch.setenv(config.HF_TOKEN_ENV, "hf_test_value")
    assert load_hf_token() == "hf_test_value"
    assert require_hf_token() == "hf_test_value"


def test_require_token_raises_with_setup_steps(monkeypatch) -> None:
    monkeypatch.delenv(config.HF_TOKEN_ENV, raising=False)
    with pytest.raises(MissingHFTokenError) as excinfo:
        require_hf_token()
    message = str(excinfo.value)
    assert config.HF_TOKEN_ENV in message
    assert "huggingface.co" in message
    assert "speaker-diarization-community-1" in message
    assert "hf_test_value" not in message


def test_message_never_contains_a_secret() -> None:
    message = missing_token_message()
    assert "hf_" not in message
    assert "HF_TOKEN=" in message


def test_load_environment_reads_a_dotenv_file(
    tmp_path: Path, monkeypatch
) -> None:
    name = "TEXT_VOICE_TEXT_TEST_TOKEN"
    monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{name}=hf_from_file\n", encoding="utf-8")
    try:
        load_environment(env_file)
        assert os.environ[name] == "hf_from_file"
    finally:
        os.environ.pop(name, None)


def test_load_environment_does_not_override_the_process_environment(
    tmp_path: Path, monkeypatch
) -> None:
    name = "TEXT_VOICE_TEXT_TEST_TOKEN_WINS"
    monkeypatch.setenv(name, "from_process")
    env_file = tmp_path / ".env"
    env_file.write_text(f"{name}=from_file\n", encoding="utf-8")

    load_environment(env_file)

    assert os.environ[name] == "from_process"
