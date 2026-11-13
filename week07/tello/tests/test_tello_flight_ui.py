"""Tello Flight tab: explicit camera lifecycle and display-only detection.

The aircraft, video source and YOLO model are all doubles. These tests assert
that the tab sends only camera-stream commands, never a flight command, and
that a detection can never reach flight control or another tab's video.
"""

from __future__ import annotations

import time

import numpy as np

from drone_vision_lab.domain import (
    BoundingBox,
    Detection,
    DetectorKind,
    Frame,
)
from drone_vision_lab.fakes import FakeDetector
from drone_vision_lab.interfaces.video import VideoSourceState, VideoSourceStatus
from drone_vision_lab.state import AppStateSnapshot
from drone_vision_lab.ui.tabs.tello_flight import TelloFlightTab

BOX_A = BoundingBox(0.1, 0.1, 0.2, 0.2)
BOX_B = BoundingBox(0.5, 0.5, 0.2, 0.2)
PEOPLE = (
    Detection(label="person", box=BOX_A, confidence=0.92),
    Detection(label="cup", box=BOX_B, confidence=0.54),
)

_FLIGHT_COMMANDS = {"takeoff", "land", "emergency_land", "up", "down", "forward"}


class _QuietSource:
    """A Tello-shaped source whose ``read`` never produces a frame.

    The tab's own pump would otherwise race the deterministic frame calls in
    the detection tests. The source records open/close so lifecycle tests can
    assert the receiver really was released.
    """

    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self._state = VideoSourceState.CLOSED

    @property
    def source_id(self) -> str:
        return "tello::test"

    @property
    def state(self) -> VideoSourceState:
        return self._state

    @property
    def status(self) -> VideoSourceStatus:
        return VideoSourceStatus.LIVE if self.opened else VideoSourceStatus.OFFLINE

    @property
    def description(self) -> str:
        return "Tello camera — test source"

    def open(self) -> None:
        self.opened = True
        self._state = VideoSourceState.READY

    def close(self) -> None:
        self.closed = True
        self._state = VideoSourceState.CLOSED

    def read(self) -> Frame | None:
        return None

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def seek(self, position_seconds: float) -> bool:
        return False

    def set_looping(self, looping: bool) -> None: ...


def _wait(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="tello::test", index=3)


def _hardware(services):
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(drone_connected=True)
    return services


def _tab(services, source: _QuietSource | None = None) -> TelloFlightTab:
    created = source or _QuietSource()
    return TelloFlightTab(services, source_factory=lambda _kind, _path: created)


def _install_yolo(services, *, detections=PEOPLE, error: str | None = None) -> FakeDetector:
    detector = FakeDetector(kind=DetectorKind.YOLO, detections=detections, error=error)
    detector.load()
    services.detectors[DetectorKind.YOLO] = detector
    return detector


def _stub_errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.tello_flight.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    return shown


# -- lifecycle ---------------------------------------------------------------


def test_constructing_the_tab_starts_nothing(qapp, services):
    source = _QuietSource()
    tab = TelloFlightTab(services, source_factory=lambda _kind, _path: source)

    assert tab.source is None
    assert source.opened is False
    assert services.state.snapshot().video_active is False
    assert services.drone.commands == ()


def test_camera_is_refused_in_simulated_mode(qapp, services, monkeypatch):
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_camera() is False
    assert shown and "--tello" in shown[0]
    assert tab.source is None
    assert services.drone.commands == ()


def test_camera_is_refused_before_the_aircraft_is_connected(qapp, services, monkeypatch):
    services.drone_mode = "tello"
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_camera() is False
    assert shown and "Connect" in shown[0]
    assert tab.source is None
    assert services.drone.commands == ()


def test_camera_is_refused_when_another_tab_owns_it(qapp, services, monkeypatch):
    _hardware(services)
    services.state.update(
        video_active=True,
        video_source_type="synthetic",
        video_owner="vision_lab",
    )
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_camera() is False
    assert shown and "Another tab" in shown[0]
    assert tab.source is None
    assert "streamon" not in services.drone.commands


def test_camera_is_refused_when_the_object_feedback_tab_owns_it(
    qapp, services, monkeypatch
):
    _hardware(services)
    services.state.update(
        video_active=True,
        video_source_type="file",
        video_owner="object_feedback",
    )
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_camera() is False
    assert shown and "Another tab" in shown[0]
    assert tab.source is None
    assert "streamon" not in services.drone.commands


