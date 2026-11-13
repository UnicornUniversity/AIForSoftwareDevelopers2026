"""On-disk profiles: portable JSON, versioning, migration and refusals.

Everything runs against a temporary directory, so no student profile is touched.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from drone_vision_lab.adapters.storage import JsonProfileRepository
from drone_vision_lab.errors import ConfigurationError
from drone_vision_lab.interfaces import PROFILE_SCHEMA_VERSION, Profile


def _repo(tmp_path) -> JsonProfileRepository:
    return JsonProfileRepository(tmp_path / "profiles")


def _save(repo: JsonProfileRepository, profile_id: str = "default", **payload) -> Profile:
    profile = Profile(
        profile_id=profile_id,
        name=payload.pop("name", profile_id.title()),
        payload=payload,
    )
    repo.save(profile)
    return repo.get(profile_id)  # type: ignore[return-value]


def test_save_writes_one_portable_json_document(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "default", opencv={"label": "green_ball", "ranges": [{}, {}]})

    path = tmp_path / "profiles" / "default.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["schema_version"] == PROFILE_SCHEMA_VERSION
    assert document["profile_id"] == "default"
    assert document["name"] == "Default"
    assert document["payload"]["opencv"]["label"] == "green_ball"
    assert document["created_at"]
    assert document["updated_at"]
    # Atomic write leaves no temporary files behind.
    assert list((tmp_path / "profiles").glob("*.tmp")) == []


def test_round_trip_preserves_payload_and_creation_time(tmp_path):
    repo = _repo(tmp_path)
    stored = _save(repo, "default", tracking={"max_speed_cm_s": 40})
    repo.save(
        Profile(
            profile_id="default",
            name="Renamed",
            created_at=stored.created_at,
            payload={"tracking": {"max_speed_cm_s": 30}},
        )
    )

    reloaded = _repo(tmp_path).get("default")
    assert reloaded is not None
    assert reloaded.name == "Renamed"
    assert reloaded.payload["tracking"]["max_speed_cm_s"] == 30
    assert reloaded.created_at == stored.created_at


def test_get_missing_profile_returns_none(tmp_path):
    assert _repo(tmp_path).get("missing") is None


def test_list_profiles_is_sorted_by_name(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "b", name="Zebra")
    _save(repo, "a", name="Apple")

    assert [profile.name for profile in repo.list_profiles()] == ["Apple", "Zebra"]


def test_duplicate_copies_payload_and_uses_a_new_id(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "default", vlm={"model": "llava:7b"})

    clone = repo.duplicate("default", "Lecture 3")

    assert clone.profile_id == "lecture-3"
    assert clone.name == "Lecture 3"
    assert clone.payload == {"vlm": {"model": "llava:7b"}}
    assert repo.get("default").payload == clone.payload  # type: ignore[union-attr]


def test_duplicate_twice_gets_distinct_ids(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "default")

    first = repo.duplicate("default", "Copy")
    second = repo.duplicate("default", "Copy")

    assert first.profile_id != second.profile_id
    assert second.profile_id == "copy-2"


def test_delete_removes_the_file_and_tolerates_a_missing_profile(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "default")
    path = tmp_path / "profiles" / "default.json"
    assert path.exists()

    repo.delete("default")
    repo.delete("default")  # idempotent

    assert not path.exists()
    assert repo.get("default") is None


def test_invalid_json_is_reported_with_the_file_name(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigurationError) as info:
        repo.get("broken")

    assert "broken.json" in info.value.user_message


def test_list_skips_invalid_files_and_keeps_the_valid_ones(tmp_path):
    repo = _repo(tmp_path)
    _save(repo, "good", name="Good")
    (tmp_path / "profiles" / "broken.json").write_text("{not json", encoding="utf-8")

    assert [profile.profile_id for profile in repo.list_profiles()] == ["good"]


def test_profile_from_a_newer_build_is_refused(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "future.json").write_text(
        json.dumps({"schema_version": 99, "profile_id": "future", "name": "Future"}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as info:
        repo.get("future")

    assert "newer build" in info.value.user_message


def test_unversioned_legacy_document_is_migrated_on_read(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "legacy.json").write_text(
        json.dumps(
            {
                "name": "Legacy",
                "opencv": {"label": "old_ball"},
                "source": {"kind": "file", "path": "demo.mp4"},
            }
        ),
        encoding="utf-8",
    )

    profile = repo.get("legacy")

    assert profile is not None
    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.payload["opencv"] == {"label": "old_ball"}
    assert profile.payload["source"]["kind"] == "file"


def test_a_migrated_profile_is_rewritten_in_the_current_format(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    legacy = tmp_path / "profiles" / "legacy.json"
    legacy.write_text(json.dumps({"name": "Legacy", "yolo": {"model_path": "a.pt"}}))

    profile = repo.get("legacy")
    assert profile is not None
    repo.save(profile)

    document = json.loads(legacy.read_text(encoding="utf-8"))
    assert document["schema_version"] == PROFILE_SCHEMA_VERSION
    assert document["payload"]["yolo"]["model_path"] == "a.pt"


def test_credentials_are_refused_on_save(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ConfigurationError) as info:
        repo.save(
            Profile(
                profile_id="leaky",
                name="Leaky",
                payload={"vlm": {"base_url": "http://x", "api_key": "sk-123"}},
            )
        )

    assert "api_key" in info.value.user_message
    assert not (tmp_path / "profiles" / "leaky.json").exists()


def test_credentials_already_in_a_file_are_refused_on_load(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "leaky.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": "leaky",
                "name": "Leaky",
                "payload": {"nested": [{"access_token": "abc"}]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        repo.get("leaky")
    assert repo.list_profiles() == []


def test_ids_that_escape_the_profiles_folder_are_refused(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ConfigurationError):
        repo.get("../outside")
    with pytest.raises(ConfigurationError):
        repo.save(Profile(profile_id="a/b", name="Slash"))


def test_a_payload_that_cannot_be_json_encoded_is_refused(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(ConfigurationError):
        repo.save(
            Profile(
                profile_id="numpy",
                name="NumPy",
                payload={"ranges": np.array([1, 2, 3])},
            )
        )


def test_a_document_cannot_shadow_another_file(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "alpha.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": "beta",
                "name": "Alpha",
                "payload": {},
            }
        ),
        encoding="utf-8",
    )

    stored = repo.get("alpha")

    assert stored is not None
    assert stored.profile_id == "alpha"
