"""Yaw-only tracking decisions and every stop condition.

No drone, camera or model is involved: the fake drone only records commands and
the detection results are constructed directly.
"""

from __future__ import annotations

import pytest

from drone_vision_lab.config import SafetyLimits
from drone_vision_lab.domain import (
    BoundingBox,
    Detection,
    DetectionResult,
    DetectorKind,
)
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.state import AppStateSnapshot, SafetyState
from drone_vision_lab.tracking import (
    TrackingController,
    TrackingSettings,
    TrackingUpdate,
    yaw_command_for_error,
)


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def flight_snapshot(
    *,
    armed: bool = True,
    dry_run: tuple[str, ...] = ("opencv",),
    state: SafetyState = SafetyState.FLYING_MANUAL,
) -> AppStateSnapshot:
    return AppStateSnapshot(
        safety_state=state,
        drone_connected=True,
        dry_run_passed_kinds=dry_run,
        autonomy_armed=armed,
    )


def detection_result(
    center_x: float,
    *,
    kind: DetectorKind = DetectorKind.OPENCV,
    processed_at: float,
    detections: int = 1,
    error: str | None = None,
) -> DetectionResult:
    boxes = tuple(
        Detection(
            label="target",
            box=BoundingBox(center_x - 0.05, 0.4, 0.1, 0.2),
        )
        for _ in range(detections)
    )
    return DetectionResult(
        detector_name="Test detector",
        kind=kind,
        detections=boxes if error is None else (),
        frame_timestamp=processed_at,
        processed_at=processed_at,
        error=error,
    )


def make_controller(
    *,
    clock: Clock | None = None,
    settings: TrackingSettings | None = None,
    kind: DetectorKind = DetectorKind.OPENCV,
    detector_ready: bool = True,
    on_error=None,
) -> tuple[TrackingController, FakeDroneAdapter, Clock]:
    drone = FakeDroneAdapter()
    drone.connect()
    clock = clock or Clock()
    controller = TrackingController(
        drone,
        detector_kind=kind,
        settings=settings or TrackingSettings(),
        clock=clock,
        detector_ready=lambda: detector_ready,
        on_error=on_error,
    )
    return controller, drone, clock


def started(
    *,
    settings: TrackingSettings | None = None,
    kind: DetectorKind = DetectorKind.OPENCV,
    detector_ready: bool = True,
    on_error=None,
) -> tuple[TrackingController, FakeDroneAdapter, Clock]:
    controller, drone, clock = make_controller(
        settings=settings,
        kind=kind,
        detector_ready=detector_ready,
        on_error=on_error,
    )
    assert controller.start(flight_snapshot()) == ""
    return controller, drone, clock


def test_the_vlm_cannot_be_constructed_into_a_tracking_controller():
    drone = FakeDroneAdapter()

    with pytest.raises(ValueError, match="advisory"):
        TrackingController(drone, detector_kind=DetectorKind.VLM)


@pytest.mark.parametrize("kind", [DetectorKind.OPENCV, DetectorKind.YOLO])
def test_opencv_and_yolo_are_accepted(kind):
    controller, _, _ = make_controller(kind=kind)
    assert controller.detector_kind is kind


def test_start_refuses_without_connection_arming_dry_run_or_manual_flight():
    disconnected = TrackingController(
        FakeDroneAdapter(), detector_kind=DetectorKind.OPENCV
    )
    assert "Connect" in disconnected.start(flight_snapshot())

    controller, drone, _ = make_controller()
    assert "manual control" in controller.start(
        flight_snapshot(state=SafetyState.ARMED)
    )
    assert "not armed" in controller.start(flight_snapshot(armed=False))
    assert "dry run" in controller.start(flight_snapshot(dry_run=()))
    assert controller.start(flight_snapshot()) == ""
    assert controller.active is True
    assert drone.commands == ("connect",)


def test_a_not_ready_detector_refuses_the_session():
    controller, _, _ = make_controller(detector_ready=False)

    assert "not ready" in controller.start(flight_snapshot())
    assert controller.active is False


def test_a_centred_target_inside_the_deadband_sends_nothing():
    errors: list[float] = []
    controller, _, clock = started(on_error=errors.append)

    update = controller.process(
        detection_result(0.54, processed_at=clock.now), now=clock.now
    )

    assert update.centered is True
    assert update.command is None
    assert update.error == pytest.approx(0.04)
    assert errors == [pytest.approx(0.04)]


def test_a_target_to_the_left_yaws_counter_clockwise():
    controller, _, clock = started()

    update = controller.process(
        detection_result(0.25, processed_at=clock.now), now=clock.now
    )

    assert update.command is not None
    assert update.command.direction == "counter_clockwise"
    assert update.command.degrees == 8  # 0.25 * 30, within 5..20
    assert update.command.error == pytest.approx(-0.25)


def test_a_target_to_the_right_yaws_clockwise():
    controller, _, clock = started()

    update = controller.process(
        detection_result(0.80, processed_at=clock.now), now=clock.now
    )

    assert update.command is not None
    assert update.command.direction == "clockwise"
    assert update.command.degrees == 9


