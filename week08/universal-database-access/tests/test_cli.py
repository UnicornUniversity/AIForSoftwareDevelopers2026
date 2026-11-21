import json
from pathlib import Path

from uda.cli import EXIT_ERROR, EXIT_OK, EXIT_REJECTED, main


def _write_response(tmp_path: Path, payload: str) -> Path:
    path = tmp_path / "response.txt"
    path.write_text(payload, encoding="utf-8")
    return path


def _valid_response() -> str:
    return json.dumps(
        {
            "concept_name": "Customer",
            "description": "A person who buys from the store.",
            "attributes": [
                {
                    "attribute": "identifier",
                    "description": "The customer's unique identifier.",
                    "column": "customer_id",
                },
                {
                    "attribute": "name",
                    "description": "The customer's full name.",
                    "column": "full_name",
                },
            ],
        }
    )


def test_cli_writes_candidate_offline(tmp_path, capsys) -> None:
    response = _write_response(tmp_path, _valid_response())
    out = tmp_path / "out" / "candidate.json"

    code = main(["propose", "--response-file", str(response), "--out", str(out)])

    assert code == EXIT_OK
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "pending_review"
    assert payload["candidate_id"]
    assert payload["created_at"]
    assert payload["source_table"] == "dbo.Customer"
    assert payload["schema_version"].startswith("sha256:")
    assert payload["concept"]["attributes"][0]["column_names"] == [
        "customer_id"
    ]
    assert "wrote" in capsys.readouterr().out


def test_cli_returns_rejected_for_unknown_column(tmp_path, capsys) -> None:
    response = _write_response(
        tmp_path,
        json.dumps(
            {
                "concept_name": "Customer",
                "description": "A person.",
                "attributes": [
                    {
                        "attribute": "identifier",
                        "description": "The customer's unique identifier.",
                        "column": "customer_key",
                    }
                ],
            }
        ),
    )
    out = tmp_path / "candidate.json"

    code = main(["propose", "--response-file", str(response), "--out", str(out)])

    assert code == EXIT_REJECTED
    assert not out.exists()
    assert "unknown_column" in capsys.readouterr().err


def test_cli_returns_error_for_malformed_response(tmp_path, capsys) -> None:
    response = _write_response(tmp_path, "not json")
    out = tmp_path / "candidate.json"

    code = main(["propose", "--response-file", str(response), "--out", str(out)])

    assert code == EXIT_ERROR
    assert not out.exists()
    assert "not a valid proposal" in capsys.readouterr().err


def test_cli_returns_error_for_unreadable_response_file(tmp_path, capsys) -> None:
    missing = tmp_path / "missing.txt"
    out = tmp_path / "candidate.json"

    code = main(["propose", "--response-file", str(missing), "--out", str(out)])

    assert code == EXIT_ERROR
    assert not out.exists()
    assert "cannot read response file" in capsys.readouterr().err


def test_cli_requires_provider_key_without_response_file(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    out = tmp_path / "candidate.json"

    code = main(["propose", "--out", str(out)])

    assert code == EXIT_ERROR
    assert not out.exists()
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().err


def test_cli_requires_db_settings_for_sqlserver_source(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("UDA_DB_SERVER", raising=False)
    response = _write_response(tmp_path, _valid_response())
    out = tmp_path / "candidate.json"

    code = main(
        [
            "propose",
            "--response-file",
            str(response),
            "--sqlserver",
            "dbo.Customer",
            "--out",
            str(out),
        ]
    )

    assert code == EXIT_ERROR
    assert not out.exists()
    assert "UDA_DB_SERVER" in capsys.readouterr().err


def test_cli_rejects_invalid_table_reference(tmp_path, capsys) -> None:
    response = _write_response(tmp_path, _valid_response())
    out = tmp_path / "candidate.json"

    code = main(
        [
            "propose",
            "--response-file",
            str(response),
            "--sqlserver",
            ".Customer",
            "--out",
            str(out),
        ]
    )

    assert code == EXIT_ERROR
    assert not out.exists()
    assert "invalid table reference" in capsys.readouterr().err
