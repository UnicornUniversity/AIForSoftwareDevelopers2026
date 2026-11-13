"""Preset Flight Missions tab: selection, preview, execution and cancellation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

import numpy as np
from PySide6.QtWidgets import QMessageBox

from drone_vision_lab.config import CONSERVATIVE_LIMITS
from drone_vision_lab.domain import (
    BoundingBox,
    CommandResult,
    CommandStatus,
    Detection,
    DetectorKind,
    Frame,
)
from drone_vision_lab.fakes import FakeDetector, FakeDroneAdapter
from drone_vision_lab.interfaces.video import VideoSourceState, VideoSourceStatus
from drone_vision_lab.preset_missions import PresetRunner
from drone_vision_lab.state import SafetyState
from drone_vision_lab.ui.tabs.preset_missions import PresetMissionsTab


def pump(qapp, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def confirm(monkeypatch, answer=QMessageBox.StandardButton.Yes) -> None:
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kwargs: answer)
    )


def sent(drone) -> tuple[str, ...]:
    return tuple(command for command in drone.commands if command != "connect")


def connect(window) -> None:
    window.drone_tab.connect_button.click()


def test_the_tab_lists_every_program_and_shows_the_first_steps(window):
    tab = window.preset_missions_tab

    assert tab.program_combo.count() == 3
    assert tab.program.program_id == "takeoff-hover-land"
    assert tab.steps_table.rowCount() == 3
    actions = [tab.steps_table.item(row, 1).text() for row in range(3)]
    assert actions == ["Take off", "Hold position", "Land"]
    assert tab.steps_table.item(1, 2).text() == "— (wait; keepalive only)"
    assert "within limits" in tab.validation_label_text
    assert tab.execute_button.isEnabled() is False  # not connected yet
    assert "Connect" in tab.execute_button.toolTip()


def test_selecting_the_square_program_shows_every_step_and_the_sdk_note(window):
    tab = window.preset_missions_tab

    tab.program_combo.setCurrentIndex(1)

    assert tab.program.program_id == "four-left-turns"
    assert tab.steps_table.rowCount() == 10
    actions = [tab.steps_table.item(row, 1).text() for row in range(10)]
    assert actions == [
        "Take off",
        "Turn left",
        "Fly forward",
        "Turn left",
        "Fly forward",
        "Turn left",
        "Fly forward",
        "Turn left",
        "Fly forward",
        "Land",
    ]
    commands = [tab.steps_table.item(row, 2).text() for row in range(10)]
    assert commands[1] == "ccw 90"
    assert commands[2] == "forward 30 30"
    assert "30 cm" in tab.note_text
    assert "20 cm" in tab.note_text
    assert "SDK" in tab.note_text
    assert "within limits" in tab.validation_label_text


def test_preview_sends_nothing(window, monkeypatch):
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(1)
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, text: seen.append(text)),
    )

    tab._preview_button.click()

    assert "Preview sends no command" in seen[0]
    assert "1. Take off" in seen[0]
    assert "ccw 90" in seen[0]
    assert "30 cm" in seen[0]


def test_execute_requires_confirmation_and_sends_nothing_on_no(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch, QMessageBox.StandardButton.No)
    connect(window)
    tab = window.preset_missions_tab

    tab.execute_button.click()
    time.sleep(0.1)
    qapp.processEvents()

    assert sent(services.drone) == ()
    assert services.state.snapshot().safety_state is SafetyState.CONNECTED_GROUNDED
    assert "No preset program has run" in tab.status_text


def test_a_confirmed_program_starts_when_qt_returns_the_answer_as_a_plain_int(
    window, services, monkeypatch, qapp
):
    """The dialog returns an int (16384 for Yes), not a StandardButton member.

    Comparing with ``is`` treated a real "Yes" as "No", so the program never
    started in the running application even though the stubbed tests passed.
    """
    confirm(monkeypatch, int(QMessageBox.StandardButton.Yes))
    connect(window)
    tab = window.preset_missions_tab
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert sent(services.drone) == ("takeoff", "land")


def test_a_confirmed_hover_program_runs_and_never_confirms_landing(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch)
    connect(window)
    tab = window.preset_missions_tab
    # Waits and takeoff settling are covered by the unit tests; skipping them
    # keeps this UI test fast without changing any validation limit.
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert sent(services.drone) == ("takeoff", "land")
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "needs visual confirmation" in tab.status_text
    assert "Landing confirmed" not in tab.status_text
    assert "acknowledged" in tab.status_text


def test_a_landing_observed_in_telemetry_returns_the_tab_to_grounded(
    window, services, monkeypatch, qapp
):
    """The adapter's CONFIRMED result is the independent evidence the contract asks for."""
    confirm(monkeypatch)
    connect(window)
    services.drone._confirm_landing = True  # noqa: SLF001 - test double switch
    tab = window.preset_missions_tab
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert services.state.snapshot().safety_state is SafetyState.LANDED_CONFIRMED
    assert "confirmed by telemetry" in tab.status_text
    assert "not confirmed" not in tab.status_text
    assert tab.execute_button.isEnabled() is True