def test_yaw_output_is_saturated_at_the_configured_maximum():
    settings = TrackingSettings(gain_deg_per_unit=100.0, max_step_deg=20)
    controller, _, clock = started(settings=settings)

    update = controller.process(
        detection_result(0.95, processed_at=clock.now), now=clock.now
    )

    assert update.command is not None
    assert update.command.degrees == 20


def test_commands_are_rate_limited():
    controller, _, clock = started()

    first = controller.process(
        detection_result(0.20, processed_at=clock.now), now=clock.now
    )
    second = controller.process(
        detection_result(0.20, processed_at=clock.now), now=clock.now
    )
    clock.advance(0.61)
    third = controller.process(
        detection_result(0.20, processed_at=clock.now), now=clock.now
    )

    assert first.command is not None
    assert second.command is None
    assert second.rate_limited is True
    assert third.command is not None


def test_stale_detections_stop_the_session():
    controller, _, clock = started()

    update = controller.process(
        detection_result(0.20, processed_at=clock.now - 0.6), now=clock.now
    )

    assert update.stopped is True
    assert "stale" in update.stop_reason
    assert controller.active is False
    assert "still airborne" in controller.last_stop_reason


def test_a_detector_failure_stops_the_session():
    controller, _, clock = started()

    update = controller.process(
        detection_result(0.20, processed_at=clock.now, error="inference failed"),
        now=clock.now,
    )

    assert update.stopped is True
    assert "detector failed" in update.stop_reason


def test_target_loss_stops_corrections_immediately_then_ends_the_session():
    controller, _, clock = started(settings=TrackingSettings(max_missed_results=3))

    first = controller.process(
        detection_result(0.20, processed_at=clock.now, detections=0), now=clock.now
    )
    second = controller.process(
        detection_result(0.20, processed_at=clock.now, detections=0), now=clock.now
    )
    third = controller.process(
        detection_result(0.20, processed_at=clock.now, detections=0), now=clock.now
    )

    assert first.command is None and first.target_lost is True
    assert second.command is None and second.target_lost is True
    assert third.stopped is True
    assert "Target lost" in third.stop_reason
    assert controller.active is False


def test_the_session_limit_ends_tracking_even_with_a_fresh_target():
    controller, _, clock = started()
    clock.advance(60.0)

    update = controller.check_health(now=clock.now)

    assert update.stopped is True
    assert "limit" in update.stop_reason
    assert controller.active is False


def test_configured_limits_cap_the_session_length():
    clock = Clock()
    drone = FakeDroneAdapter()
    drone.connect()
    controller = TrackingController(
        drone,
        detector_kind=DetectorKind.OPENCV,
        settings=TrackingSettings(session_limit_s=600.0),
        limits=SafetyLimits(max_tracking_session_s=30),
        clock=clock,
    )

    assert controller.start(flight_snapshot()) == ""
    clock.advance(30.0)
    update = controller.check_health(now=clock.now)

    assert update.stopped is True


def test_no_result_arriving_for_too_long_stops_the_session():
    controller, _, clock = started()

    clock.advance(0.6)
    update = controller.check_health(now=clock.now)

    assert update.stopped is True
    assert "No fresh detector result" in update.stop_reason


def test_results_from_another_detector_are_ignored():
    controller, _, clock = started()

    update = controller.process(
        detection_result(
            0.20, kind=DetectorKind.VLM, processed_at=clock.now
        ),
        now=clock.now,
    )

    assert update == TrackingUpdate()
    assert controller.active is True


def test_a_mixed_result_uses_the_largest_normalized_box():
    controller, _, clock = started()
    small = Detection("small", BoundingBox(0.80, 0.80, 0.05, 0.05))
    large = Detection("large", BoundingBox(0.05, 0.30, 0.20, 0.30))
    result = DetectionResult(
        detector_name="Test detector",
        kind=DetectorKind.OPENCV,
        detections=(small, large),
        frame_timestamp=clock.now,
        processed_at=clock.now,
    )

    update = controller.process(result, now=clock.now)

    assert update.error == pytest.approx(-0.35)  # centre of the large box
    assert update.command is not None
    assert update.command.direction == "counter_clockwise"


# -- pure yaw formula --------------------------------------------------------


def test_yaw_command_for_error_is_deadband_aware():
    assert yaw_command_for_error(0.10) is None
    assert yaw_command_for_error(-0.05) is None

    left = yaw_command_for_error(-0.30)
    right = yaw_command_for_error(0.30)

    assert left is not None and left.direction == "counter_clockwise"
    assert right is not None and right.direction == "clockwise"
    assert left.degrees == 9  # round(0.30 * 30)
    assert right.degrees == 9


def test_yaw_command_for_error_clamps_to_the_step_limits():
    small = yaw_command_for_error(0.11)  # round(3.3) -> clamped up to 5
    large = yaw_command_for_error(0.49)  # round(14.7) is inside; use a high gain

    assert small is not None and small.degrees == 5
    assert large is not None and large.degrees == 15

    aggressive = TrackingSettings(gain_deg_per_unit=100.0)
    capped = yaw_command_for_error(0.49, aggressive)
    assert capped is not None and capped.degrees == 20
