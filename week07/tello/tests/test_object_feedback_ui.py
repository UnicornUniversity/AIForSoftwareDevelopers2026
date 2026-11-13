"""Object detection & feedback tab: advisory only, never a flight command.

The aircraft, video source and YOLO model are doubles. These tests pin the two
things that matter: the tab sends only ``streamon``/``streamoff`` for the Tello
camera, and its output is a message — never a command.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np

from drone_vision_lab.domain import BoundingBox, Detection, DetectorKind, Frame
from drone_vision_lab.fakes import FakeDetector, FakeDroneAdapter
from drone_vision_lab.interfaces.video import VideoSourceState, VideoSourceStatus
from drone_vision_lab.pursuit import PursuitAction
from drone_vision_lab.state import AppStateSnapshot
from drone_vision_lab.ui.tabs.object_feedback import ObjectFeedbackTab

_FLIGHT_COMMANDS = {
    "takeoff",
    "land",
    "emergency_land",
    "up",
    "down",
    "forward",
    "back",
    "left",
    "right",
    "rotate",
    "move",
    "emergency",
}

LEFT = (Detection("apple", BoundingBox(0.20, 0.40, 0.10, 0.20), confidence=0.90),)
RIGHT = (Detection("apple", BoundingBox(0.75, 0.40, 0.10, 0.20), confidence=0.90),)
CENTERED = (Detection("apple", BoundingBox(0.45, 0.40, 0.10, 0.20), confidence=0.90),)


class _QuietSource:
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
        return "Test source"

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
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=3)


def _hardware(services):
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(drone_connected=True)
    return services


def _tab(services, source: _QuietSource | None = None) -> ObjectFeedbackTab:
    created = source or _QuietSource()
    return ObjectFeedbackTab(services, source_factory=lambda _kind, _path: created)


def _file_tab(services, source: _QuietSource | None = None) -> ObjectFeedbackTab:
    tab = _tab(services, source)
    assert tab.session.start("file", "clip.mp4") is True
    return tab


def _install_yolo(services, *, detections=LEFT, error: str | None = None) -> FakeDetector:
    detector = FakeDetector(kind=DetectorKind.YOLO, detections=detections, error=error)
    detector.load()
    services.detectors[DetectorKind.YOLO] = detector
    return detector


def _stub_errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.object_feedback.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    return shown


def _detect(qapp, tab: ObjectFeedbackTab) -> None:
    tab._on_frame(_frame())  # noqa: SLF001 - deterministic pipeline entry
    assert _wait(qapp, lambda: tab.last_result is not None)  # noqa: SLF001


# -- lifecycle ---------------------------------------------------------------


def test_constructing_the_tab_starts_nothing(qapp, services):
    source = _QuietSource()
    tab = _tab(services, source)

    assert tab.source is None
    assert source.opened is False
    assert services.state.snapshot().video_active is False
    assert services.drone.commands == ()
    assert tab.advisor.active is False


def test_the_tello_camera_is_refused_in_simulated_mode(qapp, services, monkeypatch):
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_source() is False
    assert shown and "--tello" in shown[0]
    assert tab.source is None
    assert services.drone.commands == ()


def test_the_tello_camera_is_refused_before_connecting(qapp, services, monkeypatch):
    services.drone_mode = "tello"
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_source() is False
    assert shown and "Connect" in shown[0]
    assert services.drone.commands == ()


def test_the_tello_camera_is_refused_when_tello_flight_owns_it(
    qapp, services, monkeypatch
):
    _hardware(services)
    services.state.update(
        video_active=True, video_source_type="tello", video_owner="tello_flight"
    )
    shown = _stub_errors(monkeypatch)
    tab = _tab(services)

    assert tab.start_source() is False
    assert shown and "Another tab" in shown[0]
    assert "streamon" not in services.drone.commands


def test_starting_the_tello_camera_claims_ownership(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)

    assert tab.start_source() is True
    assert _wait(qapp, lambda: tab.source is not None)

    snapshot = services.state.snapshot()
    assert source.opened is True
    assert services.drone.commands[-1] == "streamon"
    assert snapshot.video_source_type == "tello"
    assert snapshot.video_owner == "object_feedback"
    assert tab.advisor.active is True
    tab.shutdown()


def test_stopping_releases_the_camera_and_sends_streamoff(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    assert tab.start_source() is True
    assert _wait(qapp, lambda: tab.source is not None)

    tab.stop_button.click()

    snapshot = services.state.snapshot()
    assert tab.source is None
    assert source.closed is True
    assert snapshot.video_active is False
    assert snapshot.video_owner is None
    assert tab.advisor.active is False
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert _FLIGHT_COMMANDS.isdisjoint(services.drone.commands)


def test_an_open_failure_reports_the_error_and_releases_the_camera(
    qapp, services, monkeypatch
):
    _hardware(services)
    shown = _stub_errors(monkeypatch)

    def _broken(_kind, _path):
        raise RuntimeError("UDP 11111 is already in use")

    tab = ObjectFeedbackTab(services, source_factory=_broken)
    assert tab.start_source() is True
    assert _wait(qapp, lambda: "UDP 11111" in " ".join(shown))

    assert tab.source is None
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert services.state.snapshot().video_owner is None


def test_stop_during_streamon_never_opens_the_camera(qapp, services):
    services.drone = FakeDroneAdapter(command_delay=0.1)
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)

    assert tab.start_source() is True
    tab.stop_source()

    assert _wait(qapp, lambda: not tab.camera_busy)
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert tab.source is None
    assert source.opened is False
    assert services.state.snapshot().video_owner is None


def test_a_file_source_starts_without_any_drone_command(qapp, services, monkeypatch):
    source = _QuietSource()
    tab = _tab(services, source)
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.object_feedback.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("clip.mp4", ""),
    )
    tab.source_combo.setCurrentIndex(1)  # Video file…

    assert tab.start_source() is True

    snapshot = services.state.snapshot()
    assert source.opened is True
    assert snapshot.video_source_type == "file"
    assert snapshot.video_owner == "object_feedback"
    assert services.drone.commands == ()
    tab.shutdown()


def test_disconnect_stops_a_tello_source(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    assert tab.start_source() is True
    assert _wait(qapp, lambda: tab.source is not None)

    tab.apply_state(AppStateSnapshot(drone_connected=False))

    assert tab.source is None
    assert source.closed is True
    assert tab.advisor.active is False
    assert "disconnected" in tab.banner_label.text().lower()
    assert services.state.snapshot().video_owner is None
    assert "land" not in services.drone.commands


def test_disconnect_does_not_stop_a_file_source(qapp, services):
    tab = _file_tab(services)

    tab.apply_state(AppStateSnapshot(drone_connected=False))

    assert tab.source is not None
    assert tab.advisor.active is True
    tab.shutdown()


def test_shutdown_releases_the_camera_and_sends_no_flight_command(qapp, services):
    _hardware(services)
    source = _QuietSource()
    tab = _tab(services, source)
    assert tab.start_source() is True
    assert _wait(qapp, lambda: tab.source is not None)

    tab.shutdown()

    assert tab.source is None
    assert source.closed is True
    assert set(services.drone.commands) <= {"connect", "streamon", "streamoff"}
    assert _FLIGHT_COMMANDS.isdisjoint(services.drone.commands)


def test_the_tab_has_no_route_to_any_flight_command(qapp, services, monkeypatch):
    _install_yolo(services)
    _hardware(services)

    def _forbid(name: str):
        def _raise(*_args, **_kwargs):
            raise AssertionError(f"{name} must never be called")

        return _raise

    for name in ("takeoff", "land", "emergency_land", "move", "rotate", "send_command"):
        monkeypatch.setattr(services.drone, name, _forbid(name))

    tab = _tab(services)
    assert tab.start_source() is True
    assert _wait(qapp, lambda: tab.source is not None)
    _detect(qapp, tab)
    tab.stop_source()
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    tab.shutdown()

    assert set(services.drone.commands) <= {"connect", "streamon", "streamoff"}


# -- advisory decisions ------------------------------------------------------


def test_a_target_to_the_left_prints_a_left_advisory(qapp, services):
    _install_yolo(services, detections=LEFT)
    tab = _file_tab(services)

    _detect(qapp, tab)

    decision = tab.last_decision
    assert decision is not None
    assert decision.action is PursuitAction.YAW_LEFT
    assert "Apple is left of center" in decision.message
    banner = tab.banner_label.text()
    assert banner == decision.banner
    assert banner.startswith("ADVISORY ONLY — no command is sent.")
    assert tab.last_guidance is not None
    assert tab.last_guidance.target_color == "#34c759"
    assert "ADVISORY ONLY" in tab.decision_log.toPlainText()
    tab.shutdown()


def test_a_target_to_the_right_prints_a_right_advisory(qapp, services):
    _install_yolo(services, detections=RIGHT)
    tab = _file_tab(services)

    _detect(qapp, tab)

    decision = tab.last_decision
    assert decision is not None
    assert decision.action is PursuitAction.YAW_RIGHT
    assert "Apple is right of center" in tab.banner_label.text()
    tab.shutdown()


def test_a_centred_target_prints_a_hold_heading_advisory(qapp, services):
    _install_yolo(services, detections=CENTERED)
    tab = _file_tab(services)

    _detect(qapp, tab)

    decision = tab.last_decision
    assert decision is not None
    assert decision.action is PursuitAction.CENTERED
    assert "Apple is centered → hold heading." in tab.banner_label.text()
    tab.shutdown()


def test_no_target_prints_a_no_target_advisory(qapp, services):
    _install_yolo(services, detections=())
    tab = _file_tab(services)

    _detect(qapp, tab)

    decision = tab.last_decision
    assert decision is not None
    assert decision.action is PursuitAction.NO_TARGET
    assert "No apple detected" in tab.banner_label.text()
    assert "ADVISORY ONLY" in tab.banner_label.text()
    tab.shutdown()


def test_a_detector_failure_stops_the_advisory(qapp, services):
    _install_yolo(services, detections=(), error="weights unreadable")
    tab = _file_tab(services)

    _detect(qapp, tab)

    decision = tab.last_decision
    assert decision is not None
    assert decision.action is PursuitAction.STOPPED
    assert "The detector failed: weights unreadable" in tab.banner_label.text()
    assert tab.advisor.active is False
    tab.shutdown()


def test_resume_advisories_restarts_after_a_stop(qapp, services):
    _install_yolo(services, detections=(), error="weights unreadable")
    tab = _file_tab(services)
    _detect(qapp, tab)

    assert tab.advisor.active is False
    assert tab.resume_button.isEnabled() is True

    tab.resume_button.click()

    assert tab.advisor.active is True
    assert "Watching for the apple" in tab.banner_label.text()
    assert tab.resume_button.isEnabled() is False
    assert services.drone.commands == ()
    tab.shutdown()


def test_resume_advisories_is_disabled_without_a_source(qapp, services):
    tab = _tab(services)

    assert tab.resume_button.isEnabled() is False
    assert tab.resume_advisories() is False
    assert tab.advisor.active is False
    tab.shutdown()


def test_every_logged_line_carries_the_advisory_disclaimer(qapp, services):
    _install_yolo(services, detections=LEFT)
    tab = _file_tab(services)
    _detect(qapp, tab)

    lines = [
        line
        for line in tab.decision_log.toPlainText().splitlines()
        if line.strip()
    ]

    assert lines
    assert all("ADVISORY ONLY — no command is" in line for line in lines)
    tab.shutdown()


def test_without_a_model_live_video_is_shown_without_advice(qapp, services):
    tab = _file_tab(services)

    tab._on_frame(_frame())  # noqa: SLF001
    qapp.processEvents()

    assert tab.last_result is None
    assert tab.preview.has_frame is True
    assert "No advisory" in tab.banner_label.text()
    tab.shutdown()


def test_a_class_other_than_apple_is_surfaced(qapp, services):
    detector = _install_yolo(services)
    detector.config = SimpleNamespace(class_label="sports ball")  # type: ignore[attr-defined]

    tab = _tab(services)

    assert tab.advisor.target_label == "sports ball"
    assert "sports ball" in tab.target_label.text()
    assert "set 'apple'" in tab.target_label.text()
    tab.shutdown()


def test_a_result_that_arrives_after_stop_is_ignored(qapp, services, monkeypatch):
    detector = _install_yolo(services)
    original = detector.detect

    def _slow(frame):
        time.sleep(0.1)
        return original(frame)

    monkeypatch.setattr(detector, "detect", _slow)
    tab = _file_tab(services)

    tab._on_frame(_frame())  # noqa: SLF001
    tab.stop_source()
    assert _wait(qapp, lambda: not tab.analysis_busy)

    assert tab.last_result is None
    assert tab.banner_label.text() == "No source — choose the Tello camera or a video file."