def test_a_program_cannot_start_from_an_unconfirmed_state(
    window, services, monkeypatch, qapp
):
    """FAULT means the last landing was not confirmed, so a takeoff is refused."""
    connect(window)
    tab = window.preset_missions_tab
    errors: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.preset_missions.widgets.show_error",
        lambda _parent, _title, message: errors.append(str(message)),
    )
    services.state.update(safety_state=SafetyState.FAULT)
    tab.apply_state(services.state.snapshot())

    assert tab.execute_button.isEnabled() is False
    assert "grounded" in tab.execute_button.toolTip().lower()

    tab._execute_program()  # noqa: SLF001 - the runtime guard is the subject
    assert sent(services.drone) == ()
    assert errors and "may still be airborne" in errors[0]


def test_a_confirmed_square_program_sends_the_turns_and_legs_in_order(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch)
    connect(window)
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(1)
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert sent(services.drone) == (
        "takeoff",
        "ccw 90",
        "forward 30 30",
        "ccw 90",
        "forward 30 30",
        "ccw 90",
        "forward 30 30",
        "ccw 90",
        "forward 30 30",
        "land",
    )
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "needs visual confirmation" in tab.status_text


def test_stop_program_cancels_without_landing(window, services, monkeypatch, qapp):
    confirm(monkeypatch)
    connect(window)
    tab = window.preset_missions_tab
    tab._limits = replace(CONSERVATIVE_LIMITS, takeoff_settle_s=0.0)  # noqa: SLF001

    tab.execute_button.click()
    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    tab.stop_button.click()
    assert pump(qapp, lambda: not tab._running)

    assert "land" not in sent(services.drone)
    assert "No landing command was issued" in tab.status_text
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL


def test_the_execute_button_is_disabled_while_the_aircraft_is_airborne(window, services):
    connect(window)
    services.state.update(safety_state=SafetyState.FLYING_MISSION)
    tab = window.preset_missions_tab

    assert tab.execute_button.isEnabled() is False
    assert "already airborne" in tab.execute_button.toolTip()


def test_emergency_land_stays_reachable_while_a_preset_runs(
    window, services, monkeypatch, qapp
):
    slow = FakeDroneAdapter(command_delay=0.08)
    services.drone = slow
    confirm(monkeypatch)
    connect(window)
    tab = window.preset_missions_tab
    tab._limits = replace(CONSERVATIVE_LIMITS, takeoff_settle_s=0.0)  # noqa: SLF001

    tab.execute_button.click()
    assert pump(qapp, lambda: "takeoff" in slow.commands)
    assert window.emergency_button.isEnabled() is True

    window.emergency_button.click()
    tab.stop_button.click()
    assert pump(qapp, lambda: not tab._running)

    assert "land" in sent(slow)
    assert window.emergency_status_text == "Landing command sent — not confirmed"


