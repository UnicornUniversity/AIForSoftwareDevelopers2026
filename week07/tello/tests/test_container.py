"""Composition root: the shipping build must be simulation-only."""

from __future__ import annotations

from drone_vision_lab.adapters.drone import TelloDroneAdapter
from drone_vision_lab.container import DetectorEvents, build_default_services
from drone_vision_lab.domain import DetectorKind
from drone_vision_lab.fakes import FakeDroneAdapter, SyntheticVideoSource
from drone_vision_lab.interfaces import Detector, DroneAdapter, VideoSource
from drone_vision_lab.state import SafetyState


def test_default_services_use_simulation_components():
    services = build_default_services()
    assert isinstance(services.drone, FakeDroneAdapter)
    assert isinstance(services.video_source_factory("synthetic", None), SyntheticVideoSource)
    assert set(services.detectors) == {
        DetectorKind.OPENCV,
        DetectorKind.YOLO,
        DetectorKind.VLM,
    }


def test_default_services_are_interchangeable_with_the_interfaces():
    services = build_default_services()
    assert isinstance(services.drone, DroneAdapter)
    assert isinstance(services.video_source_factory("synthetic", None), VideoSource)
    assert all(isinstance(detector, Detector) for detector in services.detectors.values())


def test_default_services_start_disconnected_and_never_take_off():
    services = build_default_services()
    assert services.state.snapshot().safety_state is SafetyState.DISCONNECTED
    assert services.drone.command_log == ()
    assert not services.drone.connected


def test_default_services_announce_simulation_only():
    services = build_default_services()
    assert any("Simulation only" in note for note in services.notes)


def test_the_default_mode_is_simulated(monkeypatch):
    monkeypatch.delenv("DRONE_VISION_LAB_DRONE", raising=False)

    services = build_default_services()

    assert services.drone_mode == "simulated"
    assert isinstance(services.drone, FakeDroneAdapter)
    assert services.drone.command_log == ()
    assert not services.drone.connected


def test_tello_mode_selects_the_hardware_adapter_without_connecting(monkeypatch):
    monkeypatch.setenv("DRONE_VISION_LAB_DRONE", "tello")

    services = build_default_services()

    assert services.drone_mode == "tello"
    assert isinstance(services.drone, TelloDroneAdapter)
    assert not services.drone.connected
    assert any("Hardware mode" in note for note in services.notes)
    assert any("never recorded automatically" in note for note in services.notes)


def test_an_unknown_drone_mode_falls_back_and_says_so(monkeypatch):
    monkeypatch.setenv("DRONE_VISION_LAB_DRONE", "skynet")

    services = build_default_services()

    assert services.drone_mode == "simulated"
    assert isinstance(services.drone, FakeDroneAdapter)
    assert any("was ignored" in note for note in services.notes)


def test_a_command_line_mode_overrides_the_environment(monkeypatch):
    monkeypatch.setenv("DRONE_VISION_LAB_DRONE", "tello")

    services = build_default_services(drone_mode="simulated")

    assert services.drone_mode == "simulated"
    assert isinstance(services.drone, FakeDroneAdapter)


def test_the_command_line_can_select_the_hardware_adapter(monkeypatch):
    monkeypatch.delenv("DRONE_VISION_LAB_DRONE", raising=False)

    services = build_default_services(drone_mode="tello")

    assert services.drone_mode == "tello"
    assert isinstance(services.drone, TelloDroneAdapter)
    assert not services.drone.connected


# -- detector-change notifications -------------------------------------------


def test_detector_events_notify_subscribers_and_can_be_unsubscribed():
    events = DetectorEvents()
    seen: list[DetectorKind] = []
    unsubscribe = events.subscribe(seen.append)

    events.publish(DetectorKind.YOLO)
    unsubscribe()
    events.publish(DetectorKind.VLM)

    assert seen == [DetectorKind.YOLO]


def test_a_failing_detector_listener_does_not_stop_the_others():
    events = DetectorEvents()
    seen: list[DetectorKind] = []

    def broken(_kind: DetectorKind) -> None:
        raise RuntimeError("the view is gone")

    events.subscribe(broken)
    events.subscribe(seen.append)

    events.publish(DetectorKind.YOLO)

    assert seen == [DetectorKind.YOLO]


def test_every_service_graph_has_its_own_detector_events():
    first = build_default_services()
    second = build_default_services()
    seen: list[DetectorKind] = []
    first.detector_events.subscribe(seen.append)

    second.detector_events.publish(DetectorKind.YOLO)

    assert seen == []
