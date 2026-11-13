"""Preset programs: definitions, limits, ordering, holds and cancellation."""

from __future__ import annotations

import logging

from tello_doubles import FakeClock

from drone_vision_lab.config import CONSERVATIVE_LIMITS, SafetyLimits
from drone_vision_lab.domain import CommandResult, CommandStatus, Telemetry
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.mission import MissionOutcome
from drone_vision_lab.preset_missions import (
    APPLE_CLIMB_CM,
    KEEPALIVE_COMMAND,
    KEEPALIVE_INTERVAL_S,
    OBSERVATION_MAX_S,
    PRESET_APPLE_RECOGNITION,
    PRESET_PROGRAMS,
    PRESET_SQUARE,
    PRESET_TAKEOFF_HOVER_LAND,
    PresetAction,
    PresetProgram,
    PresetRunner,
    PresetStep,
    estimated_preset_duration_s,
    validate_preset,
)


def sent(drone: FakeDroneAdapter) -> tuple[str, ...]:
    """Commands after the connection handshake."""
    return tuple(command for command in drone.commands if command != "connect")


def connected_fake() -> FakeDroneAdapter:
    drone = FakeDroneAdapter()
    assert drone.connect().ok
    return drone


def make_runner(
    drone: FakeDroneAdapter,
    program: PresetProgram | None = None,
    *,
    telemetry=None,
    clock: FakeClock | None = None,
    takeoff_settle_s: float | None = None,
    sleep=None,
) -> PresetRunner:
    """A runner on a fake clock, so waits cost no real seconds."""
    clock = clock or FakeClock()
    return PresetRunner(
        drone,
        program or PRESET_TAKEOFF_HOVER_LAND,
        telemetry=telemetry,
        clock=clock,
        sleep=sleep or clock.sleep,
        takeoff_settle_s=takeoff_settle_s,
    )


def test_the_bundled_programs_are_in_the_expected_order():
    assert PRESET_PROGRAMS == (
        PRESET_TAKEOFF_HOVER_LAND,
        PRESET_SQUARE,
        PRESET_APPLE_RECOGNITION,
    )


def test_the_first_preset_takes_off_hovers_for_three_seconds_and_lands():
    program = PRESET_TAKEOFF_HOVER_LAND

    assert [step.action for step in program.steps] == [
        PresetAction.TAKEOFF,
        PresetAction.HOLD,
        PresetAction.LAND,
    ]
    assert program.steps[1].hold_s == 3.0
    assert program.steps[1].sdk_command is None
    assert validate_preset(program) == ()


def test_the_square_preset_uses_four_left_turns_and_four_twenty_centimetre_legs():
    program = PRESET_SQUARE

    assert [step.action for step in program.steps] == [
        PresetAction.TAKEOFF,
        PresetAction.YAW_LEFT,
        PresetAction.FORWARD,
        PresetAction.YAW_LEFT,
        PresetAction.FORWARD,
        PresetAction.YAW_LEFT,
        PresetAction.FORWARD,
        PresetAction.YAW_LEFT,
        PresetAction.FORWARD,
        PresetAction.LAND,
    ]
    assert [step.degrees for step in program.steps if step.action.is_yaw] == [90] * 4
    assert [step.distance_cm for step in program.steps if step.action.is_translation] == [30] * 4
    assert all(step.speed_cm_s == 30 for step in program.steps if step.action.is_translation)
    assert validate_preset(program) == ()


def test_the_square_preset_uses_thirty_centimetre_legs_and_states_the_minimum():
    note = PRESET_SQUARE.note

    assert "30 cm" in note
    assert "minimum" in note
    assert "20 cm" in note


# -- observation program -----------------------------------------------------


def test_the_apple_preset_takes_off_climbs_observes_for_ninety_seconds_and_lands():
    program = PRESET_APPLE_RECOGNITION

    assert [step.action for step in program.steps] == [
        PresetAction.TAKEOFF,
        PresetAction.CLIMB,
        PresetAction.OBSERVE,
        PresetAction.LAND,
    ]
    observe = program.steps[2]
    assert observe.hold_s == OBSERVATION_MAX_S == 90.0
    assert observe.sdk_command is None
    assert observe.action.is_observation is True
    assert program.has_observation is True
    assert validate_preset(program) == ()


