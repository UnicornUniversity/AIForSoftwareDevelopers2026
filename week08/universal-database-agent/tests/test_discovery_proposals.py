from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from _discovery_fixtures import (
    FIXED_TIME,
    load_evidence,
    proposal_writer,
    valid_output,
    write_repository,
)

from uda.discovery.models import ProposalBatch
from uda.discovery.proposals import (
    ProposalRepositoryWriter,
    validate_proposal_repository,
)
from uda.discovery.validation import build_proposals
from uda.errors import ProposalRepositoryWriteError, ProposalValidationError


def _write_args(evidence: object) -> dict[str, object]:
    return {
        "ddl_repository": str(evidence.root),  # type: ignore[attr-defined]
        "snapshot_id": evidence.snapshot_id,  # type: ignore[attr-defined]
        "prompt_version": "2",
        "prompt_sha256": "a" * 64,
        "provider": "fake",
        "model": "fixture",
        "temperature": 0.0,
        "max_tokens": 1024,
    }


def test_writes_valid_proposals_and_manifest(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    before = {
        path.relative_to(ddl_root).as_posix(): path.read_bytes()
        for path in ddl_root.rglob("*")
        if path.is_file()
    }
    evidence = load_evidence(ddl_root)
    batch = build_proposals(valid_output(), evidence)
    props = tmp_path / "proposals"
    result = proposal_writer(props).write(batch, **_write_args(evidence))
    assert result.status == "completed"
    assert result.counts == {"concepts": 3, "mappings": 7, "relationships": 1}
    assert len(result.written) == 11
    assert (props / "manifest.json").is_file()
    for path in props.rglob("*.yaml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["status"] == "proposed"
        assert payload["generation"]["provider"] == "fake"
        assert payload["generation"]["model"] == "fixture"
        assert payload["generation"]["prompt_version"] == "2"
    relationship_files = list((props / "relationships").glob("*.yaml"))
    assert len(relationship_files) == 1
    relationship = yaml.safe_load(
        relationship_files[0].read_text(encoding="utf-8")
    )
    assert relationship["kind"] == "relationship"
    assert relationship["relationship_type"] == "places"
    assert relationship["status"] == "proposed"
    after = {
        path.relative_to(ddl_root).as_posix(): path.read_bytes()
        for path in ddl_root.rglob("*")
        if path.is_file()
    }
    assert before == after
    manifest = json.loads((props / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["repository"] == "proposals"
    assert manifest["counts"] == {
        "concepts": 3,
        "mappings": 7,
        "relationships": 1,
    }
    assert manifest["last_run"]["status"] == "completed"
    validation = validate_proposal_repository(props, ddl_repository=ddl_root)
    assert validation.valid is True, validation.errors
    assert validation.counts == result.counts


def test_second_write_is_idempotent(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    batch = build_proposals(valid_output(), evidence)
    props = tmp_path / "proposals"
    writer = proposal_writer(props)
    writer.write(batch, **_write_args(evidence))
    before = {
        path.relative_to(props).as_posix(): path.read_bytes()
        for path in props.rglob("*.yaml")
    }
    second = writer.write(batch, **_write_args(evidence))
    after = {
        path.relative_to(props).as_posix(): path.read_bytes()
        for path in props.rglob("*.yaml")
    }
    assert second.status == "completed"
    assert second.written == ()
    assert before == after


def test_conflict_never_overwrites_an_existing_record(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    batch = build_proposals(valid_output(), evidence)
    props = tmp_path / "proposals"
    writer = proposal_writer(props)
    writer.write(batch, **_write_args(evidence))
    concept_path = props / "concepts" / "customer.yaml"
    original = concept_path.read_bytes()
    changed_concept = batch.concepts[0].model_copy(
        update={"definition": "A changed definition."}
    )
    changed_batch = batch.model_copy(
        update={"concepts": (changed_concept, *batch.concepts[1:])}
    )
    result = writer.write(changed_batch, **_write_args(evidence))
    assert result.status == "conflicts"
    assert result.conflicts == ("customer",)
    assert concept_path.read_bytes() == original
    manifest = json.loads((props / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["last_run"]["status"] == "conflicts"


def test_invalid_batch_writes_nothing(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    batch = build_proposals(valid_output(), evidence)
    mapping = batch.mappings[0]
    bad_mapping = mapping.model_copy(update={"semantic_id": "missing"})
    bad_batch = batch.model_copy(update={"mappings": (bad_mapping,)})
    props = tmp_path / "proposals"
    with pytest.raises(ProposalValidationError):
        proposal_writer(props).write(bad_batch, **_write_args(evidence))
    assert not props.exists()


def test_empty_batch_is_a_no_proposal_result(tmp_path: Path) -> None:
    props = tmp_path / "proposals"
    result = proposal_writer(props).write(
        ProposalBatch(),
        ddl_repository="data/knowledge/ddl",
        snapshot_id="sha256:empty",
        prompt_version="2",
        prompt_sha256="a" * 64,
        provider="fake",
        model="fixture",
        temperature=0.0,
        max_tokens=1024,
    )
    assert result.status == "no_proposals"
    assert result.written == ()
    assert not props.exists()


@pytest.mark.parametrize(
    "relative",
    ("data/knowledge/semantics", "data/knowledge/ddl", ""),
)
def test_writer_refuses_paths_outside_the_proposals_area(
    tmp_path: Path, relative: str
) -> None:
    project = tmp_path / "project"
    target = project / relative if relative else project
    target.mkdir(parents=True)
    writer = ProposalRepositoryWriter(
        target,
        project_root=project,
        clock=lambda: FIXED_TIME,
        run_id_factory=lambda: "run-guard",
    )
    with pytest.raises(ProposalRepositoryWriteError):
        writer.write(
            ProposalBatch(),
            ddl_repository="data/knowledge/ddl",
            snapshot_id="sha256:guard",
            prompt_version="2",
            prompt_sha256="a" * 64,
            provider="fake",
            model="fixture",
            temperature=0.0,
            max_tokens=1024,
        )


def test_validate_detects_tampering_and_missing_manifest(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    props = tmp_path / "proposals"
    writer = proposal_writer(props)
    writer.write(
        build_proposals(valid_output(), evidence), **_write_args(evidence)
    )
    concept_path = props / "concepts" / "customer.yaml"
    concept_path.write_text(
        concept_path.read_text(encoding="utf-8") + "\n# tampered\n",
        encoding="utf-8",
    )
    tampered = validate_proposal_repository(props)
    assert tampered.valid is False
    assert any("hash mismatch" in error for error in tampered.errors)

    (props / "manifest.json").unlink()
    missing = validate_proposal_repository(props)
    assert missing.valid is False
    assert any("manifest is missing" in error for error in missing.errors)


def test_validate_requires_per_record_generation_metadata(
    tmp_path: Path,
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    props = tmp_path / "proposals"
    proposal_writer(props).write(
        build_proposals(valid_output(), evidence), **_write_args(evidence)
    )
    concept_path = props / "concepts" / "customer.yaml"
    payload = yaml.safe_load(concept_path.read_text(encoding="utf-8"))
    payload.pop("generation")
    concept_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    validation = validate_proposal_repository(props)
    assert validation.valid is False
    assert any(
        "missing generation metadata" in error for error in validation.errors
    )


def test_validate_rejects_unexpected_files_and_status(tmp_path: Path) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    props = tmp_path / "proposals"
    writer = proposal_writer(props)
    writer.write(
        build_proposals(valid_output(), evidence), **_write_args(evidence)
    )
    (props / "concepts" / "notes.txt").write_text("unexpected", encoding="utf-8")
    unexpected = validate_proposal_repository(props)
    assert unexpected.valid is False
    assert any("Unexpected file" in error for error in unexpected.errors)

    (props / "concepts" / "notes.txt").unlink()
    concept_path = props / "concepts" / "customer.yaml"
    payload = yaml.safe_load(concept_path.read_text(encoding="utf-8"))
    payload["status"] = "approved"
    concept_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    approved = validate_proposal_repository(props)
    assert approved.valid is False


def test_validate_cross_checks_source_references_against_ddl(
    tmp_path: Path,
) -> None:
    ddl_root = tmp_path / "ddl"
    write_repository(ddl_root)
    evidence = load_evidence(ddl_root)
    batch = build_proposals(valid_output(), evidence)
    props = tmp_path / "proposals"
    writer = proposal_writer(props)
    writer.write(batch, **_write_args(evidence))
    assert validate_proposal_repository(props, ddl_repository=ddl_root).valid

    concept = batch.concepts[0]
    broken_reference = concept.source_references[0].model_copy(
        update={"physical_id": "sqlserver/Northwind/dbo/table/Missing"}
    )
    broken_concept = concept.model_copy(
        update={
            "source_references": (
                broken_reference,
                *concept.source_references[1:],
            )
        }
    )
    broken_batch = batch.model_copy(
        update={"concepts": (broken_concept, *batch.concepts[1:])}
    )
    broken_props = tmp_path / "broken-proposals"
    proposal_writer(broken_props).write(
        broken_batch, **_write_args(evidence)
    )
    internal = validate_proposal_repository(broken_props)
    assert internal.valid is True, internal.errors
    cross_checked = validate_proposal_repository(
        broken_props, ddl_repository=ddl_root
    )
    assert cross_checked.valid is False
    assert any(
        "unknown object Physical ID" in error for error in cross_checked.errors
    )
