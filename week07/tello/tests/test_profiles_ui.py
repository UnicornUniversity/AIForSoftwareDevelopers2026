"""Profile manager dialog: CRUD, confirmation and applying a profile.

The dialog is driven through its public methods; prompts and confirmations are
replaced on the instance so the suite stays headless.
"""

from __future__ import annotations

import pytest

from drone_vision_lab.adapters.storage import JsonProfileRepository
from drone_vision_lab.adapters.vision import HsvRange, OpenCvDetectorConfig, OpenCvTargetDetector
from drone_vision_lab.adapters.vlm import OllamaVlmDetector
from drone_vision_lab.domain import DetectorKind
from drone_vision_lab.interfaces import Profile
from drone_vision_lab.state import SafetyState
from drone_vision_lab.ui.profiles_dialog import ProfilesDialog


@pytest.fixture
def isolated(services, tmp_path):
    services.profiles = JsonProfileRepository(tmp_path / "profiles")
    return services


@pytest.fixture
def dialog(qapp, isolated):
    return ProfilesDialog(isolated)


def _calibrated_config() -> OpenCvDetectorConfig:
    return OpenCvDetectorConfig(
        ranges=(HsvRange(lower=(40, 80, 80), upper=(80, 255, 255)),),
        label="tennis_ball",
    )


def test_create_writes_a_json_file_and_selects_it(dialog, isolated):
    created = dialog.create_profile("Lecture 3")

    assert created.profile_id == "lecture-3"
    assert isolated.profiles.get("lecture-3") is not None
    assert dialog.selected_profile is not None
    assert dialog.selected_profile.profile_id == "lecture-3"
    assert dialog.list_widget.count() == 1


def test_created_ids_stay_unique(dialog, isolated):
    dialog.create_profile("Demo")
    dialog.create_profile("Demo")

    ids = {profile.profile_id for profile in dialog.profiles}
    assert ids == {"demo", "demo-2"}


def test_rename_keeps_the_id_and_payload(dialog, isolated):
    created = dialog.create_profile("Old name")
    isolated.profiles.save(
        Profile(profile_id=created.profile_id, name="Old name", payload={"yolo": {"a": 1}})
    )
    dialog.refresh()

    renamed = dialog.rename_selected("New name")

    assert renamed is not None
    assert renamed.profile_id == "old-name"
    assert renamed.name == "New name"
    assert renamed.payload == {"yolo": {"a": 1}}


def test_duplicate_copies_the_payload(dialog, isolated):
    created = dialog.create_profile("Source")
    isolated.profiles.save(
        Profile(
            profile_id=created.profile_id,
            name="Source",
            payload={"vlm": {"model": "llava:7b"}},
        )
    )
    dialog.refresh()

    clone = dialog.duplicate_selected("Source copy")

    assert clone is not None
    assert clone.profile_id == "source-copy"
    assert clone.payload == {"vlm": {"model": "llava:7b"}}


def test_delete_asks_first_and_cancelling_keeps_the_profile(dialog, isolated):
    dialog.create_profile("Keep me")
    dialog.confirm_delete = lambda profile: False  # type: ignore[method-assign]

    dialog._on_delete()  # noqa: SLF001 - simulates the button

    assert isolated.profiles.get("keep-me") is not None
    assert "cancelled" in dialog.status_text.lower()


def test_confirming_delete_removes_the_file(dialog, isolated):
    dialog.create_profile("Delete me")
    dialog.confirm_delete = lambda profile: True  # type: ignore[method-assign]

    dialog._on_delete()  # noqa: SLF001

    assert isolated.profiles.get("delete-me") is None
    assert dialog.profiles == []


def test_deleting_the_active_profile_clears_the_active_id(dialog, isolated):
    dialog.create_profile("Active")
    isolated.state.update(active_profile_id="active")
    dialog.confirm_delete = lambda profile: True  # type: ignore[method-assign]

    dialog._on_delete()  # noqa: SLF001

    assert isolated.state.snapshot().active_profile_id is None


def test_save_current_settings_copies_the_active_payload(dialog, isolated):
    dialog.create_profile("Configured")
    isolated.profiles.save(
        Profile(
            profile_id="configured",
            name="Configured",
            payload={"opencv": {"label": "ball"}},
        )
    )
    dialog.create_profile("Target")
    isolated.state.update(active_profile_id="configured")
    dialog.refresh()
    dialog._select("target")  # noqa: SLF001 - selection and active profile differ

    dialog.save_current_settings()

    saved = isolated.profiles.get("target")
    assert saved is not None
    assert saved.payload == {"opencv": {"label": "ball"}}


def test_loading_a_profile_installs_the_detector(dialog, isolated):
    isolated.profiles.save(
        Profile(
            profile_id="calibrated",
            name="Calibrated",
            payload={"opencv": _calibrated_config().to_dict()},
        )
    )
    dialog.refresh()
    dialog._select("calibrated")  # noqa: SLF001

    summary = dialog.load_selected()

    detector = isolated.detectors[DetectorKind.OPENCV]
    assert isinstance(detector, OpenCvTargetDetector)
    assert detector.ready is True
    assert detector.config.label == "tennis_ball"
    assert "OpenCV calibration" in summary
    assert isolated.state.snapshot().active_profile_id == "calibrated"


def test_loading_a_vlm_profile_never_contacts_ollama(dialog, isolated):
    isolated.profiles.save(
        Profile(
            profile_id="vlm",
            name="VLM",
            payload={
                "vlm": {
                    "schema_version": 1,
                    "base_url": "http://127.0.0.1:11434",
                    "model": "llava:7b",
                    "target": "ball",
                }
            },
        )
    )
    dialog.refresh()
    dialog._select("vlm")  # noqa: SLF001

    dialog.load_selected()

    detector = isolated.detectors[DetectorKind.VLM]
    assert isinstance(detector, OllamaVlmDetector)
    assert detector.config.model == "llava:7b"
    # Constructing a profile never opens a socket, so the detector is not loaded.
    assert detector.ready is False


def test_loading_a_profile_starts_no_source_and_sends_no_command(dialog, isolated):
    isolated.profiles.save(
        Profile(
            profile_id="source",
            name="Source",
            payload={"source": {"kind": "synthetic", "path": None}},
        )
    )
    dialog.refresh()
    dialog._select("source")  # noqa: SLF001

    summary = dialog.load_selected()

    snapshot = isolated.state.snapshot()
    assert snapshot.video_active is False
    assert snapshot.video_source_type is None
    assert snapshot.drone_connected is False
    assert snapshot.safety_state is SafetyState.DISCONNECTED
    assert "not started automatically" in summary


def test_an_unknown_section_is_reported_without_blocking_the_rest(dialog, isolated):
    isolated.profiles.save(
        Profile(
            profile_id="mixed",
            name="Mixed",
            payload={
                "opencv": {"schema_version": 999, "ranges": []},
                "vlm": {"schema_version": 1, "model": "llava:7b"},
            },
        )
    )
    dialog.refresh()
    dialog._select("mixed")  # noqa: SLF001

    summary = dialog.load_selected()

    assert "Not applied" in summary
    assert "VLM" in summary
    assert isinstance(isolated.detectors[DetectorKind.VLM], OllamaVlmDetector)


def test_refresh_marks_the_active_profile(dialog, isolated):
    dialog.create_profile("One")
    isolated.state.update(active_profile_id="one")

    dialog.refresh()

    labels = [
        dialog.list_widget.item(row).text() for row in range(dialog.list_widget.count())
    ]
    assert labels == ["One  (active)"]
