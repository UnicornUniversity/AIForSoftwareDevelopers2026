"""Fake adapters must satisfy the interfaces and behave predictably."""

from __future__ import annotations

import numpy as np
import pytest

from drone_vision_lab.domain import CommandStatus, Detection, DetectorKind
from drone_vision_lab.errors import ConfigurationError, HardwareUnavailableError
from drone_vision_lab.fakes import (
    FakeDetector,
    FakeDroneAdapter,
    FakeGamepad,
    InMemoryProfileRepository,
    InMemoryResultsRepository,
    SyntheticVideoSource,
)
from drone_vision_lab.interfaces import (
    Detector,
    DroneAdapter,
    ExperimentContext,
    GamepadAdapter,
    GamepadState,
    Profile,
    ProfileRepository,
    ResultsRepository,
    VideoSource,
)
from drone_vision_lab.interfaces.video import VideoSourceState

# -- protocol conformance ----------------------------------------------------


def test_fakes_satisfy_their_protocols():
    assert isinstance(FakeDroneAdapter(), DroneAdapter)
    assert isinstance(SyntheticVideoSource(), VideoSource)
    assert isinstance(FakeDetector(), Detector)
    assert isinstance(FakeGamepad(), GamepadAdapter)
    assert isinstance(InMemoryProfileRepository(), ProfileRepository)
    assert isinstance(InMemoryResultsRepository(), ResultsRepository)


# -- drone -------------------------------------------------------------------


def test_fake_drone_refuses_commands_before_connect():
    drone = FakeDroneAdapter()
    result = drone.takeoff()
    assert result.status is CommandStatus.FAILED
    assert "Not connected" in result.detail
    assert drone.flying is False


def test_fake_drone_connect_takeoff_land_sequence():
    drone = FakeDroneAdapter()
    assert drone.connect().status is CommandStatus.SENT
    assert drone.connected
    assert drone.takeoff().status is CommandStatus.SENT
    assert drone.flying is True
    assert drone.land().status is CommandStatus.SENT
    assert drone.flying is False
    assert drone.commands == ("connect", "takeoff", "land")


def test_landing_is_not_reported_as_confirmed_by_default():
    drone = FakeDroneAdapter(confirm_landing=False)
    drone.connect()
    result = drone.land()
    assert result.status is CommandStatus.SENT
    assert result.status is not CommandStatus.CONFIRMED


def test_landing_can_be_confirmed_only_when_observation_is_simulated():
    drone = FakeDroneAdapter(confirm_landing=True)
    drone.connect()
    assert drone.land().status is CommandStatus.CONFIRMED


def test_emergency_land_uses_the_standard_land_command():
    drone = FakeDroneAdapter()
    drone.connect()
    drone.emergency_land()
    assert drone.commands[-1] == "land"


def test_unreachable_drone_fails_to_connect():
    drone = FakeDroneAdapter(reachable=False)
    result = drone.connect()
    assert result.status is CommandStatus.FAILED
    assert drone.connected is False


def test_telemetry_reports_configured_battery():
    drone = FakeDroneAdapter(battery_percent=73)
    assert drone.telemetry().battery_percent == 73
    assert FakeDroneAdapter(battery_percent=None).telemetry().battery_percent is None


def test_move_and_rotate_are_recorded():
    drone = FakeDroneAdapter()
    drone.connect()
    drone.move("left", 50, speed=30)
    drone.rotate("clockwise", 20)
    assert drone.commands[-2:] == ("left 50 30", "clockwise 20")


# -- video source ------------------------------------------------------------


def test_synthetic_source_emits_frames_with_increasing_index():
    source = SyntheticVideoSource(width=64, height=48, fps=10)
    source.open()
    frames = [source.read() for _ in range(3)]
    assert all(frame is not None for frame in frames)
    assert [f.index for f in frames if f] == [0, 1, 2]
    first = frames[0]
    assert first is not None
    assert first.image.shape == (48, 64, 3)
    assert first.image.dtype == np.uint8
    assert first.source_id == "synthetic"


def test_synthetic_source_returns_none_when_closed():
    source = SyntheticVideoSource()
    assert source.read() is None
    source.open()
    assert source.read() is not None
    source.close()
    assert source.read() is None
    assert source.state is VideoSourceState.CLOSED


def test_synthetic_source_pause_and_resume():
    source = SyntheticVideoSource()
    source.open()
    source.pause()
    assert source.read() is None
    source.resume()
    assert source.read() is not None


