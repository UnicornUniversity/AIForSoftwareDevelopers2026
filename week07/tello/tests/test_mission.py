"""Six-segment mission: editable plan, limits, ordering, cancellation."""

from __future__ import annotations

import pytest
from tello_doubles import FakeClock

from drone_vision_lab.config import CONSERVATIVE_LIMITS, SafetyLimits
from drone_vision_lab.domain import CommandResult, CommandStatus, Telemetry
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.mission import (
    MissionOutcome,
    MissionPlan,
    MissionRunner,
    MissionSegment,
    SegmentAction,
    default_mission,
    estimated_duration_s,
    validate_mission,
)


def plan_with(**overrides: MissionSegment) -> MissionPlan:
    plan = default_mission()
    for index, segment in overrides.items():
        plan = plan.replace_segment(int(index), segment)
    return plan


def sent(drone: FakeDroneAdapter) -> tuple[str, ...]:
    """Commands after the connection handshake."""
    return tuple(command for command in drone.commands if command != "connect")


def connected_fake() -> FakeDroneAdapter:
    drone = FakeDroneAdapter()
    assert drone.connect().ok
    return drone


def make_runner(
    drone: FakeDroneAdapter,
    plan: MissionPlan | None = None,
    *,
    telemetry=None,
    clock: FakeClock | None = None,
) -> MissionRunner:
    """A runner on a fake clock, so the takeoff settle costs no real seconds."""
    clock = clock or FakeClock()
    return MissionRunner(
        drone,
        plan or default_mission(),
        telemetry=telemetry,
        clock=clock,
        sleep=clock.sleep,
    )


def test_default_mission_has_the_six_ordered_segments():
    plan = default_mission()

    assert [segment.action for segment in plan.segments] == [
        SegmentAction.TAKEOFF,
        SegmentAction.LEFT,
        SegmentAction.FORWARD,
        SegmentAction.RIGHT,
        SegmentAction.BACK,
        SegmentAction.LAND,
    ]
    assert validate_mission(plan) == ()


def test_a_plan_in_the_wrong_order_is_refused_at_construction():
    segments = list(default_mission().segments)
    segments[1], segments[2] = segments[2], segments[1]

    with pytest.raises(ValueError):
        MissionPlan(segments=tuple(segments))


def test_default_plan_is_short_enough_and_has_a_conservative_estimate():
    plan = default_mission()

    assert estimated_duration_s(plan) < CONSERVATIVE_LIMITS.max_mission_duration_s


def test_out_of_limit_segments_produce_named_issues():
    plan = plan_with(
        **{
            "1": MissionSegment(SegmentAction.LEFT, 150, 20),
            "2": MissionSegment(SegmentAction.FORWARD, 10, 20),
            "3": MissionSegment(SegmentAction.RIGHT, 60, 60),
            "4": MissionSegment(SegmentAction.BACK, 60, 20, pause_s=11),
        }
    )

    issues = validate_mission(plan)
    messages = " | ".join(issue.describe() for issue in issues)

    assert "Segment 2: distance 150 cm exceeds" in messages
    assert "Segment 3: distance must be within 20..500 cm" in messages
    assert "Segment 4: speed 60 cm/s exceeds" in messages
    assert "Segment 5: pause must be within 0..10 s" in messages


def test_takeoff_climb_is_bounded_by_the_altitude_limit():
    plan = plan_with(**{"0": MissionSegment(SegmentAction.TAKEOFF, 200)})

    issues = validate_mission(plan)

    assert any("configured altitude limit" in issue.message for issue in issues)


def test_an_overlong_estimate_is_refused():
    limits = SafetyLimits(max_mission_duration_s=30)
    plan = plan_with(
        **{
            "1": MissionSegment(SegmentAction.LEFT, 100, 20, pause_s=5),
            "2": MissionSegment(SegmentAction.FORWARD, 100, 20, pause_s=5),
            "3": MissionSegment(SegmentAction.RIGHT, 100, 20, pause_s=5),
            "4": MissionSegment(SegmentAction.BACK, 100, 20, pause_s=5),
        }
    )

    issues = validate_mission(plan, limits)

    assert any("duration" in issue.message for issue in issues)
    assert validate_mission(plan, CONSERVATIVE_LIMITS) == ()


def test_mission_requires_explicit_confirmation_and_sends_nothing():
    drone = connected_fake()
    runner = make_runner(drone)

    result = runner.run(operator_confirmed=False)

    assert result.outcome is MissionOutcome.REJECTED
    assert "confirmation" in result.reason
    assert sent(drone) == ()


def test_an_invalid_plan_is_rejected_before_transmission():
    drone = connected_fake()
    plan = plan_with(**{"1": MissionSegment(SegmentAction.LEFT, 150, 20)})

    result = MissionRunner(drone, plan).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "safety limits" in result.reason
    assert sent(drone) == ()


def test_a_disconnected_aircraft_is_rejected():
    drone = FakeDroneAdapter()

    result = MissionRunner(drone, default_mission()).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "Connect" in result.reason
    assert sent(drone) == ()


def test_low_battery_blocks_takeoff():
    drone = connected_fake()
    drone.set_battery(9)

    result = MissionRunner(drone, default_mission()).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "takeoff minimum" in result.reason
    assert sent(drone) == ()


