"""Gamepad mapping, dead zones and deliberate-action guards.

Windows Bluetooth controllers expose different axis counts, names and sign
conventions. Nothing here assumes a brand: the adapter reports generic
``axis_N``/``button_N`` names and this module maps *roles* onto them. The
offered default is only a proposal — ``GamepadMapping.confirmed`` stays false
until the operator explicitly confirms it, and the manual controller refuses to
send flight commands with an unconfirmed mapping.

Emergency Land is never bound by default. Mapping it requires an explicit
choice and a sustained hold, so a knocked stick cannot land an aircraft.

This module is retained for a future gamepad lesson. It is not wired into the
current application: the UI exposes no mapping controls and no polling timer.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .interfaces.gamepad import GamepadState

__all__ = [
    "AxisRole",
    "GamepadMapping",
    "HoldTrigger",
    "MappedInput",
    "apply_dead_zone",
    "map_gamepad_state",
]


class AxisRole(StrEnum):
    """What a physical axis controls in the manual-control model."""

    FORWARD = "forward"
    STRAFE = "strafe"
    YAW = "yaw"
    VERTICAL = "vertical"

    @property
    def label(self) -> str:
        return {
            AxisRole.FORWARD: "Forward / backward",
            AxisRole.STRAFE: "Left / right",
            AxisRole.YAW: "Yaw",
            AxisRole.VERTICAL: "Up / down",
        }[self]


_DEFAULT_AXES = {
    AxisRole.FORWARD: "axis_1",
    AxisRole.STRAFE: "axis_0",
    AxisRole.YAW: "axis_3",
    AxisRole.VERTICAL: "axis_2",
}
"""A common twin-stick layout, offered only as an unconfirmed proposal."""


@dataclass(frozen=True, slots=True)
class GamepadMapping:
    """Role-to-axis binding plus calibration and action buttons."""

    axes: Mapping[AxisRole, str] = field(default_factory=lambda: dict(_DEFAULT_AXES))
    dead_zone: float = 0.15
    invert: frozenset[AxisRole] = frozenset(
        {AxisRole.FORWARD, AxisRole.VERTICAL}
    )
    button_actions: Mapping[str, str] = field(default_factory=dict)
    """``button_N`` → ``"takeoff"``, ``"land"`` or ``"emergency_land"``.

    Empty by default: a face button does nothing until the operator maps it.
    """
    emergency_button: str | None = None
    confirmed: bool = False
    action_hold_s: float = 0.6
    emergency_hold_s: float = 1.5

    def __post_init__(self) -> None:
        for role, axis in self.axes.items():
            if not isinstance(axis, str) or not axis:
                raise ValueError(f"Axis for {role.value} must be a non-empty name")
        if not 0.0 <= self.dead_zone < 1.0:
            raise ValueError("dead_zone must be within 0.0 .. 1.0 (exclusive)")
        if self.action_hold_s <= 0 or self.emergency_hold_s <= 0:
            raise ValueError("Button hold times must be positive")
        if self.emergency_button is not None and not self.emergency_button:
            raise ValueError("emergency_button must be a button name or None")

    # -- editing -------------------------------------------------------------

    def with_axis(self, role: AxisRole, axis: str) -> GamepadMapping:
        """Bind a role to an axis. Changing the mapping revokes confirmation."""
        updated = dict(self.axes)
        updated[role] = axis
        return replace(self, axes=updated, confirmed=False)

    def with_invert(self, role: AxisRole, inverted: bool) -> GamepadMapping:
        roles = set(self.invert)
        if inverted:
            roles.add(role)
        else:
            roles.discard(role)
        return replace(self, invert=frozenset(roles), confirmed=False)

    def with_dead_zone(self, dead_zone: float) -> GamepadMapping:
        """Calibration only; keeps an existing confirmation."""
        return replace(self, dead_zone=dead_zone)

    def with_button_action(self, button: str, action: str | None) -> GamepadMapping:
        actions = dict(self.button_actions)
        if action is None:
            actions.pop(button, None)
        else:
            actions[button] = action
        emergency = self.emergency_button
        if action == "emergency_land":
            emergency = button
        elif emergency == button:
            emergency = None
        return replace(
            self,
            button_actions=actions,
            emergency_button=emergency,
            confirmed=False,
        )

    def confirmed_copy(self) -> GamepadMapping:
        """The operator has reviewed this mapping; flight actions become allowed."""
        return replace(self, confirmed=True)

    def axis_for(self, role: AxisRole) -> str:
        return self.axes[role]


@dataclass(frozen=True, slots=True)
class MappedInput:
    """Dead-zoned, normalized stick values plus held buttons."""

    forward: float = 0.0
    strafe: float = 0.0
    yaw: float = 0.0
    vertical: float = 0.0
    buttons: frozenset[str] = frozenset()
    connected: bool = False

    def dominant(self) -> tuple[AxisRole | None, float]:
        """The axis the operator pushed furthest past the dead zone."""
        candidates = (
            (AxisRole.FORWARD, self.forward),
            (AxisRole.STRAFE, self.strafe),
            (AxisRole.YAW, self.yaw),
            (AxisRole.VERTICAL, self.vertical),
        )
        role, value = max(candidates, key=lambda item: abs(item[1]))
        return (role, value) if value else (None, 0.0)


def apply_dead_zone(value: float, dead_zone: float) -> float:
    """Clamp a stick value and rescale so motion starts smoothly past the dead zone."""
    if not -1.0 <= dead_zone < 1.0:
        raise ValueError("dead_zone must be within -1.0 .. 1.0 (exclusive)")
    clamped = max(-1.0, min(1.0, float(value)))
    if dead_zone > 0 and abs(clamped) <= dead_zone:
        return 0.0
    scaled = (abs(clamped) - dead_zone) / (1.0 - dead_zone)
    return max(-1.0, min(1.0, scaled)) * (1.0 if clamped > 0 else -1.0)


def map_gamepad_state(state: GamepadState, mapping: GamepadMapping) -> MappedInput:
    """Apply the user's mapping, inversion and dead zone to one poll."""
    if not state.connected:
        return MappedInput(connected=False)

    def axis(role: AxisRole) -> float:
        raw = state.axis(mapping.axis_for(role))
        if role in mapping.invert:
            raw = -raw
        return apply_dead_zone(raw, mapping.dead_zone)

    return MappedInput(
        forward=axis(AxisRole.FORWARD),
        strafe=axis(AxisRole.STRAFE),
        yaw=axis(AxisRole.YAW),
        vertical=axis(AxisRole.VERTICAL),
        buttons=state.buttons,
        connected=True,
    )


class HoldTrigger:
    """Fire once after a button has been held continuously for ``hold_s``.

    Releasing the button re-arms the trigger. Used for deliberate actions such
    as a mapped Emergency Land, so a single accidental press does nothing.
    """

    def __init__(
        self,
        hold_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if hold_s <= 0:
            raise ValueError("hold_s must be positive")
        self._hold_s = hold_s
        self._clock = clock
        self._held_since: float | None = None
        self._fired = False

    @property
    def fired(self) -> bool:
        return self._fired

    def reset(self) -> None:
        self._held_since = None
        self._fired = False

    def update(self, held: bool) -> bool:
        """Feed the current button state; True exactly once per sustained hold."""
        now = self._clock()
        if not held:
            self._held_since = None
            self._fired = False
            return False
        if self._held_since is None:
            self._held_since = now
            return False
        if not self._fired and (now - self._held_since) >= self._hold_s:
            self._fired = True
            return True
        return False
