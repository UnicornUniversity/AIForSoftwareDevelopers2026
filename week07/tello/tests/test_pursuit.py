"""The advisory-only pursuit advisor: decisions, stops and disclaimers.

No Qt, no drone and no model. The advisor has no drone adapter at all, and the
tests assert that its output is a message, never a command sent anywhere.
"""

from __future__ import annotations

import pytest

import drone_vision_lab.pursuit as pursuit_module
from drone_vision_lab.domain import BoundingBox, Detection, DetectionResult, DetectorKind
from drone_vision_lab.pursuit import PursuitAction, PursuitAdvisor
from drone_vision_lab.tracking import TrackingSettings


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def result_at(
    center_x: float | None,
    *,
    now: float,
    kind: DetectorKind = DetectorKind.YOLO,
    error: str | None = None,
    label: str = "apple",
) -> DetectionResult:
    detections = ()
    if center_x is not None:
        detections = (
            Detection(
                label=label,
                box=BoundingBox(center_x - 0.05, 0.4, 0.1, 0.2),
                confidence=0.9,
            ),
        )
    return DetectionResult(
        detector_name="YOLO",
        kind=kind,
        detections=detections,
        frame_timestamp=now,
        processed_at=now,
        error=error,
    )


def started(
    *,
    settings: TrackingSettings | None = None,
    clock: Clock | None = None,
) -> tuple[PursuitAdvisor, Clock]:
    clock = clock or Clock()
    advisor = PursuitAdvisor(settings=settings or TrackingSettings(), clock=clock)
    advisor.start(now=clock.now)
    return advisor, clock


def test_the_vlm_cannot_be_constructed_into_the_advisor():
    with pytest.raises(ValueError, match="advisory"):
        PursuitAdvisor(detector_kind=DetectorKind.VLM)


def test_the_advisor_has_no_drone_and_no_way_to_send():
    assert not hasattr(pursuit_module, "DroneAdapter")
    advisor, _ = started()
    assert not hasattr(advisor, "drone")
    assert not hasattr(advisor, "_drone")


def test_it_is_idle_until_started():
    advisor = PursuitAdvisor(clock=Clock())

    decision = advisor.process(result_at(0.2, now=100.0), now=100.0)

    assert decision.action is PursuitAction.IDLE
    assert advisor.active is False


def test_start_waits_for_the_first_detection():
    advisor, _ = started()

    assert advisor.active is True
    assert advisor.last_decision is not None
    assert advisor.last_decision.action is PursuitAction.IDLE
    assert "Watching" in advisor.last_decision.message


def test_a_centred_target_holds_heading():
    advisor, clock = started()

    decision = advisor.process(result_at(0.54, now=clock.now), now=clock.now)

    assert decision.action is PursuitAction.CENTERED
    assert decision.command is None
    assert decision.error is not None and abs(decision.error - 0.04) < 1e-9
    assert decision.message == "Apple is centered → hold heading."


def test_a_target_to_the_left_asks_for_a_left_yaw():
    advisor, clock = started()

    decision = advisor.process(result_at(0.25, now=clock.now), now=clock.now)

    assert decision.action is PursuitAction.YAW_LEFT
    assert decision.command is not None
    assert decision.command.direction == "counter_clockwise"
    assert decision.command.degrees == 8  # round(0.25 * 30)
    assert decision.message == "Apple is left of center → yaw left 8°."


def test_a_target_to_the_right_asks_for_a_right_yaw():
    advisor, clock = started()

    decision = advisor.process(result_at(0.80, now=clock.now), now=clock.now)

    assert decision.action is PursuitAction.YAW_RIGHT
    assert decision.command is not None
    assert decision.command.direction == "clockwise"
    assert decision.command.degrees == 9
    assert decision.message == "Apple is right of center → yaw right 9°."


def test_yaw_steps_respect_the_minimum_and_maximum():
    settings = TrackingSettings(gain_deg_per_unit=100.0, max_step_deg=20)
    advisor, clock = started(settings=settings)

    far = advisor.process(result_at(0.95, now=clock.now), now=clock.now)
    small = advisor.process(
        result_at(0.39, now=clock.now + 1.0), now=clock.now + 1.0
    )

    assert far.command is not None and far.command.degrees == 20
    # Error 0.11 * 100 -> 11, inside the limits; use the default gain for the floor.
    assert small.command is not None and small.command.degrees == 11

    default_gain, clock = started()
    floor = default_gain.process(
        result_at(0.39, now=clock.now), now=clock.now
    )  # 0.11 * 30 -> 3.3, clamped up to 5
    assert floor.command is not None and floor.command.degrees == 5


def test_yaw_advisories_are_rate_limited_and_do_not_slide_the_window():
    advisor, clock = started()

    first = advisor.process(result_at(0.20, now=clock.now), now=clock.now)
    second = advisor.process(result_at(0.20, now=clock.now), now=clock.now)
    clock.advance(0.40)
    third = advisor.process(
        result_at(0.20, now=clock.now), now=clock.now
    )  # still inside 0.6 s from the first
    clock.advance(0.21)
    fourth = advisor.process(result_at(0.20, now=clock.now), now=clock.now)

    assert first.action is PursuitAction.YAW_LEFT
    assert second.action is PursuitAction.HOLDING
    assert second.rate_limited is True
    assert second.command is None
    assert third.action is PursuitAction.HOLDING
    assert fourth.action is PursuitAction.YAW_LEFT


