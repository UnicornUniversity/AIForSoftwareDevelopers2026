"""Bounded manual control shared by keyboard, on-screen buttons and gamepad.

Every manual input becomes one short, bounded command: a fixed translation or
yaw step at a conservative speed, never a continuous ``rc`` stream. Commands are
rate limited, require an explicit "take control" engagement, and are refused
while a mission owns the aircraft. Release-to-stop means the controller stops
issuing commands when the stick returns to the dead zone; the last bounded step
finishes on its own (the standard Tello SDK has no universal ``stop`` verb).

This module is Qt-free. The UI submits :meth:`ManualController.execute` from a
background worker so no network wait touches the GUI thread.

The gamepad entry point (:meth:`ManualController.from_gamepad`) is retained for a
future lesson, but no UI in this build calls it. Manual flight uses the keyboard
and the on-screen buttons only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .config import CONSERVATIVE_LIMITS, SafetyLimits
from .domain import CommandResult, CommandStatus, Telemetry, telemetry_is_fresh
from .gamepad import AxisRole, MappedInput
from .interfaces.drone import DroneAdapter
from .state import AppStateSnapshot, ControlAuthority, SafetyState

__all__ = ["ManualAction", "ManualCommand", "ManualController"]


class ManualAction(StrEnum):
    FORWARD = "forward"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    YAW_CW = "yaw_cw"
    YAW_CCW = "yaw_ccw"
    TAKEOFF = "takeoff"
    LAND = "land"

    @property
    def is_movement(self) -> bool:
        return self in (
            ManualAction.FORWARD,
            ManualAction.BACK,
            ManualAction.LEFT,
            ManualAction.RIGHT,
            ManualAction.UP,
            ManualAction.DOWN,
        )


@dataclass(frozen=True, slots=True)
class ManualCommand:
    action: ManualAction
    amount: int = 0

    def describe(self) -> str:
        if self.amount:
            return f"{self.action.value} {self.amount}"
        return self.action.value


class ManualController:
    """Turns operator input into bounded commands, or refuses with a reason."""

    def __init__(
        self,
        drone: DroneAdapter,
        *,
        limits: SafetyLimits = CONSERVATIVE_LIMITS,
        step_cm: int = 30,
        yaw_degrees: int = 15,
        speed_cm_s: int = 30,
        min_interval_s: float = 0.5,
        telemetry_max_age_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 20 <= step_cm <= limits.max_segment_distance_cm:
            raise ValueError(
                f"step_cm must be within 20..{limits.max_segment_distance_cm}"
            )
        if not 1 <= yaw_degrees <= 90:
            raise ValueError("yaw_degrees must be within 1..90")
        if not 10 <= speed_cm_s <= limits.max_speed_cm_s:
            raise ValueError(f"speed_cm_s must be within 10..{limits.max_speed_cm_s}")
        if min_interval_s < 0:
            raise ValueError("min_interval_s must not be negative")
        if telemetry_max_age_s is None:
            telemetry_max_age_s = limits.telemetry_max_age_s
        if telemetry_max_age_s <= 0:
            raise ValueError("telemetry_max_age_s must be positive")
        self._drone = drone
        self._limits = limits
        self._step_cm = step_cm
        self._yaw_degrees = yaw_degrees
        self._speed_cm_s = speed_cm_s
        self._min_interval_s = min_interval_s
        self._telemetry_max_age_s = telemetry_max_age_s
        self._clock = clock
        self._engaged = False
        self._last_command_at: float | None = None
        self._blocked_reason = ""

    # -- inspection ----------------------------------------------------------

    @property
    def engaged(self) -> bool:
        return self._engaged

    @property
    def blocked_reason(self) -> str:
        """Why the last request produced no command, or ``""``."""
        return self._blocked_reason

    @property
    def step_cm(self) -> int:
        return self._step_cm

    @property
    def yaw_degrees(self) -> int:
        return self._yaw_degrees

    # -- engagement ----------------------------------------------------------

    def engage(self, snapshot: AppStateSnapshot) -> str:
        """Acquire manual control; returns ``""`` or the refusal reason."""
        if not self._drone.connected:
            return self._refuse("Connect to the aircraft before taking manual control.")
        if snapshot.control_authority is ControlAuthority.EXTERNAL_APP:
            return self._refuse(
                "Another controller is declared active. Close the phone app's control "
                "session before taking control from this application."
            )
        if snapshot.safety_state in (
            SafetyState.FLYING_MISSION,
            SafetyState.FLYING_TRACKING,
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        ):
            return self._refuse(
                "Manual control is unavailable while a mission, tracking session or "
                "landing owns the aircraft."
            )
        self._engaged = True
        self._last_command_at = None
        self._blocked_reason = ""
        return ""

    def disengage(self, reason: str = "Manual control released.") -> None:
        self._engaged = False
        self._last_command_at = None
        self._blocked_reason = reason

    # -- decisions -----------------------------------------------------------

    def from_gamepad(
        self,
        mapped: MappedInput,
        snapshot: AppStateSnapshot,
        telemetry: Telemetry,
        *,
        mapping_confirmed: bool,
    ) -> ManualCommand | None:
        """One bounded command from the dominant stick, or ``None``."""
        if not mapped.connected:
            self._blocked_reason = "No controller is connected."
            return None
        if not mapping_confirmed:
            self._blocked_reason = (
                "The gamepad mapping is unconfirmed; mapped input is ignored."
            )
            return None
        role, value = mapped.dominant()
        if role is None or not value:
            self._blocked_reason = "Sticks are centred; no command is being sent."
            return None
        action = self._action_for(role, value)
        if action is None:
            return None
        return self._consider(action, snapshot, telemetry)

    def from_keyboard(
        self,
        action: ManualAction,
        snapshot: AppStateSnapshot,
        telemetry: Telemetry,
    ) -> ManualCommand | None:
        return self._consider(action, snapshot, telemetry)

    def takeoff(self, snapshot: AppStateSnapshot, telemetry: Telemetry) -> ManualCommand | None:
        return self._consider(ManualAction.TAKEOFF, snapshot, telemetry)

    def land(self, snapshot: AppStateSnapshot, telemetry: Telemetry) -> ManualCommand | None:
        return self._consider(ManualAction.LAND, snapshot, telemetry)

    # -- execution -----------------------------------------------------------

    def execute(self, command: ManualCommand) -> CommandResult:
        """Send one bounded command. Intended to run on a background worker."""
        if not self._engaged:
            return self._refusal(command, "Manual control is not engaged.")
        if not self._drone.connected:
            self._engaged = False
            return self._refusal(command, "The command channel is no longer available.")

        action = command.action
        if action is ManualAction.TAKEOFF:
            result = self._drone.takeoff()
        elif action is ManualAction.LAND:
            result = self._drone.land()
        elif action is ManualAction.YAW_CW:
            result = self._drone.rotate("clockwise", command.amount)
        elif action is ManualAction.YAW_CCW:
            result = self._drone.rotate("counter_clockwise", command.amount)
        elif action is ManualAction.UP:
            result = self._drone.move("up", command.amount, self._speed_cm_s)
        elif action is ManualAction.DOWN:
            result = self._drone.move("down", command.amount, self._speed_cm_s)
        else:
            result = self._drone.move(action.value, command.amount, self._speed_cm_s)
        self._last_command_at = self._clock()
        return result

    # -- internals -----------------------------------------------------------

    def _action_for(self, role: AxisRole, value: float) -> ManualAction | None:
        if role is AxisRole.FORWARD:
            return ManualAction.FORWARD if value > 0 else ManualAction.BACK
        if role is AxisRole.STRAFE:
            return ManualAction.RIGHT if value > 0 else ManualAction.LEFT
        if role is AxisRole.YAW:
            return ManualAction.YAW_CW if value > 0 else ManualAction.YAW_CCW
        return ManualAction.UP if value > 0 else ManualAction.DOWN

    def _consider(
        self,
        action: ManualAction,
        snapshot: AppStateSnapshot,
        telemetry: Telemetry,
    ) -> ManualCommand | None:
        reason = self._gate(action, snapshot, telemetry)
        if reason:
            self._blocked_reason = reason
            return None
        if self._rate_limited():
            self._blocked_reason = "Waiting for the previous command to finish."
            return None
        self._blocked_reason = ""
        return ManualCommand(action, self._amount_for(action))

    def _amount_for(self, action: ManualAction) -> int:
        if action in (ManualAction.YAW_CW, ManualAction.YAW_CCW):
            return self._yaw_degrees
        if action is ManualAction.TAKEOFF or action is ManualAction.LAND:
            return 0
        return self._step_cm

    def _gate(
        self,
        action: ManualAction,
        snapshot: AppStateSnapshot,
        telemetry: Telemetry,
    ) -> str:
        if not self._engaged:
            return "Take manual control before sending commands."
        if not self._drone.connected or not snapshot.drone_connected:
            return "The command channel is not available."
        if snapshot.control_authority is ControlAuthority.EXTERNAL_APP:
            return "Another controller is declared active."
        if snapshot.safety_state in (
            SafetyState.FLYING_MISSION,
            SafetyState.FLYING_TRACKING,
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        ):
            return "A mission, tracking session or landing owns the aircraft."
        if action is ManualAction.TAKEOFF:
            return self._takeoff_gate(snapshot, telemetry)
        if not snapshot.safety_state.in_flight:
            return "Take off before using movement controls."
        if action is ManualAction.LAND:
            # Landing is the recovery action. It must never be blocked by a low
            # or stale battery: refusing it would argue against bringing the
            # aircraft down.
            return ""
        fresh = self._telemetry_is_fresh(telemetry)
        # A stale battery reading is the last thing the aircraft said, not
        # evidence about the present; gates must not treat it as current.
        battery = telemetry.battery_percent if fresh else None
        if battery is not None and battery < self._limits.min_battery_percent_in_flight:
            return (
                f"Battery {battery}% is below the in-flight minimum "
                f"{self._limits.min_battery_percent_in_flight}%."
            )
        height = telemetry.height_cm
        if action is ManualAction.UP or action is ManualAction.DOWN:
            if not fresh:
                return (
                    "Telemetry is stale or has not been received; vertical control "
                    "needs a current height report from the aircraft."
                )
            if height is None:
                return (
                    "Height has not been reported by the aircraft; vertical control is "
                    "unavailable until telemetry arrives."
                )
            if action is ManualAction.UP and (
                height + self._step_cm > self._limits.max_altitude_cm
            ):
                return (
                    f"Refused: climbing {self._step_cm} cm would exceed the "
                    f"{self._limits.max_altitude_cm} cm altitude limit."
                )
            if action is ManualAction.DOWN and height <= self._step_cm:
                return (
                    f"Refused: the aircraft reports {height} cm; descending "
                    f"{self._step_cm} cm would reach the ground. Use Land instead."
                )
        return ""

    def _takeoff_gate(self, snapshot: AppStateSnapshot, telemetry: Telemetry) -> str:
        if snapshot.safety_state.in_flight:
            return "The aircraft is already airborne."
        battery = telemetry.battery_percent
        if battery is None:
            return "Battery has not been reported; takeoff is blocked."
        if not self._telemetry_is_fresh(telemetry):
            return (
                "Telemetry is stale or has not been received; takeoff is blocked "
                "until the aircraft reports a current battery level."
            )
        if battery < self._limits.min_battery_percent_for_takeoff:
            return (
                f"Battery {battery}% is below the takeoff minimum "
                f"{self._limits.min_battery_percent_for_takeoff}%."
            )
        return ""

    def _telemetry_is_fresh(self, telemetry: Telemetry) -> bool:
        return telemetry_is_fresh(
            telemetry,
            now=self._clock(),
            max_age_s=self._telemetry_max_age_s,
        )

    def _rate_limited(self) -> bool:
        if self._last_command_at is None:
            return False
        return (self._clock() - self._last_command_at) < self._min_interval_s

    def _refuse(self, reason: str) -> str:
        self._engaged = False
        self._blocked_reason = reason
        return reason

    def _refusal(self, command: ManualCommand, reason: str) -> CommandResult:
        now = self._clock()
        return CommandResult(
            command.describe(),
            CommandStatus.REJECTED,
            f"Refused locally before transmission: {reason}",
            requested_at=now,
            completed_at=now,
        )
