"""Bounded manual control: same gates for keyboard, buttons and sticks."""

from __future__ import annotations

import pytest
from tello_doubles import FakeClock

from drone_vision_lab.domain import Telemetry
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.gamepad import MappedInput
from drone_vision_lab.manual_control import ManualAction, ManualCommand, ManualController
from drone_vision_lab.state import AppStateSnapshot, ControlAuthority, SafetyState

GROUND = AppStateSnapshot(
    safety_state=SafetyState.CONNECTED_GROUNDED,
    control_authority=ControlAuthority.DESKTOP,
    drone_connected=True,
)
FLYING = AppStateSnapshot(
    safety_state=SafetyState.FLYING_MANUAL,
    control_authority=ControlAuthority.DESKTOP,
    drone_connected=True,
)
HEALTHY = Telemetry(battery_percent=80, height_cm=80, received_at=0.0)


def sent(drone: FakeDroneAdapter) -> tuple[str, ...]:
    """Commands after the connection handshake."""
    return tuple(command for command in drone.commands if command != "connect")


def make_controller(
    *,
    flying: bool = True,
) -> tuple[ManualController, FakeDroneAdapter, FakeClock]:
    drone = FakeDroneAdapter()
    assert drone.connect().ok
    clock = FakeClock()
    controller = ManualController(drone, clock=clock)
    snapshot = FLYING if flying else GROUND
    assert controller.engage(snapshot) == ""
    return controller, drone, clock


def test_manual_control_requires_a_connection_and_engagement():
    drone = FakeDroneAdapter()
    controller = ManualController(drone)

    assert "Connect" in controller.engage(GROUND)
    assert controller.engaged is False
    command = controller.from_keyboard(ManualAction.FORWARD, GROUND, HEALTHY)
    assert command is None
    assert "Take manual control" in controller.blocked_reason


def test_engagement_refuses_an_external_controller():
    drone = FakeDroneAdapter()
    assert drone.connect().ok
    controller = ManualController(drone)
    snapshot = AppStateSnapshot(
        safety_state=SafetyState.CONNECTED_GROUNDED,
        control_authority=ControlAuthority.EXTERNAL_APP,
        drone_connected=True,
    )

    reason = controller.engage(snapshot)

    assert "phone app" in reason


def test_sticks_need_a_confirmed_mapping_and_centre_means_no_command():
    controller, _drone, _clock = make_controller()
    mapped = MappedInput(forward=0.8, connected=True)

    assert (
        controller.from_gamepad(mapped, FLYING, HEALTHY, mapping_confirmed=False)
        is None
    )
    assert "unconfirmed" in controller.blocked_reason
    assert (
        controller.from_gamepad(mapped, FLYING, HEALTHY, mapping_confirmed=True)
        == ManualCommand(ManualAction.FORWARD, 30)
    )
    assert (
        controller.from_gamepad(
            MappedInput(connected=True), FLYING, HEALTHY, mapping_confirmed=True
        )
        is None
    )
    assert "centred" in controller.blocked_reason


def test_each_axis_maps_to_one_bounded_action():
    controller, _drone, _clock = make_controller()
    cases = (
        (MappedInput(forward=0.9, connected=True), ManualAction.FORWARD),
        (MappedInput(forward=-0.9, connected=True), ManualAction.BACK),
        (MappedInput(strafe=0.9, connected=True), ManualAction.RIGHT),
        (MappedInput(strafe=-0.9, connected=True), ManualAction.LEFT),
        (MappedInput(yaw=0.9, connected=True), ManualAction.YAW_CW),
        (MappedInput(yaw=-0.9, connected=True), ManualAction.YAW_CCW),
        (MappedInput(vertical=0.9, connected=True), ManualAction.UP),
        (MappedInput(vertical=-0.9, connected=True), ManualAction.DOWN),
    )

    for mapped, expected in cases:
        command = controller.from_gamepad(
            mapped,
            FLYING,
            Telemetry(height_cm=80, received_at=0.0),
            mapping_confirmed=True,
        )
        assert command is not None, expected
        assert command.action is expected

        controller.execute(command)
        controller._last_command_at = None  # test clock control


def test_execute_sends_one_bounded_command():
    controller, drone, _clock = make_controller()
    command = controller.from_keyboard(ManualAction.FORWARD, FLYING, HEALTHY)

    assert command == ManualCommand(ManualAction.FORWARD, 30)
    result = controller.execute(command)

    assert result.status.value == "sent"
    assert sent(drone) == ("forward 30 30",)


def test_commands_are_rate_limited():
    controller, drone, clock = make_controller()
    first = controller.from_keyboard(ManualAction.RIGHT, FLYING, HEALTHY)
    assert first is not None
    controller.execute(first)

    assert controller.from_keyboard(ManualAction.RIGHT, FLYING, HEALTHY) is None
    assert "previous command" in controller.blocked_reason

    clock.now = 0.5
    second = controller.from_keyboard(ManualAction.RIGHT, FLYING, HEALTHY)

    assert second is not None
    assert sent(drone) == ("right 30 30",)


def test_movement_is_refused_on_the_ground():
    controller, drone, _clock = make_controller(flying=False)

    command = controller.from_keyboard(ManualAction.FORWARD, GROUND, HEALTHY)

    assert command is None
    assert "Take off" in controller.blocked_reason
    assert sent(drone) == ()