# -- observation program -----------------------------------------------------


class _QuietSource:
    """A video source that decodes nothing; the test feeds frames directly."""

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
        return "Test camera"

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


class _StreamingSource(_QuietSource):
    """A live source that keeps handing the pump frames, like the camera."""

    def read(self) -> Frame | None:
        return _frame()


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=1)


def _hardware(services) -> None:
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(
        drone_connected=True, safety_state=SafetyState.CONNECTED_GROUNDED
    )


def _install_yolo(services, detections: tuple[Detection, ...] = ()) -> FakeDetector:
    detector = FakeDetector(kind=DetectorKind.YOLO, detections=detections)
    detector.load()
    services.detectors[DetectorKind.YOLO] = detector
    return detector


def _observation_tab(services, source: _QuietSource | None = None) -> PresetMissionsTab:
    created = source or _QuietSource()
    tab = PresetMissionsTab(
        services, source_factory=lambda _kind, _path: created
    )
    tab.program_combo.setCurrentIndex(2)
    return tab


def _stub_errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.preset_missions.widgets.show_error",
        lambda _parent, _title, message: shown.append(str(message)),
    )
    return shown


def test_only_the_apple_program_shows_the_camera_group(qapp, services, monkeypatch):
    _install_yolo(services)
    _hardware(services)
    tab = _observation_tab(services)
    tab.program_combo.setCurrentIndex(0)

    assert tab.program.program_id == "takeoff-hover-land"
    assert tab.camera_group.isHidden() is True

    tab.program_combo.setCurrentIndex(1)
    assert tab.camera_group.isHidden() is True

    tab.program_combo.setCurrentIndex(2)
    assert tab.program.has_observation is True
    assert tab.camera_group.isHidden() is False
    assert tab.steps_table.rowCount() == 4
    assert tab.steps_table.item(1, 1).text() == "Climb"
    assert tab.steps_table.item(1, 2).text() == "up 50"
    assert tab.steps_table.item(2, 1).text() == "Observe target"
    assert tab.steps_table.item(2, 2).text() == "— (wait; keepalive only)"
    assert "1.5 m" in tab.note_text
    assert "90 s" in tab.note_text
    tab.shutdown()


def test_the_apple_program_is_refused_in_simulated_mode(
    qapp, services, monkeypatch
):
    _install_yolo(services)
    assert services.drone.connect().ok
    services.state.update(
        drone_connected=True, safety_state=SafetyState.CONNECTED_GROUNDED
    )
    tab = _observation_tab(services)
    errors = _stub_errors(monkeypatch)

    assert tab.execute_button.isEnabled() is False
    assert "--tello" in tab.execute_button.toolTip()

    tab._execute_program()  # noqa: SLF001 - the runtime guard is the subject
    assert sent(services.drone) == ()
    assert errors and "--tello" in errors[0]
    tab.shutdown()


def test_the_apple_program_will_not_take_off_without_a_yolo_model(
    qapp, services, monkeypatch
):
    _hardware(services)
    tab = _observation_tab(services)
    errors = _stub_errors(monkeypatch)

    assert tab.execute_button.isEnabled() is False
    assert "YOLO" in tab.execute_button.toolTip()

    tab._execute_program()  # noqa: SLF001
    assert "streamon" not in services.drone.commands
    assert "takeoff" not in services.drone.commands
    assert errors and "YOLO" in errors[0]
    tab.shutdown()


def test_the_apple_program_is_refused_while_another_tab_owns_the_camera(
    qapp, services, monkeypatch
):
    _install_yolo(services)
    _hardware(services)
    services.state.update(
        video_active=True, video_source_type="tello", video_owner="tello_flight"
    )
    tab = _observation_tab(services)

    assert tab.execute_button.isEnabled() is False
    assert "Another tab" in tab.execute_button.toolTip()
    tab.shutdown()


