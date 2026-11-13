"""Gamepad mapping: no brand assumptions, dead zones, deliberate actions."""

from __future__ import annotations

import pytest
from tello_doubles import FakeClock

from drone_vision_lab.gamepad import (
    AxisRole,
    GamepadMapping,
    HoldTrigger,
    apply_dead_zone,
    map_gamepad_state,
)
from drone_vision_lab.interfaces.gamepad import GamepadState


def test_the_offered_mapping_is_unconfirmed_until_the_operator_accepts_it():
    mapping = GamepadMapping()

    assert mapping.confirmed is False
    assert mapping.axis_for(AxisRole.FORWARD) == "axis_1"
    assert mapping.emergency_button is None
    assert mapping.button_actions == {}


def test_editing_an_axis_or_inversion_revokes_confirmation():
    confirmed = GamepadMapping().confirmed_copy()
    assert confirmed.confirmed is True

    rebound = confirmed.with_axis(AxisRole.YAW, "axis_5")
    inverted = confirmed.with_invert(AxisRole.STRAFE, True)

    assert rebound.confirmed is False
    assert rebound.axis_for(AxisRole.YAW) == "axis_5"
    assert inverted.confirmed is False
    assert AxisRole.STRAFE in inverted.invert


def test_dead_zone_calibration_keeps_confirmation():
    confirmed = GamepadMapping().confirmed_copy()

    updated = confirmed.with_dead_zone(0.25)

    assert updated.dead_zone == 0.25
    assert updated.confirmed is True


def test_mapping_an_emergency_button_requires_a_fresh_confirmation():
    mapping = GamepadMapping().confirmed_copy()

    updated = mapping.with_button_action("button_7", "emergency_land")

    assert updated.emergency_button == "button_7"
    assert updated.button_actions["button_7"] == "emergency_land"
    assert updated.confirmed is False
    assert updated.with_button_action("button_7", None).emergency_button is None


def test_dead_zone_is_rescaled_not_merely_clipped():
    assert apply_dead_zone(0.1, 0.15) == 0.0
    assert apply_dead_zone(-0.15, 0.15) == 0.0
    assert apply_dead_zone(0.575, 0.15) == pytest.approx(0.5)
    assert apply_dead_zone(-1.0, 0.0) == -1.0
    assert apply_dead_zone(2.0, 0.15) == 1.0


def test_invalid_mappings_are_refused():
    with pytest.raises(ValueError):
        GamepadMapping(dead_zone=1.0)
    with pytest.raises(ValueError):
        GamepadMapping().with_axis(AxisRole.YAW, "")
    with pytest.raises(ValueError):
        apply_dead_zone(0.5, 1.0)


def test_a_state_is_mapped_through_roles_and_inversion():
    mapping = GamepadMapping().with_dead_zone(0.0)
    state = GamepadState(
        connected=True,
        axes={
            "axis_0": 0.5,  # strafe right
            "axis_1": -0.8,  # forward stick up (inverted by default)
            "axis_2": 0.0,
            "axis_3": 0.5,  # yaw right
        },
        buttons=frozenset({"button_0"}),
    )

    mapped = map_gamepad_state(state, mapping)

    assert mapped.connected is True
    assert mapped.strafe == pytest.approx(0.5)
    assert mapped.forward == pytest.approx(0.8)
    assert mapped.yaw == pytest.approx(0.5)
    assert mapped.vertical == 0.0
    assert mapped.buttons == frozenset({"button_0"})


def test_disconnected_sticks_map_to_nothing():
    mapped = map_gamepad_state(GamepadState(connected=False), GamepadMapping())

    assert mapped.connected is False
    assert mapped.dominant() == (None, 0.0)


def test_the_largest_past_dead_zone_axis_wins():
    state = GamepadState(
        connected=True,
        axes={"axis_0": 0.2, "axis_1": -0.9, "axis_2": 0.1, "axis_3": 0.3},
    )

    role, value = map_gamepad_state(state, GamepadMapping()).dominant()

    assert role is AxisRole.FORWARD
    assert value == pytest.approx((0.9 - 0.15) / 0.85)


def test_hold_trigger_fires_once_and_rearms_after_release():
    clock = FakeClock()
    trigger = HoldTrigger(1.5, clock=clock)

    assert trigger.update(True) is False
    clock.now = 1.0
    assert trigger.update(True) is False
    clock.now = 1.5
    assert trigger.update(True) is True
    clock.now = 2.0
    assert trigger.update(True) is False

    assert trigger.update(False) is False
    assert trigger.update(True) is False
    clock.now = 3.5
    assert trigger.update(True) is True


def test_hold_trigger_rejects_a_non_positive_hold():
    with pytest.raises(ValueError):
        HoldTrigger(0)