def test_the_apple_preset_climbs_fifty_centimetres_to_about_one_and_a_half_metres():
    climb = PRESET_APPLE_RECOGNITION.steps[1]

    assert APPLE_CLIMB_CM == 50
    assert climb.distance_cm == 50
    # The SDK's ``up x`` has no speed argument; the step carries none.
    assert climb.speed_cm_s is None
    assert climb.sdk_command == "up 50"
    assert climb.action.label == "Climb"
    assert "takeoff hover height" in climb.detail
    # About one metre of takeoff hover plus the climb.
    assert "1.5 m" in PRESET_APPLE_RECOGNITION.summary
    assert "1.5 m" in PRESET_APPLE_RECOGNITION.note


def test_the_apple_preset_note_says_the_height_is_approximate():
    note = PRESET_APPLE_RECOGNITION.note

    assert "approximate" in note
    assert "no altitude setpoint" in note


def test_the_apple_preset_note_names_the_emergency_land_and_fallback_landing():
    note = PRESET_APPLE_RECOGNITION.note

    assert "EMERGENCY LAND" in note
    assert "not sent" in note
    assert "fallback" in note
    assert "90 s" in note


def test_a_program_without_an_observation_does_not_ask_for_the_camera():
    assert PRESET_TAKEOFF_HOVER_LAND.has_observation is False
    assert PRESET_SQUARE.has_observation is False


def test_an_observation_takes_no_distance_speed_or_turn_angle():
    program = PresetProgram(
        program_id="bad-observation",
        title="Bad observation",
        summary="Fields the step cannot use.",
        steps=(
            PresetStep.takeoff(),
            PresetStep(PresetAction.OBSERVE, distance_cm=30, speed_cm_s=30, hold_s=5.0),
            PresetStep.land(),
        ),
    )

    messages = " | ".join(issue.describe() for issue in validate_preset(program))

    assert "Step 2: an observation takes no distance, speed or turn angle." in messages


def test_an_observation_outside_one_to_ninety_seconds_is_rejected():
    too_short = PresetProgram(
        program_id="short-observation",
        title="Short observation",
        summary="Below the observation minimum.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.observe(0.5),
            PresetStep.land(),
        ),
    )
    too_long = PresetProgram(
        program_id="long-observation",
        title="Long observation",
        summary="Above the observation maximum.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.observe(91.0),
            PresetStep.land(),
        ),
    )

    assert any(
        "observation must be within 1..90 s" in issue.message
        for issue in validate_preset(too_short)
    )
    assert any(
        "observation must be within 1..90 s" in issue.message
        for issue in validate_preset(too_long)
    )