def test_takeoff_requires_a_reported_battery_above_the_minimum():
    controller, drone, _clock = make_controller(flying=False)

    no_battery = controller.takeoff(GROUND, Telemetry(battery_percent=None))
    no_battery_reason = controller.blocked_reason
    low = controller.takeoff(GROUND, Telemetry(battery_percent=9, received_at=0.0))
    low_reason = controller.blocked_reason
    ready = controller.takeoff(GROUND, Telemetry(battery_percent=80, received_at=0.0))

    assert no_battery is None and "Battery has not been reported" in no_battery_reason
    assert low is None and "below the takeoff minimum" in low_reason
    assert ready == ManualCommand(ManualAction.TAKEOFF)
    assert controller.execute(ready).ok
    assert sent(drone) == ("takeoff",)


def test_vertical_control_needs_reported_height_and_respects_limits():
    controller, _drone, _clock = make_controller()

    unknown = controller.from_keyboard(
        ManualAction.UP, FLYING, Telemetry(battery_percent=80, received_at=0.0)
    )
    unknown_reason = controller.blocked_reason
    near_ceiling = controller.from_keyboard(
        ManualAction.UP,
        FLYING,
        Telemetry(battery_percent=80, height_cm=140, received_at=0.0),
    )
    ceiling_reason = controller.blocked_reason
    near_floor = controller.from_keyboard(
        ManualAction.DOWN,
        FLYING,
        Telemetry(battery_percent=80, height_cm=20, received_at=0.0),
    )
    floor_reason = controller.blocked_reason

    assert unknown is None and "Height has not been reported" in unknown_reason
    assert near_ceiling is None and "altitude limit" in ceiling_reason
    assert near_floor is None and "Use Land" in floor_reason


def test_low_in_flight_battery_blocks_movement():
    controller, _drone, _clock = make_controller()

    command = controller.from_keyboard(
        ManualAction.FORWARD, FLYING, Telemetry(battery_percent=15, received_at=0.0)
    )

    assert command is None
    assert "in-flight minimum" in controller.blocked_reason


def test_a_mission_or_landing_owns_the_aircraft():
    controller, _drone, _clock = make_controller()
    snapshot = AppStateSnapshot(
        safety_state=SafetyState.FLYING_MISSION,
        control_authority=ControlAuthority.DESKTOP,
        drone_connected=True,
    )

    assert controller.from_keyboard(ManualAction.FORWARD, snapshot, HEALTHY) is None
    assert "mission" in controller.blocked_reason.lower()


def test_land_is_one_command_and_release_disengages():
    controller, drone, _clock = make_controller()
    land = controller.land(FLYING, HEALTHY)

    assert land == ManualCommand(ManualAction.LAND)
    assert controller.execute(land).ok
    controller.disengage()

    assert controller.engaged is False
    assert controller.execute(ManualCommand(ManualAction.LAND)).status.value == "rejected"
    assert sent(drone) == ("land",)


def test_execute_refuses_when_the_channel_or_engagement_is_gone():
    controller, drone, _clock = make_controller()
    drone.disconnect()

    result = controller.execute(ManualCommand(ManualAction.FORWARD, 30))

    assert result.status.value == "rejected"
    assert "no longer available" in result.detail
    assert controller.engaged is False


def test_stale_telemetry_blocks_takeoff_and_vertical_control_but_not_landing():
    controller, _drone, clock = make_controller()
    stale = Telemetry(battery_percent=80, height_cm=80, received_at=0.0)
    clock.now = 10.0

    takeoff = controller.takeoff(GROUND, stale)
    takeoff_reason = controller.blocked_reason
    climb = controller.from_keyboard(ManualAction.UP, FLYING, stale)
    climb_reason = controller.blocked_reason
    forward = controller.from_keyboard(ManualAction.FORWARD, FLYING, stale)
    land = controller.land(FLYING, stale)

    assert takeoff is None and "stale" in takeoff_reason
    assert climb is None and "stale" in climb_reason
    # Horizontal steps do not depend on a telemetry value, so stale telemetry
    # does not block them; landing is always available.
    assert forward == ManualCommand(ManualAction.FORWARD, 30)
    assert land == ManualCommand(ManualAction.LAND)


def test_landing_is_never_blocked_by_a_low_battery():
    controller, _drone, _clock = make_controller()

    land = controller.land(FLYING, Telemetry(battery_percent=15, received_at=0.0))

    assert land == ManualCommand(ManualAction.LAND)


def test_telemetry_without_a_timestamp_cannot_satisfy_a_gate():
    controller, _drone, _clock = make_controller()
    untimed = Telemetry(battery_percent=80, height_cm=80)

    command = controller.from_keyboard(ManualAction.UP, FLYING, untimed)

    assert command is None
    assert "stale" in controller.blocked_reason


def test_bounded_step_settings_are_validated():
    drone = FakeDroneAdapter()
    with pytest.raises(ValueError):
        ManualController(drone, step_cm=10)
    with pytest.raises(ValueError):
        ManualController(drone, yaw_degrees=0)
    with pytest.raises(ValueError):
        ManualController(drone, speed_cm_s=200)
    with pytest.raises(ValueError):
        ManualController(drone, min_interval_s=-1)
    with pytest.raises(ValueError):
        ManualController(drone, telemetry_max_age_s=0)
