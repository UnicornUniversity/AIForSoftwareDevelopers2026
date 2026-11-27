from __future__ import annotations

from uda.tracing.redaction import sanitize_attributes


def test_deny_by_default_drops_unknown_fields() -> None:
    cleaned = sanitize_attributes({"question": "How many customers?", "model": "deepseek"})
    assert cleaned == {"model": "deepseek"}


def test_allowlisted_metadata_is_kept() -> None:
    cleaned = sanitize_attributes({"node": "demo_validate_sql", "retry_count": 1})
    assert cleaned == {"node": "demo_validate_sql", "retry_count": 1}


def test_max_tokens_is_kept() -> None:
    assert sanitize_attributes({"max_tokens": 1024}) == {"max_tokens": 1024}


def test_numeric_token_counts_are_kept() -> None:
    cleaned = sanitize_attributes(
        {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
    )
    assert cleaned == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


def test_sensitive_keys_are_dropped() -> None:
    cleaned = sanitize_attributes(
        {
            "api_key": "abc",
            "client_secret": "abc",
            "db_password": "abc",
            "access_token": "abc",
            "auth_token": "abc",
            "model": "deepseek",
        }
    )
    assert cleaned == {"model": "deepseek"}


def test_arbitrary_token_usage_nested_dict_is_dropped() -> None:
    cleaned = sanitize_attributes({"token_usage": {"input": 10}, "model": "deepseek"})
    assert cleaned == {"model": "deepseek"}


def test_secret_patterns_are_redacted() -> None:
    cleaned = sanitize_attributes({"result_ref": "sk-abcdefghijklmnop"})
    assert cleaned == {"result_ref": "[REDACTED]"}


def test_obvious_email_in_result_ref_is_redacted() -> None:
    cleaned = sanitize_attributes({"result_ref": "john.doe@example.com"})
    assert cleaned == {"result_ref": "[REDACTED]"}


def test_synthetic_result_ref_survives() -> None:
    cleaned = sanitize_attributes({"result_ref": "order-123"})
    assert cleaned == {"result_ref": "order-123"}


def test_long_values_are_truncated() -> None:
    cleaned = sanitize_attributes({"result_ref": "x" * 600})
    assert cleaned["result_ref"].endswith("[truncated]")
