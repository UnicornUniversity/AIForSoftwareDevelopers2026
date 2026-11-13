"""The six-segment mission: editing, validation and sequential execution.

A mission is a rectangular loop flown in a fixed order: take off (optionally
climbing to a configured height), left, forward, right, backward, land. The
editor may change distances, speed and pauses, but every value is checked
against :class:`~drone_vision_lab.config.SafetyLimits` before anything is sent.

Execution is strictly sequential and cancellable. **Stop Mission** stops
issuing new commands and does not itself land; **Emergency Land** is a separate
top-bar action. A standard Tello has no reliable indoor global position, so a
loop of six moves does not return to its exact start point — the UI says
"approximate", never "return to origin".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .config import CONSERVATIVE_LIMITS, SafetyLimits
from .domain import CommandResult, CommandStatus, Telemetry, telemetry_is_fresh
from .interfaces.drone import DroneAdapter

__all__ = [
    "MissionIssue",
    "MissionOutcome",
    "MissionPlan",
    "MissionResult",
    "MissionRunner",
    "MissionSegment",
    "SegmentAction",
    "default_mission",
    "estimated_duration_s",
    "validate_mission",
]

_TAKEOFF_SECONDS = 5.0
_LAND_SECONDS = 5.0


class SegmentAction(StrEnum):
    TAKEOFF = "takeoff"
    LEFT = "left"
    FORWARD = "forward"
    RIGHT = "right"
    BACK = "back"
    LAND = "land"


_MISSION_ORDER = (
    SegmentAction.TAKEOFF,
    SegmentAction.LEFT,
    SegmentAction.FORWARD,
    SegmentAction.RIGHT,
    SegmentAction.BACK,
    SegmentAction.LAND,
)


@dataclass(frozen=True, slots=True)
class MissionSegment:
    """One editable leg of the loop."""

    action: SegmentAction
    distance_cm: int = 0
    """Climb height for the takeoff leg; translation distance for the others."""
    speed_cm_s: int | None = None
    pause_s: float = 0.0

    @property
    def is_takeoff(self) -> bool:
        return self.action is SegmentAction.TAKEOFF

    @property
    def is_landing(self) -> bool:
        return self.action is SegmentAction.LAND

    @property
    def is_movement(self) -> bool:
        return not self.is_takeoff and not self.is_landing


def default_mission(limits: SafetyLimits = CONSERVATIVE_LIMITS) -> MissionPlan:
    """The conservative starting plan shown when the tab opens."""
    distance = limits.max_segment_distance_cm
    speed = min(30, limits.max_speed_cm_s)
    return MissionPlan(
        segments=(
            MissionSegment(SegmentAction.TAKEOFF, distance_cm=0),
            MissionSegment(SegmentAction.LEFT, distance, speed),
            MissionSegment(SegmentAction.FORWARD, distance, speed),
            MissionSegment(SegmentAction.RIGHT, distance, speed),
            MissionSegment(SegmentAction.BACK, distance, speed),
            MissionSegment(SegmentAction.LAND),
        )
    )


@dataclass(frozen=True, slots=True)
class MissionPlan:
    segments: tuple[MissionSegment, ...] = field(default_factory=lambda: default_mission().segments)

    def __post_init__(self) -> None:
        if tuple(segment.action for segment in self.segments) != _MISSION_ORDER:
            raise ValueError(
                "A mission is exactly six segments in order: "
                + ", ".join(action.value for action in _MISSION_ORDER)
            )

    def replace_segment(self, index: int, segment: MissionSegment) -> MissionPlan:
        segments = list(self.segments)
        segments[index] = segment
        return replace(self, segments=tuple(segments))


@dataclass(frozen=True, slots=True)
class MissionIssue:
    segment_index: int | None
    message: str

    def describe(self) -> str:
        if self.segment_index is None:
            return self.message
        return f"Segment {self.segment_index + 1}: {self.message}"


def estimated_duration_s(plan: MissionPlan) -> float:
    """Conservative estimate; it is not a promise of flight time."""
    seconds = _TAKEOFF_SECONDS + _LAND_SECONDS
    for segment in plan.segments:
        seconds += segment.pause_s
        if (segment.is_takeoff and segment.distance_cm) or segment.is_movement:
            speed = segment.speed_cm_s or 30
            seconds += segment.distance_cm / speed
    return round(seconds, 1)


def validate_mission(
    plan: MissionPlan,
    limits: SafetyLimits = CONSERVATIVE_LIMITS,
) -> tuple[MissionIssue, ...]:
    """Every reason the plan must not fly. Empty means the plan is within limits."""
    issues: list[MissionIssue] = []
    for index, segment in enumerate(plan.segments):
        if segment.is_takeoff:
            if not 0 <= segment.distance_cm <= limits.max_altitude_cm:
                issues.append(
                    MissionIssue(
                        index,
                        f"climb must be 0 or 20..{limits.max_altitude_cm} cm "
                        "(the configured altitude limit).",
                    )
                )
            elif 0 < segment.distance_cm < 20:
                issues.append(
                    MissionIssue(index, "climb must be 0 or at least 20 cm.")
                )
            if segment.speed_cm_s is not None:
                issues.append(
                    MissionIssue(index, "takeoff does not use a speed setting.")
                )
        elif segment.is_movement:
            if not 20 <= segment.distance_cm <= 500:
                issues.append(MissionIssue(index, "distance must be within 20..500 cm."))
            elif segment.distance_cm > limits.max_segment_distance_cm:
                issues.append(
                    MissionIssue(
                        index,
                        f"distance {segment.distance_cm} cm exceeds the "
                        f"{limits.max_segment_distance_cm} cm segment limit.",
                    )
                )
            if segment.speed_cm_s is None:
                issues.append(MissionIssue(index, "speed is required for a movement leg."))
            elif not 10 <= segment.speed_cm_s <= 100:
                issues.append(MissionIssue(index, "speed must be within 10..100 cm/s."))
            elif segment.speed_cm_s > limits.max_speed_cm_s:
                issues.append(
                    MissionIssue(
                        index,
                        f"speed {segment.speed_cm_s} cm/s exceeds the "
                        f"{limits.max_speed_cm_s} cm/s limit.",
                    )
                )
        elif segment.is_landing and (segment.distance_cm or segment.speed_cm_s is not None):
            issues.append(MissionIssue(index, "landing takes no distance or speed."))
        if not 0.0 <= segment.pause_s <= 10.0:
            issues.append(MissionIssue(index, "pause must be within 0..10 s."))

    duration = estimated_duration_s(plan)
    if duration > limits.max_mission_duration_s:
        issues.append(
            MissionIssue(
                None,
                f"estimated duration {duration:.1f} s exceeds the "
                f"{limits.max_mission_duration_s} s mission limit.",
            )
        )
    return tuple(issues)


class MissionOutcome(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MissionResult:
    outcome: MissionOutcome
    reason: str = ""
    commands: tuple[CommandResult, ...] = ()

    @property
    def completed(self) -> bool:
        return self.outcome is MissionOutcome.COMPLETED


class MissionRunner:
    """Runs one plan sequentially; safe to cancel from another thread."""

    def __init__(
        self,
        drone: DroneAdapter,
        plan: MissionPlan,
        *,
        limits: SafetyLimits = CONSERVATIVE_LIMITS,
        telemetry: Callable[[], Telemetry] | None = None,
        takeoff_settle_s: float | None = None,
        telemetry_max_age_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if takeoff_settle_s is None:
            takeoff_settle_s = limits.takeoff_settle_s
        if telemetry_max_age_s is None:
            telemetry_max_age_s = limits.telemetry_max_age_s
        if takeoff_settle_s < 0:
            raise ValueError("takeoff_settle_s must not be negative")
        if telemetry_max_age_s <= 0:
            raise ValueError("telemetry_max_age_s must be positive")
        self._drone = drone
        self._plan = plan
        self._limits = limits
        self._telemetry = telemetry or drone.telemetry
        self._takeoff_settle_s = takeoff_settle_s
        self._telemetry_max_age_s = telemetry_max_age_s
        self._clock = clock
        self._sleep = sleep
        self._cancel = threading.Event()
        self._cancel_reason = ""

    @property
    def plan(self) -> MissionPlan:
        return self._plan

    @property
    def cancelling(self) -> bool:
        return self._cancel.is_set()

    def cancel(self, reason: str = "Stopped by the operator.") -> None:
        """Stop issuing new commands. The command already in flight still finishes."""
        self._cancel_reason = reason
        self._cancel.set()

    def run(self, *, operator_confirmed: bool) -> MissionResult:
        """Execute the plan. Requires explicit confirmation; never auto-starts."""
        if not operator_confirmed:
            return MissionResult(
                MissionOutcome.REJECTED,
                "Mission execution requires explicit operator confirmation.",
            )
        issues = validate_mission(self._plan, self._limits)
        if issues:
            return MissionResult(
                MissionOutcome.REJECTED,
                "The plan is outside the safety limits: "
                + "; ".join(issue.describe() for issue in issues),
            )
        if not self._drone.connected:
            return MissionResult(
                MissionOutcome.REJECTED,
                "Connect to the aircraft before starting a mission.",
            )

        telemetry = self._telemetry()
        battery = telemetry.battery_percent
        if battery is None:
            return MissionResult(
                MissionOutcome.REJECTED,
                "Battery has not been reported; takeoff is blocked.",
            )
        if not self._telemetry_is_fresh(telemetry):
            return MissionResult(
                MissionOutcome.REJECTED,
                "Telemetry is stale or has not been received; the mission is blocked "
                "until the aircraft reports a current battery level.",
            )
        if battery < self._limits.min_battery_percent_for_takeoff:
            return MissionResult(
                MissionOutcome.REJECTED,
                f"Battery {battery}% is below the takeoff minimum "
                f"{self._limits.min_battery_percent_for_takeoff}%.",
            )

        commands: list[CommandResult] = []
        for index, segment in enumerate(self._plan.segments):
            if self._cancel.is_set():
                return MissionResult(MissionOutcome.CANCELLED, self._cancel_reason, tuple(commands))
            if segment.is_movement:
                telemetry = self._telemetry()
                # A stale reading is the last thing the aircraft said, not
                # evidence about the present. Ignore it rather than aborting a
                # flight on old data; the next fresh report can still abort it.
                battery = (
                    telemetry.battery_percent
                    if self._telemetry_is_fresh(telemetry)
                    else None
                )
                if (
                    battery is not None
                    and battery < self._limits.min_battery_percent_in_flight
                ):
                    return MissionResult(
                        MissionOutcome.ABORTED,
                        f"Battery {battery}% is below the in-flight minimum "
                        f"{self._limits.min_battery_percent_in_flight}%. Remaining "
                        "segments were not sent.",
                        tuple(commands),
                    )

            if segment.pause_s and not self._pause(segment.pause_s):
                return MissionResult(
                    MissionOutcome.CANCELLED, self._cancel_reason, tuple(commands)
                )

            results = self._send(segment)
            commands.extend(results)
            failed = next((result for result in results if not result.ok), None)
            if failed is not None:
                return MissionResult(
                    MissionOutcome.ABORTED,
                    self._abort_reason(index + 1, segment, failed),
                    tuple(commands),
                )

        outcome = MissionOutcome.COMPLETED
        reason = (
            "Mission commands acknowledged. Landing still requires visual "
            "confirmation; a standard Tello does not return to its exact start point."
        )
        return MissionResult(outcome, reason, tuple(commands))

    # -- internals -----------------------------------------------------------

    def _abort_reason(
        self, number: int, segment: MissionSegment, failed: CommandResult
    ) -> str:
        """Say which segment failed and what the app can honestly infer about flight.

        A refused takeoff is the aircraft's own answer that this mission did not
        lift it off; a timed-out takeoff is not, because the reply may simply have
        been lost. Later failures leave the aircraft airborne.
        """
        detail = failed.detail if failed.detail.endswith(".") else f"{failed.detail}."
        reason = (
            f"Segment {number} ({segment.action.value}) did not succeed: {detail} "
            "Remaining segments were not sent."
        )
        # The takeoff segment may also send a climb; only the takeoff command
        # itself says anything about whether the aircraft left the ground.
        refused_takeoff = (
            segment.is_takeoff
            and failed.command == "takeoff"
            and failed.status is CommandStatus.FAILED
        )
        if refused_takeoff:
            return (
                reason
                + " The aircraft refused the takeoff, so this mission did not take "
                "it off. Check that the phone app is not controlling it, that it is "
                "level and unobstructed, and that its battery is healthy. If it is "
                "already airborne under another controller, land it."
            )
        if segment.is_takeoff and failed.command == "takeoff":
            return (
                reason
                + " The takeoff outcome is unknown: the aircraft may have taken off "
                "and may still be airborne — use Emergency Land if needed."
            )
        return (
            reason
            + " The aircraft may still be airborne — use Emergency Land if needed."
        )

    def _send(self, segment: MissionSegment) -> tuple[CommandResult, ...]:
        if segment.is_takeoff:
            takeoff = self._drone.takeoff()
            if not takeoff.ok:
                return (takeoff,)
            # The SDK acknowledges ``takeoff`` before the aircraft has reached
            # its hover height. A climb or first move sent immediately can be
            # refused or can fight the takeoff, so wait — cancellably — first.
            if not self._pause(self._takeoff_settle_s):
                return (takeoff,)
            if segment.distance_cm > 0:
                climb = self._drone.move("up", segment.distance_cm, segment.speed_cm_s)
                return (takeoff, climb)
            return (takeoff,)
        if segment.is_landing:
            return (self._drone.land(),)
        return (
            self._drone.move(segment.action.value, segment.distance_cm, segment.speed_cm_s),
        )

    def _telemetry_is_fresh(self, telemetry: Telemetry) -> bool:
        return telemetry_is_fresh(
            telemetry,
            now=self._clock(),
            max_age_s=self._telemetry_max_age_s,
        )

    def _pause(self, seconds: float) -> bool:
        deadline = self._clock() + seconds
        while self._clock() < deadline:
            if self._cancel.is_set():
                return False
            self._sleep(min(0.1, max(0.0, deadline - self._clock())))
        return not self._cancel.is_set()