def test_a_camera_failure_blocks_takeoff(qapp, services, monkeypatch):
    _install_yolo(services)
    _hardware(services)
    errors = _stub_errors(monkeypatch)

    def _broken(_kind: str, _path: str | None):
        raise RuntimeError("UDP 11111 is already in use")

    tab = PresetMissionsTab(services, source_factory=_broken)
    tab.program_combo.setCurrentIndex(2)
    confirm(monkeypatch)

    tab.execute_button.click()

    assert pump(qapp, lambda: "UDP 11111" in " ".join(errors))
    assert "takeoff" not in services.drone.commands
    assert "no takeoff command was sent" in tab.status_text
    tab.shutdown()


def test_the_camera_starts_before_takeoff_and_the_program_lands_itself(
    qapp, services, monkeypatch
):
    _install_yolo(services)
    _hardware(services)
    source = _QuietSource()
    tab = _observation_tab(services, source)
    confirm(monkeypatch)
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)

    tab.execute_button.click()

    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    assert pump(qapp, lambda: not tab._running)
    commands = list(services.drone.commands)
    assert commands.index("streamon") < commands.index("takeoff")
    assert commands.index("takeoff") < commands.index("up 50")
    assert commands.count("land") == 1
    # Once a takeoff was attempted the camera closes locally; streamoff is not
    # sent into a possible landing.
    assert "streamoff" not in commands
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "needs visual confirmation" in tab.status_text
    # The unconfirmed landing keeps Execute locked; the status line, not only a
    # tooltip, has to say how to clear it.
    assert "Reconnect" in tab.status_text
    assert tab.execute_button.isEnabled() is False
    tab.shutdown()


def test_the_observation_runs_yolo_on_the_live_camera(qapp, services, monkeypatch):
    """Recognition is driven by the camera session, not by the runner thread."""
    detector = _install_yolo(
        services,
        detections=(
            Detection("apple", BoundingBox(0.20, 0.40, 0.10, 0.20), confidence=0.90),
        ),
    )
    _hardware(services)
    tab = _observation_tab(services, _StreamingSource())
    confirm(monkeypatch)

    def _pause(self, seconds: float, **kwargs: object) -> bool:
        if seconds < 30.0:  # takeoff settle
            return True
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and tab.last_result is None:
            time.sleep(0.01)
        return True

    monkeypatch.setattr(PresetRunner, "_pause", _pause)
    assert tab.execute_button.isEnabled() is True, tab.execute_button.toolTip()
    tab.execute_button.click()

    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    assert pump(qapp, lambda: not tab._running)
    assert detector.frames_seen >= 1
    assert tab.last_result is not None
    assert "apple" in tab.detection_label.text()
    assert "display only" in tab.detection_label.text()
    tab.shutdown()


def test_an_aborted_program_says_the_observation_did_not_run_and_how_to_recover(
    qapp, services, monkeypatch
):
    _install_yolo(services)
    _hardware(services)
    tab = _observation_tab(services, _QuietSource())
    confirm(monkeypatch)
    monkeypatch.setattr(PresetRunner, "_pause", lambda self, seconds, **kwargs: True)
    refused = CommandResult(
        "up",
        CommandStatus.FAILED,
        "error No valid imu",
        requested_at=0.0,
        completed_at=0.0,
    )
    monkeypatch.setattr(services.drone, "move", lambda *args, **kwargs: refused)

    tab.execute_button.click()

    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    assert pump(qapp, lambda: not tab._running)
    assert services.state.snapshot().safety_state is SafetyState.FAULT
    assert "No valid imu" in tab.status_text
    assert "observation step did not run" in tab.status_text
    assert "Reconnect" in tab.status_text
    assert tab.execute_button.isEnabled() is False
    # A reconnect is what clears FAULT; the gate follows it in both directions.
    services.state.update(
        drone_connected=True, safety_state=SafetyState.CONNECTED_GROUNDED
    )
    tab.apply_state(services.state.snapshot())
    assert tab.execute_button.isEnabled() is True
    tab.shutdown()


