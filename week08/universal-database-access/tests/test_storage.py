import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from uda.fixtures import load_demo_schema
from uda.models import AttributeMapping, Candidate, ConceptProposal
from uda.storage import CandidateStorageError, save_candidate

SCHEMA_VERSION = "sha256:" + "0" * 64
CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000001")
CREATED_AT = datetime(2026, 11, 20, 10, 0, 0, tzinfo=UTC)


def _candidate(physical_table: str = "dbo.Customer") -> Candidate:
    return Candidate(
        candidate_id=CANDIDATE_ID,
        created_at=CREATED_AT,
        source_table=physical_table,
        schema_version=SCHEMA_VERSION,
        concept=ConceptProposal(
            concept_name="Customer",
            description="A person who buys from the store.",
            attributes=(
                AttributeMapping(
                    attribute="identifier",
                    column_names=["customer_id"],
                ),
            ),
        ),
    )


def test_save_creates_parents_and_writes_pending_json(tmp_path) -> None:
    target = tmp_path / "nested" / "candidate.json"

    saved = save_candidate(target, load_demo_schema(), _candidate())

    assert saved == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == str(CANDIDATE_ID)
    assert payload["created_at"].startswith("2026-11-20T10:00:00")
    assert payload["source_table"] == "dbo.Customer"
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "pending_review"
    assert payload["concept"]["attributes"][0]["column_names"] == [
        "customer_id"
    ]
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_save_is_deterministic(tmp_path) -> None:
    schema = load_demo_schema()
    candidate = _candidate()
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    save_candidate(first, schema, candidate)
    save_candidate(second, schema, candidate)

    assert first.read_bytes() == second.read_bytes()


def test_invalid_candidate_is_refused_without_writing(tmp_path) -> None:
    target = tmp_path / "candidate.json"

    with pytest.raises(CandidateStorageError, match="table_mismatch"):
        save_candidate(target, load_demo_schema(), _candidate("dbo.Other"))

    assert not target.exists()


def test_existing_candidate_is_not_overwritten(tmp_path) -> None:
    target = tmp_path / "candidate.json"
    schema = load_demo_schema()
    candidate = _candidate()
    save_candidate(target, schema, candidate)
    original = target.read_bytes()

    with pytest.raises(CandidateStorageError, match="already exists"):
        save_candidate(target, schema, candidate)

    assert target.read_bytes() == original
