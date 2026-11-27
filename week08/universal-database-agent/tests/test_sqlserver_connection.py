from __future__ import annotations

import pytest

from uda.adapters.sqlserver import build_connection_url, ensure_driver_available
from uda.config import DatabaseConfig
from uda.errors import AdapterConfigurationError, ConfigurationError


def sql_auth_config() -> DatabaseConfig:
    return DatabaseConfig(
        host="db.example",
        port=1433,
        name="Northwind",
        username="reader",
        password="super-secret",
        trusted_connection=False,
        encrypt=True,
        trust_server_certificate=False,
    )


def test_sql_auth_url_and_masked_password() -> None:
    url = build_connection_url(sql_auth_config())
    assert url.drivername == "mssql+pyodbc"
    assert url.username == "reader"
    assert url.password == "super-secret"
    assert url.query["Encrypt"] == "yes"
    assert url.query["TrustServerCertificate"] == "no"
    rendered = url.render_as_string(hide_password=True)
    assert "super-secret" not in rendered
    assert "***" in rendered


def test_trusted_connection_has_no_credentials() -> None:
    config = DatabaseConfig(
        username="",
        password="",
        trusted_connection=True,
        encrypt=True,
        trust_server_certificate=True,
    )
    url = build_connection_url(config)
    assert url.username is None
    assert url.password is None
    assert url.query["Trusted_Connection"] == "yes"
    assert url.query["Encrypt"] == "yes"
    assert url.query["TrustServerCertificate"] == "yes"
    assert "super-secret" not in url.render_as_string(hide_password=True)


def test_trusted_connection_rejects_credentials() -> None:
    config = DatabaseConfig(
        username="reader",
        password="secret",
        trusted_connection=True,
    )
    with pytest.raises(ConfigurationError, match="Trusted connection"):
        build_connection_url(config)


def test_sql_auth_requires_username_and_password() -> None:
    with pytest.raises(ConfigurationError, match="UDA_DB_USERNAME"):
        build_connection_url(DatabaseConfig(username="", password="secret"))
    with pytest.raises(ConfigurationError, match="UDA_DB_PASSWORD"):
        build_connection_url(DatabaseConfig(username="reader", password=""))


def test_driver_check_accepts_installed_driver() -> None:
    ensure_driver_available("ODBC Driver 18 for SQL Server", ["ODBC Driver 18 for SQL Server"])


def test_driver_check_reports_missing_driver() -> None:
    with pytest.raises(AdapterConfigurationError, match="not installed"):
        ensure_driver_available("ODBC Driver 18 for SQL Server", ["SQL Server"])