def test_emergency_land_stops_the_observation_without_a_second_landing(
    qapp, services, monkeypatch
):
    _install_yolo(services)
    _hardware(services)
    source = _QuietSource()
    tab = _observation_tab(services, source)
    confirm(monkeypatch)
    during_observation: dict[str, bool] = {}

    def _pause(self, seconds: float, **kwargs: object) -> bool:
        if seconds < 30.0:  # takeoff settle
            return True
        during_observation["reached"] = True
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.cancelling:
                return False
            time.sleep(0.01)
        return False

    monkeypatch.setattr(PresetRunner, "_pause", _pause)

    tab.execute_button.click()

    assert pump(qapp, lambda: during_observation.get("reached", False))
    assert "takeoff" in services.drone.commands

    # Emergency Land's acknowledged landing writes LANDING_REQUESTED. This tab is
    # standalone, so deliver the same snapshot the MainWindow bridge would.
    services.state.update(safety_state=SafetyState.LANDING_REQUESTED)
    tab.apply_state(services.state.snapshot())
    assert pump(qapp, lambda: not tab._running)

    assert "land" not in sent(services.drone)  # no land from the program
    assert "streamoff" not in services.drone.commands
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "A landing was requested" in tab.status_text
    assert "own landing step was not sent" in tab.status_text
    tab.shutdown()


def test_a_frame_runs_yolo_and_marks_the_apple_in_green(qapp, services):
    detector = _install_yolo(
        services,
        detections=(
            Detection("apple", BoundingBox(0.20, 0.40, 0.10, 0.20), confidence=0.91),
        ),
    )
    _hardware(services)
    tab = _observation_tab(services)

    tab._on_frame(_frame())  # noqa: SLF001 - deterministic pipeline entry
    assert pump(qapp, lambda: tab.last_result is not None)

    assert detector.frames_seen == 1
    assert tab.last_result is not None
    text = tab.detection_label.text()
    assert "apple" in text
    assert "0.91" in text
    assert "display only" in text
    assert tab.preview.has_frame is True
    tab.shutdown()


# -- the Execute gate follows detector saves and unconfirmed landings ---------


def test_a_detector_installed_elsewhere_enables_the_apple_program(window, services):
    """The gate is re-read when any tab replaces the YOLO detector.

    Loading weights from another tab installs the detector but emits no state
    change; without the detector-change signal the button stayed disabled while
    the camera panel still said no model was loaded.
    """
    _hardware(services)
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(2)
    assert tab.execute_button.isEnabled() is False
    assert "YOLO" in tab.execute_button.toolTip()

    _install_yolo(services)
    services.detector_events.publish(DetectorKind.YOLO)

    assert tab.execute_button.isEnabled() is True
    assert "Fake detector" in tab.target_label.text()


def test_an_unconfirmed_landing_is_not_reported_as_already_airborne(window, services):
    """LANDING_REQUESTED means "may still be airborne", not "is airborne"."""
    _install_yolo(services)
    _hardware(services)
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(2)
    services.state.update(safety_state=SafetyState.LANDING_REQUESTED)

    assert tab.execute_button.isEnabled() is False
    tooltip = tab.execute_button.toolTip()
    assert "not confirmed" in tooltip
    assert "may still be airborne" in tooltip
    assert "already airborne" not in tooltip


def test_the_unconfirmed_landing_guard_explains_the_situation(
    window, services, monkeypatch
):
    _install_yolo(services)
    _hardware(services)
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(2)
    services.state.update(safety_state=SafetyState.LANDING_REQUESTED)
    errors = _stub_errors(monkeypatch)

    tab._execute_program()  # noqa: SLF001 - the runtime guard is the subject

    assert sent(services.drone) == ()
    assert errors
    assert "has not been confirmed" in errors[0]
    assert "may still be airborne" in errors[0]