def test_start_sends_streamon_and_claims_the_camera(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)

    tab.start_button.click()
    assert _wait(qapp, lambda: tab.source is not None)

    assert source.opened is True
    assert services.drone.commands[-1] == "streamon"
    snapshot = services.state.snapshot()
    assert snapshot.video_active is True
    assert snapshot.video_source_type == "tello"
    assert snapshot.video_owner == "tello_flight"
    assert tab.start_button.isEnabled() is False
    assert tab.stop_button.isEnabled() is True
    tab.shutdown()


def test_stop_sends_streamoff_and_releases_the_camera(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    tab.start_camera()
    assert _wait(qapp, lambda: tab.source is not None)

    tab.stop_button.click()

    assert tab.source is None
    assert source.closed is True
    snapshot = services.state.snapshot()
    assert snapshot.video_active is False
    assert snapshot.video_source_type is None
    assert snapshot.video_owner is None
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert _FLIGHT_COMMANDS.isdisjoint(services.drone.commands)


def test_an_open_failure_sends_streamoff_and_reports_the_error(qapp, services, monkeypatch):
    _hardware(services)
    shown = _stub_errors(monkeypatch)

    def _broken(_kind, _path):
        raise RuntimeError("UDP 11111 is already in use")

    tab = TelloFlightTab(services, source_factory=_broken)
    tab.start_camera()
    assert _wait(qapp, lambda: "UDP 11111" in " ".join(shown))

    assert tab.source is None
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert services.state.snapshot().video_owner is None


def test_stop_during_streamon_does_not_open_the_camera_later(qapp, services):
    from drone_vision_lab.fakes import FakeDroneAdapter

    services.drone = FakeDroneAdapter(command_delay=0.1)
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)

    assert tab.start_camera() is True
    tab.stop_camera()

    assert _wait(qapp, lambda: not tab.camera_busy)
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)

    assert tab.source is None
    assert source.opened is False
    assert services.state.snapshot().video_owner is None


def test_disconnect_stops_the_camera_without_sending_a_land(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    tab.start_camera()
    assert _wait(qapp, lambda: tab.source is not None)

    tab.apply_state(AppStateSnapshot(drone_connected=False))

    assert tab.source is None
    assert source.closed is True
    assert "disconnected" in tab._status_pill.text().lower()  # noqa: SLF001
    assert services.state.snapshot().video_owner is None
    assert "land" not in services.drone.commands


def test_shutdown_releases_the_camera_and_sends_no_flight_command(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    tab.start_camera()
    assert _wait(qapp, lambda: tab.source is not None)

    tab.shutdown()

    assert tab.source is None
    assert source.closed is True
    assert set(services.drone.commands) <= {"connect", "streamon", "streamoff"}
    assert _FLIGHT_COMMANDS.isdisjoint(services.drone.commands)


# -- detection ---------------------------------------------------------------


def test_detections_are_labelled_with_class_and_confidence(qapp, services):
    detector = _install_yolo(services)
    tab = _tab(services)

    tab._on_frame(_frame())  # noqa: SLF001 - drives the pipeline deterministically
    assert _wait(qapp, lambda: tab.last_result is not None)

    assert detector.frames_seen == 1
    summary = tab.summary_label.text()
    assert "2 object(s)" in summary
    assert "person (0.92)" in summary
    assert "cup (0.54)" in summary
    assert tab.preview.has_frame is True


def test_detection_failure_is_reported_and_not_hidden(qapp, services):
    _install_yolo(services, detections=(), error="weights unreadable")
    tab = _tab(services)

    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: tab.last_result is not None)

    summary = tab.summary_label.text()
    assert "Detection failed" in summary
    assert "weights unreadable" in summary


def test_turning_the_overlay_off_leaves_live_video_alone(qapp, services):
    detector = _install_yolo(services)
    tab = _tab(services)
    tab.detect_check.setChecked(False)

    tab._on_frame(_frame())  # noqa: SLF001
    qapp.processEvents()

    assert detector.frames_seen == 0
    assert tab.preview.has_frame is True
    assert tab.last_result is None


def test_an_analysis_result_that_arrives_after_stop_is_ignored(
    qapp, services, monkeypatch
):
    detector = _install_yolo(services)
    original = detector.detect_all_classes

    def _slow(frame):
        time.sleep(0.1)
        return original(frame)

    monkeypatch.setattr(detector, "detect_all_classes", _slow)
    tab = _tab(services)

    tab._on_frame(_frame())  # noqa: SLF001
    tab.stop_camera()
    assert _wait(qapp, lambda: not tab._analysis_runner.busy)  # noqa: SLF001

    assert tab.last_result is None
    assert "No camera" in tab.summary_label.text()


def test_yolo_status_tells_the_operator_when_no_model_is_loaded(qapp, services):
    tab = _tab(services)

    assert "no model loaded" in tab.yolo_label.text().lower()
    assert tab.detect_check.isEnabled() is False