def test_an_observation_sends_only_keepalives_between_the_climb_and_the_landing():
    drone = connected_fake()
    clock = FakeClock()
    runner = PresetRunner(
        drone,
        PRESET_APPLE_RECOGNITION,
        telemetry=lambda: Telemetry(battery_percent=80, received_at=clock.now),
        clock=clock,
        sleep=clock.sleep,
    )

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    commands = sent(drone)
    # ``up 50`` is the only movement. The observation sends no flight command,
    # but a bare ``command`` keepalive every 5 s stops the Tello landing itself
    # after 15 s without one. The fallback ``land`` ends the observation.
    assert commands[:2] == ("takeoff", "up 50")
    assert commands[-1] == "land"
    keepalives = commands[2:-1]
    assert set(keepalives) == {KEEPALIVE_COMMAND}
    # 5, 10, ... 85 s: the slot at 90 s is the deadline, where ``land`` is next.
    assert len(keepalives) == int(OBSERVATION_MAX_S // KEEPALIVE_INTERVAL_S) - 1
    # The full observation elapsed before the fallback landing.
    assert clock.now >= OBSERVATION_MAX_S + CONSERVATIVE_LIMITS.takeoff_settle_s


def test_a_long_hold_sends_keepalives_but_a_short_hold_does_not():
    long_hold = PresetProgram(
        program_id="long-hold",
        title="Long hold",
        summary="A hold longer than the Tello's no-command limit.",
        steps=(PresetStep.takeoff(), PresetStep.hold(20.0), PresetStep.land()),
    )
    drone = connected_fake()
    clock = FakeClock()
    runner = make_runner(drone, program=long_hold, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    # The 3 s hold in the hover preset is shorter than the 5 s keepalive
    # interval, so it sends nothing; this 20 s hold must send keepalives.
    assert sent(drone) == ("takeoff", "command", "command", "command", "land")
    hover = connected_fake()
    hover_clock = FakeClock()
    make_runner(hover, clock=hover_clock).run(operator_confirmed=True)
    assert sent(hover) == ("takeoff", "land")


def test_a_failed_keepalive_is_logged_and_the_program_still_lands(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock()
    runner = PresetRunner(
        drone,
        PRESET_APPLE_RECOGNITION,
        telemetry=lambda: Telemetry(battery_percent=80, received_at=clock.now),
        clock=clock,
        sleep=clock.sleep,
    )
    monkeypatch.setattr(
        drone,
        "send_command",
        lambda command, timeout=5.0: CommandResult(
            command,
            CommandStatus.TIMEOUT,
            "No reply from the aircraft",
            requested_at=clock.now,
            completed_at=clock.now,
        ),
    )

    result = runner.run(operator_confirmed=True)

    # A failed keepalive does not abort the program: the Tello's own failsafe
    # landing is safe, and the program still sends its fallback landing.
    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone)[-1] == "land"
    messages = _messages(caplog)
    assert messages.count("Preset keepalive failed") == (
        int(OBSERVATION_MAX_S // KEEPALIVE_INTERVAL_S) - 1
    )
    failures = [
        record
        for record in caplog.records
        if record.getMessage() == "Preset keepalive failed"
    ]
    assert failures[0].levelno == logging.WARNING
    assert failures[0].context["command"] == KEEPALIVE_COMMAND
    assert failures[0].context["status"] == CommandStatus.TIMEOUT.value


def test_the_apple_preset_climbs_after_takeoff_and_before_the_observation():
    drone = connected_fake()
    clock = FakeClock()
    runner = PresetRunner(
        drone,
        PRESET_APPLE_RECOGNITION,
        telemetry=lambda: Telemetry(battery_percent=80, received_at=clock.now),
        clock=clock,
        sleep=clock.sleep,
    )

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    commands = sent(drone)
    assert commands.index("takeoff") < commands.index("up 50") < commands.index("land")
    # No separate ``speed`` command: ``up x`` takes none and the step sets none.
    assert not any(command.startswith("speed ") for command in commands)


def test_a_battery_drop_after_takeoff_aborts_before_the_climb():
    drone = connected_fake()
    clock = FakeClock()
    batteries = iter([80, 15])

    def telemetry() -> Telemetry:
        return Telemetry(battery_percent=next(batteries), received_at=clock.now)

    runner = PresetRunner(
        drone,
        PRESET_APPLE_RECOGNITION,
        telemetry=telemetry,
        clock=clock,
        sleep=clock.sleep,
    )

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "in-flight minimum" in result.reason
    assert sent(drone) == ("takeoff",)


def test_an_observation_is_logged_as_an_observation_not_a_hold(caplog):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock()

    runner = PresetRunner(
        drone,
        PRESET_APPLE_RECOGNITION,
        telemetry=drone.telemetry,
        clock=clock,
        sleep=clock.sleep,
    )
    runner.run(operator_confirmed=True)

    messages = _messages(caplog)
    assert "Preset observation starting" in messages
    assert "Preset observation finished" in messages
    assert "Preset hold starting" not in messages


def test_a_climb_carries_no_speed_hold_or_turn_angle():
    program = PresetProgram(
        program_id="bad-climb",
        title="Bad climb",
        summary="Fields the climb cannot use.",
        steps=(
            PresetStep.takeoff(),
            PresetStep(PresetAction.CLIMB, distance_cm=50, speed_cm_s=30),
            PresetStep.land(),
        ),
    )

    messages = " | ".join(issue.describe() for issue in validate_preset(program))

    assert "Step 2: a climb takes no speed, hold or turn angle." in messages


def test_a_climb_outside_the_sdk_minimum_or_the_altitude_limit_is_rejected():
    too_short = PresetProgram(
        program_id="short-climb",
        title="Short climb",
        summary="Below the movement minimum.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.climb(10),
            PresetStep.land(),
        ),
    )
    too_high = PresetProgram(
        program_id="tall-climb",
        title="Tall climb",
        summary="Above the altitude limit.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.climb(CONSERVATIVE_LIMITS.max_altitude_cm + 10),
            PresetStep.land(),
        ),
    )

    messages = " | ".join(issue.describe() for issue in validate_preset(too_short))
    assert (
        f"climb must be within 20..{CONSERVATIVE_LIMITS.max_altitude_cm} cm"
        in messages
    )
    messages = " | ".join(issue.describe() for issue in validate_preset(too_high))
    assert (
        f"climb must be within 20..{CONSERVATIVE_LIMITS.max_altitude_cm} cm"
        in messages
    )


def test_a_climb_at_the_altitude_limit_itself_is_allowed():
    program = PresetProgram(
        program_id="limit-climb",
        title="Limit climb",
        summary="Exactly the configured limit.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.climb(CONSERVATIVE_LIMITS.max_altitude_cm),
            PresetStep.land(),
        ),
    )

    assert validate_preset(program) == ()


