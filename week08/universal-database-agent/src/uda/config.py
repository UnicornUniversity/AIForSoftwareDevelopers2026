"""Configuration loading with explicit precedence.

Precedence: CLI arguments > environment variables > YAML profile > built-in defaults.
Secrets are accepted only from the environment, never from YAML.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigurationError

_SECRET_KEYS = frozenset(
    {
        "password",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "public_key",
        "token",
        "access_token",
        "connection_string",
        "dsn",
    }
)


class DatabaseConfig(BaseModel):
    """Read-only database settings. Phase 1 does not connect."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=True)

    host: str = "localhost"
    port: int | None = Field(default=1433, ge=1, le=65535)
    name: str = "Northwind"
    username: str = Field(
        default="uda_readonly",
        validation_alias=AliasChoices("username", "user"),
        serialization_alias="username",
    )
    password: str = Field(default="", repr=False)
    driver: str = "ODBC Driver 18 for SQL Server"
    trusted_connection: bool = False
    encrypt: bool = True
    trust_server_certificate: bool = False
    schema_name: str = Field(
        default="dbo",
        validation_alias=AliasChoices("schema", "schema_name"),
        serialization_alias="schema",
    )
    connection_timeout_seconds: int = Field(default=15, gt=0)
    query_timeout_seconds: int = Field(
        default=30,
        gt=0,
        validation_alias=AliasChoices("query_timeout_seconds", "timeout_seconds"),
        serialization_alias="query_timeout_seconds",
    )
    row_limit: int = Field(default=1000, gt=0)

    def validate_connection_settings(self) -> None:
        """Validate authentication settings before a connection is attempted."""

        if self.trusted_connection:
            if self.username or self.password:
                raise ConfigurationError(
                    "Trusted connection requires UDA_DB_USERNAME and UDA_DB_PASSWORD "
                    "to be empty."
                )
        else:
            if not self.username:
                raise ConfigurationError(
                    "UDA_DB_USERNAME is required for SQL Server Authentication."
                )
            if not self.password:
                raise ConfigurationError(
                    "UDA_DB_PASSWORD is required for SQL Server Authentication."
                )


class LLMConfig(BaseModel):
    """Provider, endpoint, model, and generation parameters."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    api_key: str = Field(default="", repr=False)


class LangfuseConfig(BaseModel):
    """Langfuse connection settings. Keys come from the environment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    public_key: str = Field(default="", repr=False)
    secret_key: str = Field(default="", repr=False)
    host: str = "http://localhost:3000"


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tracer: Literal["noop", "langfuse"] = "noop"
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)


class AppConfig(BaseModel):
    """Fully resolved application configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    profile: str = "deepseek"
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    def redacted_dump(self) -> dict[str, Any]:
        """Return configuration as a dict with secret values masked."""

        data = self.model_dump(by_alias=True)
        _mask(data, ("database", "password"))
        _mask(data, ("llm", "api_key"))
        _mask(data, ("observability", "langfuse", "public_key"))
        _mask(data, ("observability", "langfuse", "secret_key"))
        return data


class CliOverrides(BaseModel):
    """Values supplied explicitly on the command line."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    tracer: Literal["noop", "langfuse"] | None = None


def load_env_file(path: Path | None) -> None:
    """Load a .env file without overriding real environment variables."""

    if path is not None and path.exists():
        load_dotenv(dotenv_path=path, override=False)