def test_misses_accumulate_then_stop_and_a_detection_resets_them():
    advisor, clock = started(settings=TrackingSettings(max_missed_results=3))

    first = advisor.process(result_at(None, now=clock.now), now=clock.now)
    second = advisor.process(result_at(None, now=clock.now), now=clock.now)
    seen = advisor.process(result_at(0.50, now=clock.now), now=clock.now)
    after = advisor.process(result_at(None, now=clock.now), now=clock.now)
    third = advisor.process(result_at(None, now=clock.now), now=clock.now)
    final = advisor.process(result_at(None, now=clock.now), now=clock.now)

    assert first.action is PursuitAction.NO_TARGET
    assert first.misses == 1
    assert first.message == "No apple detected (1 of 3 misses) → hold heading."
    assert second.misses == 2
    assert seen.action is PursuitAction.CENTERED
    assert after.misses == 1
    assert third.misses == 2
    assert final.action is PursuitAction.STOPPED
    assert "Target lost after 3 consecutive misses" in final.message
    assert advisor.active is False


def test_a_stale_result_stops_the_advisory():
    advisor, clock = started()

    decision = advisor.process(
        result_at(0.20, now=clock.now - 0.6), now=clock.now
    )

    assert decision.action is PursuitAction.STOPPED
    assert "stale" in decision.message
    assert advisor.active is False


def test_a_detector_failure_stops_the_advisory():
    advisor, clock = started()

    decision = advisor.process(
        result_at(0.20, now=clock.now, error="inference failed"), now=clock.now
    )

    assert decision.action is PursuitAction.STOPPED
    assert "The detector failed: inference failed" in decision.message


def test_check_health_stops_after_results_stop_arriving():
    advisor, clock = started()

    advisor.process(result_at(0.50, now=clock.now), now=clock.now)
    healthy = advisor.check_health(now=clock.now)
    clock.advance(0.6)
    stale = advisor.check_health(now=clock.now)

    assert healthy.action is PursuitAction.CENTERED
    assert stale.action is PursuitAction.STOPPED
    assert "No fresh detector result" in stale.message


def test_check_health_waits_for_the_first_result_without_stopping():
    advisor, clock = started()

    clock.advance(10.0)
    decision = advisor.check_health(now=clock.now)

    assert decision.action is PursuitAction.IDLE
    assert advisor.active is True


def test_stop_is_sticky_until_start_again():
    advisor, clock = started()

    stopped = advisor.stop("Source stopped")
    later = advisor.process(result_at(0.20, now=clock.now), now=clock.now)
    health = advisor.check_health(now=clock.now)

    assert stopped.action is PursuitAction.STOPPED
    assert stopped.message == "Source stopped — advisory stopped."
    assert "Source stopped" in advisor.stop_reason
    assert later.action is PursuitAction.STOPPED
    assert health.action is PursuitAction.STOPPED

    advisor.start(now=clock.now)
    resumed = advisor.process(result_at(0.20, now=clock.now), now=clock.now)
    assert resumed.action is PursuitAction.YAW_LEFT


def test_a_default_stop_reads_correctly():
    advisor, _ = started()

    decision = advisor.stop()

    assert decision.message == "Advisory stopped by the operator — advisory stopped."


def test_every_banner_carries_the_advisory_disclaimer():
    advisor, clock = started()

    centred = advisor.process(result_at(0.50, now=clock.now), now=clock.now)
    stopped = advisor.stop("Source stopped")

    assert centred.banner.startswith("ADVISORY ONLY — no command is sent.")
    assert centred.banner.endswith(centred.message)
    assert stopped.banner.startswith("ADVISORY ONLY — no command was sent.")
    assert stopped.banner.endswith(stopped.message)


def test_results_from_another_detector_are_ignored():
    advisor = PursuitAdvisor(clock=Clock())
    advisor.start(now=100.0)

    decision = advisor.process(
        result_at(0.20, now=100.0, kind=DetectorKind.OPENCV), now=100.0
    )

    assert decision.action is PursuitAction.IDLE
    assert advisor.active is True


def test_the_largest_navigable_box_is_chosen():
    advisor, clock = started()
    result = DetectionResult(
        detector_name="YOLO",
        kind=DetectorKind.YOLO,
        detections=(
            Detection("apple", BoundingBox(0.80, 0.80, 0.05, 0.05)),
            Detection("apple", BoundingBox(0.05, 0.30, 0.20, 0.30)),
        ),
        frame_timestamp=clock.now,
        processed_at=clock.now,
    )

    decision = advisor.process(result, now=clock.now)

    assert decision.error is not None and abs(decision.error + 0.35) < 1e-9
    assert decision.action is PursuitAction.YAW_LEFT
    assert decision.target_box is not None
    assert decision.target_box.area == 0.06


def test_the_target_label_drives_the_message():
    advisor, clock = started()

    advisor.set_target_label("sports ball")
    decision = advisor.process(
        result_at(0.50, now=clock.now, label="sports ball"), now=clock.now
    )

    assert advisor.target_label == "sports ball"
    assert decision.message == "Sports ball is centered → hold heading."