def test_mission_commands_follow_the_plan_in_order():
    drone = connected_fake()
    plan = plan_with(
        **{
            "0": MissionSegment(SegmentAction.TAKEOFF, 20),
            "1": MissionSegment(SegmentAction.LEFT, 30, 20),
            "2": MissionSegment(SegmentAction.FORWARD, 40, 20),
            "3": MissionSegment(SegmentAction.RIGHT, 50, 20),
            "4": MissionSegment(SegmentAction.BACK, 60, 20),
        }
    )

    result = make_runner(drone, plan).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone) == (
        "takeoff",
        "up 20",
        "left 30 20",
        "forward 40 20",
        "right 50 20",
        "back 60 20",
        "land",
    )
    assert "visual confirmation" in result.reason


def test_stopping_does_not_send_a_landing_command():
    class CancellingDrone(FakeDroneAdapter):
        runner: MissionRunner

        def move(self, direction, distance_cm, speed=None, timeout=10.0):
            result = super().move(direction, distance_cm, speed, timeout)
            if len(self.commands) == 3:
                self.runner.cancel("Stopped for the test")
            return result

    drone = CancellingDrone()
    assert drone.connect().ok
    runner = make_runner(drone)
    drone.runner = runner

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert "Stopped for the test" in result.reason
    assert "land" not in sent(drone)
    assert len(result.commands) == 2


def test_cancelling_before_the_first_command_sends_nothing():
    drone = connected_fake()
    runner = MissionRunner(drone, default_mission())
    runner.cancel()

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert sent(drone) == ()


def test_a_refused_takeoff_says_the_mission_did_not_lift_off():
    drone = connected_fake()

    def refused(timeout: float = 20.0) -> CommandResult:
        return CommandResult(
            "takeoff",
            CommandStatus.FAILED,
            "The aircraft refused the command (error).",
        )

    drone.takeoff = refused  # type: ignore[method-assign]

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "Segment 1 (takeoff) did not succeed" in result.reason
    assert "refused the takeoff" in result.reason
    assert "may still be airborne" not in result.reason
    assert ".." not in result.reason
    # The refused takeoff was the only command attempted; nothing else was sent.
    assert sent(drone) == ()


def test_a_failed_command_aborts_the_rest_and_says_the_aircraft_may_be_airborne():
    drone = connected_fake()

    original_move = drone.move

    def failing_move(direction, distance_cm, speed=None, timeout=10.0):
        if direction == "forward":
            return CommandResult(
                "forward",
                CommandStatus.FAILED,
                "The aircraft refused the command (error).",
            )
        return original_move(direction, distance_cm, speed, timeout)

    drone.move = failing_move  # type: ignore[method-assign]

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "may still be airborne" in result.reason
    assert "back" not in sent(drone)
    assert "land" not in sent(drone)


def test_a_battery_drop_mid_mission_aborts_before_the_next_movement():
    drone = connected_fake()
    clock = FakeClock()
    batteries = iter([80, 15])

    def telemetry() -> Telemetry:
        return Telemetry(battery_percent=next(batteries), received_at=clock.now)

    runner = make_runner(drone, telemetry=telemetry, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "in-flight minimum" in result.reason
    assert sent(drone) == ("takeoff",)


def test_stale_telemetry_blocks_the_mission_before_takeoff():
    drone = connected_fake()
    clock = FakeClock(now=10.0)
    stale = Telemetry(battery_percent=80, received_at=0.0)
    runner = make_runner(drone, telemetry=lambda: stale, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "stale" in result.reason
    assert sent(drone) == ()


def test_the_takeoff_is_settled_before_the_first_follow_up_command():
    drone = connected_fake()
    plan = plan_with(**{"0": MissionSegment(SegmentAction.TAKEOFF, 20)})
    clock = FakeClock()
    runner = make_runner(drone, plan, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone)[:2] == ("takeoff", "up 20")
    assert clock.now >= CONSERVATIVE_LIMITS.takeoff_settle_s - 1e-6


def test_stopping_during_the_takeoff_settle_skips_the_climb():
    drone = connected_fake()
    plan = plan_with(**{"0": MissionSegment(SegmentAction.TAKEOFF, 20)})
    clock = FakeClock()
    holder: dict[str, MissionRunner] = {}

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        holder["runner"].cancel("Stopped during the takeoff settle.")

    runner = MissionRunner(drone, plan, clock=clock, sleep=sleep)
    holder["runner"] = runner

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert "settle" in result.reason
    assert sent(drone) == ("takeoff",)


def test_a_stale_low_battery_reading_mid_mission_does_not_abort_the_flight():
    drone = connected_fake()
    clock = FakeClock()
    batteries = iter([80, 80, 15, 80, 80])

    def telemetry() -> Telemetry:
        battery = next(batteries)
        # The 15% reading is old: it is the last thing the aircraft said, not
        # evidence about the present, so it must not abort a valid flight.
        received_at = 0.0 if battery == 15 else clock.now
        return Telemetry(battery_percent=battery, received_at=received_at)

    runner = make_runner(drone, telemetry=telemetry, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED


def test_takeoff_then_five_seconds_of_stale_telemetry_still_lands():
    drone = connected_fake()
    clock = FakeClock()
    # The only report is the one that allowed takeoff. By the time the first
    # movement is considered it is older than the freshness limit, and it stays
    # that way for the rest of the flight: the aircraft has gone quiet, not
    # reported a low battery. The mission must keep flying and still send land.
    last_report = Telemetry(battery_percent=80, height_cm=100, received_at=0.0)
    runner = make_runner(drone, telemetry=lambda: last_report, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert clock.now >= CONSERVATIVE_LIMITS.takeoff_settle_s
    assert clock.now - last_report.received_at > CONSERVATIVE_LIMITS.telemetry_max_age_s
    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone) == (
        "takeoff",
        "left 100 30",
        "forward 100 30",
        "right 100 30",
        "back 100 30",
        "land",
    )
    assert "visual confirmation" in result.reason