def test_a_ten_centimetre_leg_is_rejected_with_the_sdk_minimum():
    program = PresetProgram(
        program_id="too-short",
        title="Too short",
        summary="A leg the SDK cannot accept.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.forward(10, 30),
            PresetStep.land(),
        ),
    )

    issues = validate_preset(program)

    assert any("20..500 cm" in issue.message for issue in issues)
    assert any("SDK does not accept a shorter movement" in issue.message for issue in issues)


def test_a_program_must_start_with_takeoff_and_end_with_landing():
    missing_start = PresetProgram(
        program_id="no-takeoff",
        title="No takeoff",
        summary="Starts in the air.",
        steps=(PresetStep.hold(1.0), PresetStep.land()),
    )
    missing_end = PresetProgram(
        program_id="no-landing",
        title="No landing",
        summary="Never comes down.",
        steps=(PresetStep.takeoff(), PresetStep.hold(1.0)),
    )

    assert any("start with takeoff" in issue.message for issue in validate_preset(missing_start))
    assert any("end with landing" in issue.message for issue in validate_preset(missing_end))


def test_a_landing_in_the_middle_is_rejected():
    program = PresetProgram(
        program_id="land-early",
        title="Land early",
        summary="An extra landing in the middle.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.land(),
            PresetStep.hold(1.0),
            PresetStep.land(),
        ),
    )

    messages = " | ".join(issue.describe() for issue in validate_preset(program))

    assert "no step may follow it" in messages


def test_out_of_limit_turns_holds_and_movements_are_named():
    program = PresetProgram(
        program_id="bad-values",
        title="Bad values",
        summary="Every field is wrong.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.turn_left(0),
            PresetStep.hold(31.0),
            PresetStep.forward(500, 60),
            PresetStep.land(),
        ),
    )

    messages = " | ".join(issue.describe() for issue in validate_preset(program))

    assert "Step 2: turn must be within 1..360 degrees" in messages
    assert "Step 3: hold must be within 0.1..30 s" in messages
    assert "Step 4: distance 500 cm exceeds the 100 cm segment limit" in messages
    assert "Step 4: speed 60 cm/s exceeds the 50 cm/s limit" in messages