def test_synthetic_source_seek_changes_next_index():
    source = SyntheticVideoSource(fps=10)
    source.open()
    assert source.seek(2.0) is True
    frame = source.read()
    assert frame is not None and frame.index == 20
    assert source.seek(-1) is False


def test_synthetic_source_can_fail_to_open():
    source = SyntheticVideoSource(fail_on_open=True)
    with pytest.raises(HardwareUnavailableError):
        source.open()
    assert source.state is VideoSourceState.ERROR


# -- detector ----------------------------------------------------------------


def test_detector_reports_error_until_loaded():
    detector = FakeDetector()
    source = SyntheticVideoSource()
    source.open()
    frame = source.read()
    assert frame is not None
    result = detector.detect(frame)
    assert result.failed
    assert not detector.ready


def test_loaded_detector_returns_configured_detections():
    from drone_vision_lab.domain import BoundingBox

    detection = Detection("sports ball", BoundingBox(0.4, 0.4, 0.2, 0.2), confidence=0.8)
    detector = FakeDetector(detections=(detection,), kind=DetectorKind.YOLO)
    detector.load()
    source = SyntheticVideoSource()
    source.open()
    frame = source.read()
    assert frame is not None
    result = detector.detect(frame)
    assert result.found
    assert result.detections == (detection,)
    assert result.kind is DetectorKind.YOLO


def test_detector_error_is_reported_not_raised():
    detector = FakeDetector(error="model unavailable")
    detector.load()
    source = SyntheticVideoSource()
    source.open()
    frame = source.read()
    assert frame is not None
    result = detector.detect(frame)
    assert result.error == "model unavailable"
    assert result.found is False


def test_detector_load_can_fail():
    detector = FakeDetector(fail_on_load=True)
    with pytest.raises(RuntimeError):
        detector.load()


# -- gamepad -----------------------------------------------------------------


def test_gamepad_returns_disconnected_when_closed():
    gamepad = FakeGamepad()
    assert gamepad.poll().connected is False


def test_gamepad_replays_scripted_states():
    scripted = GamepadState(connected=True, axes={"left_x": 0.5}, buttons=frozenset({"a"}))
    gamepad = FakeGamepad([scripted])
    gamepad.open()
    state = gamepad.poll()
    assert state.connected
    assert state.axis("left_x") == 0.5
    assert state.held("a")
    assert state.axis("missing", default=0.0) == 0.0


# -- repositories ------------------------------------------------------------


def test_profile_repository_round_trip_and_duplicate():
    repo = InMemoryProfileRepository()
    repo.save(Profile(profile_id="p1", name="Tennis ball", payload={"target": "green_ball"}))
    loaded = repo.get("p1")
    assert loaded is not None and loaded.payload["target"] == "green_ball"
    assert loaded.created_at  # timestamp filled in by the repository

    clone = repo.duplicate("p1", "Tennis ball (copy)")
    assert clone.name == "Tennis ball (copy)"
    assert clone.payload == loaded.payload
    assert len(repo.list_profiles()) == 2

    repo.delete("p1")
    assert repo.get("p1") is None


def test_profile_repository_rejects_unknown_schema_version():
    repo = InMemoryProfileRepository()
    with pytest.raises(ConfigurationError):
        repo.save(Profile(profile_id="p1", name="x", schema_version=99))


def test_results_repository_exports_csv_and_json(tmp_path):
    import json

    repo = InMemoryResultsRepository()
    experiment = repo.start_experiment(
        "Demo", ExperimentContext(source_type="synthetic", profile_id="default")
    )
    repo.record_metric(experiment, "OpenCV", "fps", 29.5, "fps")
    repo.finish_experiment(experiment)

    csv_path = tmp_path / "out.csv"
    json_path = tmp_path / "out.json"
    assert repo.export_csv(experiment, str(csv_path)) == str(csv_path)
    assert repo.export_json(experiment, str(json_path)) == str(json_path)

    text = csv_path.read_text(encoding="utf-8")
    assert "OpenCV" in text and "29.5" in text
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document["samples"]["OpenCV"][0]["metric"] == "fps"


def test_results_repository_rejects_metric_after_finish():
    repo = InMemoryResultsRepository()
    experiment = repo.start_experiment(
        "Demo", ExperimentContext(source_type="synthetic")
    )
    repo.finish_experiment(experiment)
    with pytest.raises(ConfigurationError):
        repo.record_metric(experiment, "OpenCV", "fps", 1.0)


def test_results_repository_rejects_unknown_experiment():
    repo = InMemoryResultsRepository()
    with pytest.raises(ConfigurationError):
        repo.finish_experiment("missing")
