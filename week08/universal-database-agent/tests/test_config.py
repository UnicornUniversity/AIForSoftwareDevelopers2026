from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from uda.config import CliOverrides, load_config, load_env_file
from uda.errors import ConfigurationError


def write_profile(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_are_used_without_a_profile() -> None:
    config = load_config(env={})
    assert config.profile == "deepseek"
    assert config.llm.provider == "deepseek"
    assert config.llm.model == "deepseek-chat"
    assert config.observability.tracer == "noop"


def test_yaml_profile_overrides_defaults(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "profile: test\nllm:\n  model: profile-model\n")
    config = load_config(path, env={})
    assert config.profile == "test"
    assert config.llm.model == "profile-model"


def test_environment_overrides_yaml(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "llm:\n  model: profile-model\n")
    config = load_config(path, env={"UDA_LLM_MODEL": "env-model"})
    assert config.llm.model == "env-model"


def test_cli_overrides_environment(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "llm:\n  model: profile-model\n")
    config = load_config(
        path,
        overrides=CliOverrides(model="cli-model"),
        env={"UDA_LLM_MODEL": "env-model"},
    )
    assert config.llm.model == "cli-model"


def test_secret_in_yaml_is_rejected(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "llm:\n  api_key: should-not-be-here\n")
    with pytest.raises(ConfigurationError, match="not allowed in YAML"):
        load_config(path, env={})


def test_invalid_environment_number_is_reported_without_secret(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "profile: test\n")
    with pytest.raises(ConfigurationError) as excinfo:
        load_config(
            path,
            env={"UDA_DB_PORT": "not-a-number", "UDA_DB_PASSWORD": "supersecret"},
        )
    message = str(excinfo.value)
    assert "UDA_DB_PORT" in message
    assert "supersecret" not in message


def test_invalid_temperature_is_rejected(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "llm:\n  temperature: 5.0\n")
    with pytest.raises(ConfigurationError, match="temperature"):
        load_config(path, env={})


def test_redacted_dump_masks_secrets(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "profile: test\n")
    config = load_config(
        path,
        env={
            "UDA_DB_PASSWORD": "db-secret",
            "UDA_LLM_API_KEY": "llm-secret",
            "LANGFUSE_SECRET_KEY": "lf-secret",
        },
    )
    dumped = config.redacted_dump()
    assert dumped["database"]["password"] == "***"
    assert dumped["llm"]["api_key"] == "***"
    assert dumped["observability"]["langfuse"]["secret_key"] == "***"


def test_missing_profile_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path / "missing.yaml", env={})


def test_dotenv_loading_and_missing_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("UDA_LLM_MODEL=dotenv-model\n", encoding="utf-8")
    with patch.dict(os.environ, {}, clear=True):
        load_env_file(tmp_path / "missing.env")
        load_env_file(env_file)
        assert os.environ["UDA_LLM_MODEL"] == "dotenv-model"
        config = load_config(env=None)
        assert config.llm.model == "dotenv-model"


def test_real_environment_wins_over_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("UDA_LLM_MODEL=dotenv-model\n", encoding="utf-8")
    with patch.dict(os.environ, {"UDA_LLM_MODEL": "real-model"}, clear=True):
        load_env_file(env_file)
        assert os.environ["UDA_LLM_MODEL"] == "real-model"


def test_malformed_yaml_is_an_error(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "llm: [unclosed\n")
    with pytest.raises(ConfigurationError, match="not valid YAML"):
        load_config(path, env={})


def test_non_model_field_precedence(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "database:\n  schema: profile_schema\n")
    config = load_config(path, env={"UDA_DB_SCHEMA": "env_schema"})
    assert config.database.schema_name == "env_schema"
    assert load_config(env={}).database.schema_name == "dbo"


def test_secret_does_not_appear_in_displayed_configuration(tmp_path: Path) -> None:
    path = write_profile(tmp_path, "profile: test\n")
    config = load_config(
        path,
        env={
            "UDA_DB_PASSWORD": "display-secret",
            "UDA_LLM_API_KEY": "display-key",
        },
    )
    displayed = str(config.redacted_dump())
    assert "display-secret" not in displayed
    assert "display-key" not in displayed


def test_database_connection_environment_settings() -> None:
    config = load_config(
        env={
            "UDA_DB_USERNAME": "reader",
            "UDA_DB_PASSWORD": "secret",
            "UDA_DB_TRUSTED_CONNECTION": "false",
            "UDA_DB_ENCRYPT": "true",
            "UDA_DB_TRUST_SERVER_CERTIFICATE": "true",
            "UDA_DB_CONNECTION_TIMEOUT": "7",
            "UDA_DB_QUERY_TIMEOUT": "9",
        }
    )
    assert config.database.username == "reader"
    assert config.database.trusted_connection is False
    assert config.database.encrypt is True
    assert config.database.trust_server_certificate is True
    assert config.database.connection_timeout_seconds == 7
    assert config.database.query_timeout_seconds == 9


def test_legacy_database_environment_aliases() -> None:
    config = load_config(
        env={
            "UDA_DB_USER": "legacy-reader",
            "UDA_DB_TIMEOUT_SECONDS": "11",
        }
    )
    assert config.database.username == "legacy-reader"
    assert config.database.query_timeout_seconds == 11
    preferred = load_config(
        env={
            "UDA_DB_USER": "legacy-reader",
            "UDA_DB_USERNAME": "preferred-reader",
            "UDA_DB_TIMEOUT_SECONDS": "11",
            "UDA_DB_QUERY_TIMEOUT": "12",
        }
    )
    assert preferred.database.username == "preferred-reader"
    assert preferred.database.query_timeout_seconds == 12


def test_empty_port_selects_named_instance() -> None:
    assert load_config(env={"UDA_DB_PORT": ""}).database.port is None


def test_invalid_boolean_environment_value_is_an_error() -> None:
    with pytest.raises(ConfigurationError, match="UDA_DB_ENCRYPT"):
        load_config(env={"UDA_DB_ENCRYPT": "sometimes"})


def test_connection_auth_validation() -> None:
    with pytest.raises(ConfigurationError, match="UDA_DB_PASSWORD"):
        load_config(env={"UDA_DB_PASSWORD": ""}).database.validate_connection_settings()

    trusted_with_credentials = load_config(
        env={"UDA_DB_TRUSTED_CONNECTION": "true"}
    ).database
    with pytest.raises(ConfigurationError, match="Trusted connection"):
        trusted_with_credentials.validate_connection_settings()

    trusted = load_config(
        env={
            "UDA_DB_TRUSTED_CONNECTION": "true",
            "UDA_DB_USERNAME": "",
            "UDA_DB_PASSWORD": "",
        }
    ).database
    trusted.validate_connection_settings()