def test_an_overlong_program_is_refused():
    program = PresetProgram(
        program_id="long",
        title="Long",
        summary="Too many holds.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.hold(30.0),
            PresetStep.hold(30.0),
            PresetStep.hold(30.0),
            PresetStep.land(),
        ),
    )

    issues = validate_preset(program, SafetyLimits(max_mission_duration_s=30))

    assert any("duration" in issue.message for issue in issues)
    assert validate_preset(program, CONSERVATIVE_LIMITS) == ()


def test_every_bundled_program_has_a_conservative_time_estimate():
    for program in PRESET_PROGRAMS:
        estimate = estimated_preset_duration_s(program)

        assert 0 < estimate < CONSERVATIVE_LIMITS.max_mission_duration_s


def test_a_preset_requires_explicit_confirmation_and_sends_nothing():
    drone = connected_fake()
    runner = make_runner(drone)

    result = runner.run(operator_confirmed=False)

    assert result.outcome is MissionOutcome.REJECTED
    assert "confirmation" in result.reason
    assert sent(drone) == ()


def test_a_disconnected_aircraft_is_rejected():
    drone = FakeDroneAdapter()

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "Connect" in result.reason
    assert sent(drone) == ()


def test_stale_telemetry_blocks_the_program_before_takeoff():
    drone = connected_fake()
    clock = FakeClock(now=10.0)
    stale = Telemetry(battery_percent=80, received_at=0.0)
    runner = make_runner(drone, telemetry=lambda: stale, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "stale" in result.reason
    assert sent(drone) == ()


def test_low_battery_blocks_takeoff():
    drone = connected_fake()
    drone.set_battery(9)

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.REJECTED
    assert "takeoff minimum" in result.reason
    assert sent(drone) == ()


def test_the_hover_program_sends_no_command_during_the_hold(caplog):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock()
    runner = make_runner(drone, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone) == ("takeoff", "land")
    assert clock.now >= 3.0 + CONSERVATIVE_LIMITS.takeoff_settle_s
    assert "visual confirmation" in result.reason
    finished = next(
        record for record in caplog.records if record.getMessage() == "Preset run finished"
    )
    assert finished.context["landing_confirmed"] is False


def test_a_confirmed_landing_is_reported_as_confirmed(caplog):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = FakeDroneAdapter(confirm_landing=True)
    assert drone.connect().ok

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert "landing was confirmed" in result.reason
    assert "visual confirmation" not in result.reason
    finished = next(
        record for record in caplog.records if record.getMessage() == "Preset run finished"
    )
    assert finished.context["landing_confirmed"] is True


def test_the_square_program_sends_turns_and_legs_in_order():
    drone = connected_fake()
    clock = FakeClock()
    runner = make_runner(drone, PRESET_SQUARE, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone) == (
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


def test_stopping_during_the_hold_does_not_land():
    drone = connected_fake()
    clock = FakeClock()
    holder: dict[str, PresetRunner] = {}

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        holder["runner"].cancel("Stopped during the hold.")

    runner = make_runner(
        drone,
        clock=clock,
        takeoff_settle_s=0.0,
        sleep=sleep,
    )
    holder["runner"] = runner

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert "Stopped during the hold" in result.reason
    assert sent(drone) == ("takeoff",)


def test_stopping_before_the_first_command_sends_nothing():
    drone = connected_fake()
    runner = make_runner(drone)
    runner.cancel()

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert sent(drone) == ()


def test_stopping_during_the_takeoff_settle_skips_the_hold_and_landing():
    drone = connected_fake()
    clock = FakeClock()
    holder: dict[str, PresetRunner] = {}

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        holder["runner"].cancel("Stopped during the takeoff settle.")

    runner = make_runner(drone, clock=clock, sleep=sleep)
    holder["runner"] = runner

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.CANCELLED
    assert "settle" in result.reason
    assert sent(drone) == ("takeoff",)


def test_a_refused_takeoff_names_step_one_and_says_the_program_did_not_lift_off(caplog):
    caplog.set_level(logging.WARNING, logger="drone_vision_lab.preset_missions")
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
    # The failing step is the first one; an off-by-one once reported "Step 2".
    assert "Step 1 (takeoff) did not succeed" in result.reason
    assert "refused the takeoff" in result.reason
    # An explicit refusal is not a lost reply, so the aircraft is not described
    # as possibly airborne by this program.
    assert "may still be airborne" not in result.reason
    assert ".." not in result.reason
    # The refused takeoff was the only command attempted; nothing else was sent.
    assert sent(drone) == ()

    aborted = next(
        record
        for record in caplog.records
        if record.getMessage() == "Preset aborted at a failed step"
    )
    assert aborted.context["step"] == 1
    assert aborted.context["status"] == "failed"
    # The report carries what the aircraft last said, for diagnosing a refusal.
    assert "battery_percent" in aborted.context
    assert "temperature_c" in aborted.context
    assert "height_cm" in aborted.context


def test_a_timed_out_takeoff_keeps_the_unknown_outcome_and_airborne_warning():
    drone = connected_fake()

    def timed_out(timeout: float = 20.0) -> CommandResult:
        return CommandResult(
            "takeoff",
            CommandStatus.TIMEOUT,
            "No reply within the timeout; the outcome is unknown.",
        )

    drone.takeoff = timed_out  # type: ignore[method-assign]

    result = make_runner(drone).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "Step 1 (takeoff) did not succeed" in result.reason
    assert "outcome is unknown" in result.reason
    assert "may still be airborne" in result.reason


def test_a_failed_command_aborts_the_rest_and_says_the_aircraft_may_be_airborne():
    drone = connected_fake()

    original_rotate = drone.rotate

    def failing_rotate(direction, degrees, timeout=10.0):
        if direction == "ccw":
            return CommandResult(
                "ccw",
                CommandStatus.FAILED,
                "The aircraft refused the command (error).",
            )
        return original_rotate(direction, degrees, timeout)

    drone.rotate = failing_rotate  # type: ignore[method-assign]

    result = make_runner(drone, PRESET_SQUARE).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    # The square's second step is the left turn; the number must match the table.
    assert "Step 2 (yaw_left) did not succeed" in result.reason
    assert "may still be airborne" in result.reason
    assert "forward" not in sent(drone)
    assert "land" not in sent(drone)


def test_a_refused_climb_says_the_observation_step_did_not_run():
    """The apple demo exists for the observation; do not make the operator wait
    for a green box that this run can never produce."""
    drone = connected_fake()

    def refused_up(*args, **kwargs) -> CommandResult:
        return CommandResult("up", CommandStatus.FAILED, "error No valid imu")

    drone.move = refused_up  # type: ignore[method-assign]

    result = make_runner(drone, PRESET_APPLE_RECOGNITION).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "Step 2 (up) did not succeed" in result.reason
    assert "The observation step did not run" in result.reason
    assert "land" not in sent(drone)


def test_an_abort_at_the_landing_does_not_claim_the_observation_was_skipped():
    drone = connected_fake()

    def refused_land(timeout: float = 20.0) -> CommandResult:
        return CommandResult(
            "land",
            CommandStatus.FAILED,
            "The aircraft refused the command (error).",
        )

    drone.land = refused_land  # type: ignore[method-assign]

    result = make_runner(drone, PRESET_APPLE_RECOGNITION).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "Step 4 (land) did not succeed" in result.reason
    assert "observation step did not run" not in result.reason


def test_an_aborted_program_logs_the_telemetry_at_failure_time(caplog):
    """The pre-takeoff sample must not be reported as the failure-time height."""
    caplog.set_level(logging.WARNING, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock()
    readings = iter(
        [
            Telemetry(battery_percent=80, height_cm=0, received_at=0.0),  # gates
            Telemetry(
                battery_percent=79,
                height_cm=110,
                temperature_c=66.0,
                received_at=5.0,
            ),  # aborted landing
        ]
    )

    def refused_land(timeout: float = 20.0) -> CommandResult:
        return CommandResult(
            "land",
            CommandStatus.FAILED,
            "The aircraft refused the command (error).",
        )

    drone.land = refused_land  # type: ignore[method-assign]

    result = make_runner(drone, telemetry=lambda: next(readings), clock=clock).run(
        operator_confirmed=True
    )

    assert result.outcome is MissionOutcome.ABORTED
    aborted = next(
        record
        for record in caplog.records
        if record.getMessage() == "Preset aborted at a failed step"
    )
    assert aborted.context["height_cm"] == 110
    assert aborted.context["battery_percent"] == 79
    assert aborted.context["temperature_c"] == 66.0
    assert aborted.context["telemetry_age_s"] is not None


def test_a_battery_drop_mid_program_aborts_before_the_next_turn():
    drone = connected_fake()
    clock = FakeClock()
    batteries = iter([80, 15])

    def telemetry() -> Telemetry:
        return Telemetry(battery_percent=next(batteries), received_at=clock.now)

    runner = make_runner(drone, PRESET_SQUARE, telemetry=telemetry, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.ABORTED
    assert "in-flight minimum" in result.reason
    assert sent(drone) == ("takeoff",)


def test_takeoff_is_settled_before_the_first_turn():
    drone = connected_fake()
    clock = FakeClock()
    runner = make_runner(drone, PRESET_SQUARE, clock=clock)

    result = runner.run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone)[:2] == ("takeoff", "ccw 90")
    assert clock.now >= CONSERVATIVE_LIMITS.takeoff_settle_s


def test_a_right_turn_uses_the_cw_command():
    program = PresetProgram(
        program_id="right-turn",
        title="Right turn",
        summary="A single right turn.",
        steps=(
            PresetStep.takeoff(),
            PresetStep.turn_right(45),
            PresetStep.land(),
        ),
    )
    drone = connected_fake()

    result = make_runner(drone, program).run(operator_confirmed=True)

    assert result.outcome is MissionOutcome.COMPLETED
    assert sent(drone) == ("takeoff", "cw 45", "land")


# -- run logging -------------------------------------------------------------


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_a_run_logs_every_step_and_the_final_outcome(caplog):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()

    make_runner(drone).run(operator_confirmed=True)

    messages = _messages(caplog)
    assert "Preset run requested" in messages
    assert "Preset gates passed" in messages
    assert messages.count("Preset step starting") == 3
    assert "Preset hold starting" in messages
    assert "Preset hold finished" in messages
    assert messages.count("Preset command outcome") == 2  # takeoff and land
    assert "Takeoff settle finished" in messages
    assert "Preset run finished" in messages

    finished = next(
        record for record in caplog.records if record.getMessage() == "Preset run finished"
    )
    assert finished.context["outcome"] == "completed"
    assert finished.context["commands_sent"] == 2


def test_a_refused_gate_is_logged_with_the_reason(caplog):
    caplog.set_level(logging.WARNING, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock(now=10.0)
    stale = Telemetry(battery_percent=80, received_at=0.0)

    result = make_runner(drone, telemetry=lambda: stale, clock=clock).run(
        operator_confirmed=True
    )

    assert result.outcome is MissionOutcome.REJECTED
    refused = next(
        record
        for record in caplog.records
        if record.getMessage() == "Preset gates refused the run"
    )
    assert "stale" in refused.context["reason"]
    assert refused.context["program"] == PRESET_TAKEOFF_HOVER_LAND.program_id


def test_a_movement_without_fresh_telemetry_is_logged_before_it_is_sent(caplog):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.preset_missions")
    drone = connected_fake()
    clock = FakeClock()
    readings = iter(
        [
            Telemetry(battery_percent=80, received_at=0.0),  # gate: fresh at t=0
            Telemetry(battery_percent=80, received_at=0.0),  # step: stale
        ]
    )

    make_runner(
        drone,
        PRESET_SQUARE,
        telemetry=lambda: next(readings, Telemetry()),
        clock=clock,
    ).run(operator_confirmed=True)

    skipped = [
        record
        for record in caplog.records
        if record.getMessage() == "In-flight battery check skipped: telemetry is stale"
    ]
    assert skipped
    assert skipped[0].context["action"] == "yaw_left"
    assert skipped[0].context["telemetry_age_s"] is not None
