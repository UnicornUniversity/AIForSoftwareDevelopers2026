"""Autonomous yaw tracking controls in the Computer Vision Lab.

Everything runs against the simulated drone and a scripted detector. Dialogs
are stubbed; the tests check the safety gates and the command path, never a
real controller or camera.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
from PySide6.QtWidgets import QMessageBox

from drone_vision_lab.domain import (
    BoundingBox,
    Detection,
    DetectionResult,
    DetectorKind,
    Frame,
)
from drone_vision_lab.fakes import FakeDetector
from drone_vision_lab.interfaces import VideoSourceStatus
from drone_vision_lab.manual_control import ManualAction
from drone_vision_lab.state import SafetyState


def pump(qapp, predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def stub_dialogs(monkeypatch, answer=QMessageBox.StandardButton.Yes) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kwargs: answer)
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *args, **kwargs: answer)
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda parent, title, text: seen.append(f"{title}: {text}")),
    )
    return seen


def sent(drone) -> tuple[str, ...]:
    return tuple(command for command in drone.commands if command != "connect")


def fresh_frame() -> Frame:
    return Frame(
        image=np.zeros((48, 64, 3), dtype=np.uint8),
        captured_at=time.monotonic(),
        source_id="synthetic",
        index=0,
    )


def detection(center_x: float = 0.20) -> Detection:
    return Detection(
        label="target",
        box=BoundingBox(center_x - 0.05, 0.4, 0.1, 0.2),
    )


def prepare(window, services, *, center_x: float = 0.20) -> FakeDetector:
    detector = FakeDetector(
        kind=DetectorKind.OPENCV, detections=(detection(center_x),)
    )
    detector.load()
    services.detectors[DetectorKind.OPENCV] = detector
    window.vision_tab.refresh_detectors()
    window.drone_tab.connect_button.click()
    window.vision_tab._last_frame = fresh_frame()
    services.state.update(
        safety_state=SafetyState.DRY_RUN_PASSED,
        dry_run_passed_kinds=("opencv",),
        video_active=True,
        autonomy_armed=False,
    )
    window.vision_tab.refresh_tracking()
    return detector


def arm(window, qapp) -> None:
    window.vision_tab.arm_button.click()
    assert pump(qapp, lambda: window.vision_tab.arm_button.text() == "Disarm autonomy")


def start_tracking(window, services, qapp) -> None:
    services.state.update(safety_state=SafetyState.FLYING_MANUAL)
    window.vision_tab._last_frame = fresh_frame()
    window.vision_tab.refresh_tracking()
    window.vision_tab.start_tracking_button.click()
    assert pump(
        qapp,
        lambda: window.vision_tab.tracking_controller is not None
        and window.vision_tab.tracking_controller.active,
    )


def test_arming_is_disabled_until_a_detector_passes_a_dry_run(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    detector = FakeDetector(kind=DetectorKind.OPENCV)
    detector.load()
    services.detectors[DetectorKind.OPENCV] = detector
    window.vision_tab.refresh_tracking()
    window.drone_tab.connect_button.click()
    services.state.update(video_active=True)

    tab = window.vision_tab
    assert tab.arm_button.isEnabled() is False
    tab._on_arm()  # noqa: SLF001 - the disabled button cannot be clicked
    assert "dry run" in tab.tracking_status_text


def test_arming_is_explicit_sends_no_command_and_does_not_take_off(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab

    assert tab.arm_button.isEnabled() is True
    assert "Disarm autonomy" not in tab.arm_button.text()
    arm(window, qapp)

    snapshot = services.state.snapshot()
    assert snapshot.autonomy_armed is True
    assert snapshot.safety_state is SafetyState.ARMED
    assert sent(services.drone) == ()
    assert "No command" in tab.tracking_status_text


def test_start_tracking_requires_manual_flight_and_a_confirmation(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)

    # Armed but still grounded: Start Tracking stays disabled.
    assert tab.start_tracking_button.isEnabled() is False

    services.state.update(safety_state=SafetyState.FLYING_MANUAL)
    tab._last_frame = fresh_frame()
    tab.refresh_tracking()
    stub_dialogs(monkeypatch, QMessageBox.StandardButton.No)
    tab.start_tracking_button.click()
    qapp.processEvents()

    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL
    assert tab.tracking_controller is None
    assert sent(services.drone) == ()


def test_a_confirmed_start_turns_left_and_stop_does_not_land(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)

    assert services.state.snapshot().safety_state is SafetyState.FLYING_TRACKING
    result = DetectionResult(
        detector_name="Test detector",
        kind=DetectorKind.OPENCV,
        detections=(detection(0.20),),
        frame_timestamp=time.monotonic(),
        processed_at=time.monotonic(),
    )
    tab._on_analysis_finished({DetectorKind.OPENCV: result})  # noqa: SLF001

    assert pump(
        qapp, lambda: "counter_clockwise 9" in services.drone.commands
    )
    assert "yaw" in tab.tracking_detail_text.lower()

    tab.stop_tracking_button.click()
    qapp.processEvents()

    assert tab.tracking_controller.active is False
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL
    assert "land" not in sent(services.drone)
    assert "no landing command" in tab.tracking_detail_text.lower()
    assert "still airborne" in tab.tracking_status_text


def test_target_loss_stops_corrections_and_ends_in_operator_attention(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)
    empty = DetectionResult(
        detector_name="Test detector",
        kind=DetectorKind.OPENCV,
        detections=(),
        frame_timestamp=time.monotonic(),
        processed_at=time.monotonic(),
    )

    for _ in range(3):
        tab._on_analysis_finished({DetectorKind.OPENCV: empty})  # noqa: SLF001

    assert tab.tracking_controller.active is False
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL
    assert "Target lost" in tab.tracking_status_text
    assert not any("clockwise" in command for command in sent(services.drone))
    assert "land" not in sent(services.drone)


def test_video_loss_stops_tracking_without_landing(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)

    tab._on_status(VideoSourceStatus.STALE)  # noqa: SLF001

    assert tab.tracking_controller.active is False
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL
    assert "video source" in tab.tracking_status_text.lower()
    assert "land" not in sent(services.drone)


def test_vlm_mode_cannot_arm_or_start_tracking(window, services, monkeypatch):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab

    tab.set_mode(DetectorKind.VLM)

    assert tab.arm_button.isEnabled() is False
    assert tab.start_tracking_button.isEnabled() is False
    assert "OpenCV or YOLO" in tab._tracking_target_label.text()  # noqa: SLF001


def test_manual_input_overrides_tracking_and_then_moves_the_aircraft(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    # Take manual control before arming; it stays engaged through tracking.
    window.drone_tab.manual_panel._take_control_button.click()
    assert window.drone_tab.manual_panel.controller.engaged is True
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)

    window.drone_tab.manual_panel._request_action(ManualAction.RIGHT)  # noqa: SLF001

    assert tab.tracking_controller.active is False
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL
    assert pump(qapp, lambda: "right 30 30" in services.drone.commands)
    assert "Manual override" in tab.tracking_status_text


def test_land_from_tracking_is_sent_but_never_called_confirmed(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)

    tab.tracking_land_button.click()

    assert pump(
        qapp,
        lambda: services.state.snapshot().safety_state
        is SafetyState.LANDING_REQUESTED,
    )
    assert pump(qapp, lambda: "sent — not confirmed" in tab.tracking_status_text)
    assert tab.tracking_controller.active is False
    assert "land" in sent(services.drone)
    assert "Landing confirmed" not in tab.tracking_status_text
    assert services.state.snapshot().autonomy_armed is False


def test_emergency_land_preempts_an_active_tracking_session(
    window, services, monkeypatch, qapp
):
    stub_dialogs(monkeypatch)
    prepare(window, services)
    tab = window.vision_tab
    arm(window, qapp)
    start_tracking(window, services, qapp)

    window.emergency_button.click()
    qapp.processEvents()

    assert tab.tracking_controller.active is False
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "land" in sent(services.drone)
    assert "not confirmed" in window.emergency_status_text