def load_config(
    profile_path: Path | None = None,
    overrides: CliOverrides | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Resolve configuration in the documented precedence order.

    ``env`` is injectable for tests; by default the process environment is used.
    """

    env_map: Mapping[str, str] = os.environ if env is None else env
    data: dict[str, Any] = AppConfig().model_dump(by_alias=True)

    if profile_path is not None:
        data = _merge(data, _load_profile(profile_path))

    data = _apply_environment(data, env_map)
    data = _apply_overrides(data, overrides)

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(f"Invalid configuration: {details}") from exc


def _load_profile(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"Configuration profile not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Configuration profile is not valid YAML: {path}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"Configuration profile must be a mapping: {path}")
    _reject_secrets(raw)
    return _normalize_profile_aliases(raw)


def _normalize_profile_aliases(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize legacy YAML aliases so base defaults do not collide with them."""

    database = profile.get("database")
    if not isinstance(database, Mapping):
        return profile
    normalized = dict(database)
    for legacy, canonical in (
        ("user", "username"),
        ("timeout_seconds", "query_timeout_seconds"),
        ("schema_name", "schema"),
    ):
        if legacy in normalized:
            value = normalized.pop(legacy)
            normalized.setdefault(canonical, value)
    result = dict(profile)
    result["database"] = normalized
    return result


def _reject_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            location = f"{path}.{key}" if path else str(key)
            if str(key).lower() in _SECRET_KEYS:
                raise ConfigurationError(
                    f"Secret field '{location}' is not allowed in YAML profiles; "
                    "use environment variables (UDA_* or LANGFUSE_*)."
                )
            _reject_secrets(nested, location)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secrets(nested, f"{path}[{index}]")


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _assign(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = data
    for part in path[:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    target[path[-1]] = value


def _apply_environment(data: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    text_vars = {
        "UDA_DB_HOST": ("database", "host"),
        "UDA_DB_NAME": ("database", "name"),
        "UDA_DB_USER": ("database", "username"),
        "UDA_DB_USERNAME": ("database", "username"),
        "UDA_DB_PASSWORD": ("database", "password"),
        "UDA_DB_DRIVER": ("database", "driver"),
        "UDA_DB_SCHEMA": ("database", "schema"),
        "UDA_LLM_PROVIDER": ("llm", "provider"),
        "UDA_LLM_BASE_URL": ("llm", "base_url"),
        "UDA_LLM_MODEL": ("llm", "model"),
        "UDA_LLM_API_KEY": ("llm", "api_key"),
        "UDA_TRACER": ("observability", "tracer"),
        "LANGFUSE_PUBLIC_KEY": ("observability", "langfuse", "public_key"),
        "LANGFUSE_SECRET_KEY": ("observability", "langfuse", "secret_key"),
        "LANGFUSE_HOST": ("observability", "langfuse", "host"),
    }
    for name, path in text_vars.items():
        if name in env:
            _assign(data, path, env[name])

    if "UDA_DB_PORT" in env:
        raw_port = env["UDA_DB_PORT"].strip()
        _assign(
            data,
            ("database", "port"),
            _to_int("UDA_DB_PORT", raw_port) if raw_port else None,
        )

    int_vars = {
        "UDA_DB_TIMEOUT_SECONDS": ("database", "query_timeout_seconds"),
        "UDA_DB_QUERY_TIMEOUT": ("database", "query_timeout_seconds"),
        "UDA_DB_CONNECTION_TIMEOUT": ("database", "connection_timeout_seconds"),
        "UDA_DB_ROW_LIMIT": ("database", "row_limit"),
        "UDA_LLM_MAX_TOKENS": ("llm", "max_tokens"),
    }
    for name, path in int_vars.items():
        if name in env:
            _assign(data, path, _to_int(name, env[name]))

    bool_vars = {
        "UDA_DB_TRUSTED_CONNECTION": ("database", "trusted_connection"),
        "UDA_DB_ENCRYPT": ("database", "encrypt"),
        "UDA_DB_TRUST_SERVER_CERTIFICATE": ("database", "trust_server_certificate"),
    }
    for name, path in bool_vars.items():
        if name in env:
            _assign(data, path, _to_bool(name, env[name]))

    if "UDA_LLM_TEMPERATURE" in env:
        _assign(
            data,
            ("llm", "temperature"),
            _to_float("UDA_LLM_TEMPERATURE", env["UDA_LLM_TEMPERATURE"]),
        )
    if "UDA_LLM_TIMEOUT" in env:
        _assign(
            data,
            ("llm", "timeout_seconds"),
            _to_float("UDA_LLM_TIMEOUT", env["UDA_LLM_TIMEOUT"]),
        )

    return data


def _apply_overrides(data: dict[str, Any], overrides: CliOverrides | None) -> dict[str, Any]:
    if overrides is None:
        return data
    if overrides.provider is not None:
        _assign(data, ("llm", "provider"), overrides.provider)
    if overrides.base_url is not None:
        _assign(data, ("llm", "base_url"), overrides.base_url)
    if overrides.model is not None:
        _assign(data, ("llm", "model"), overrides.model)
    if overrides.tracer is not None:
        _assign(data, ("observability", "tracer"), overrides.tracer)
    return data


def _to_int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc


def _to_float(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc


def _to_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean (true/false).")


def _mask(data: dict[str, Any], path: tuple[str, ...]) -> None:
    target: Any = data
    for part in path[:-1]:
        if not isinstance(target, dict) or part not in target:
            return
        target = target[part]
    if isinstance(target, dict) and target.get(path[-1]):
        target[path[-1]] = "***"
