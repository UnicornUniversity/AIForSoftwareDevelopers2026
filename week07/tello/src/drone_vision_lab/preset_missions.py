"""Preset flight programs: fixed, multistep sequences with the same safety gates.

A preset is a read-only program an operator can preview and fly without editing
it. Unlike :mod:`drone_vision_lab.mission`, a preset may contain any ordered
combination of takeoff, holds, observations, yaw turns, translations, climbs and
landing, so a program can describe a shape or a simple classroom demonstration.

An **observation** is a wait like a hold: it sends no flight command, so the
aircraft keeps hovering on its own (a standard Tello has no position hold). The
operator uses it to show an object to the aircraft camera while the UI draws the
configured YOLO target. A standard Tello lands itself when it receives no command
for 15 s, so a hold or observation longer than that sends a bare ``command``
keepalive every 5 s; it resets the timer and never moves the aircraft. An
observation is bounded (1–90 s) and the program still ends with a landing, so a
distracted operator does not leave the aircraft hovering indefinitely. When the
operator lands first with Emergency Land, the UI cancels the run before its own
landing step; the program then sends no second landing command.

Nothing here flies automatically: :class:`PresetRunner` requires an explicit
operator confirmation, refuses stale or missing telemetry, checks the battery in
flight, and stops before the next step when a command fails. **Stop Program**
stops issuing new steps and never lands by itself; **Emergency Land** remains a
separate top-bar action.

The Tello SDK accepts movement between 20 cm and 500 cm, so a program cannot fly
a 10 cm leg. :func:`validate_preset` rejects such a leg rather than adjusting it
silently. The bundled square preset uses 30 cm legs.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from .config import CONSERVATIVE_LIMITS, SafetyLimits
from .domain import CommandResult, CommandStatus, Telemetry, telemetry_is_fresh
from .interfaces.drone import DroneAdapter
from .mission import MissionOutcome, MissionResult

_log = logging.getLogger(__name__)

__all__ = [
    "APPLE_CLIMB_CM",
    "KEEPALIVE_COMMAND",
    "KEEPALIVE_INTERVAL_S",
    "PRESET_APPLE_RECOGNITION",
    "PRESET_PROGRAMS",
    "PRESET_SQUARE",
    "PRESET_TAKEOFF_HOVER_LAND",
    "PresetAction",
    "PresetIssue",
    "PresetProgram",
    "PresetRunner",
    "PresetStep",
    "estimated_preset_duration_s",
    "validate_preset",
]

OBSERVATION_MAX_S = 90.0
"""Upper bound for one observation step; also keeps the total under the limit."""

KEEPALIVE_INTERVAL_S = 5.0
"""How often a long wait resets the Tello's no-command timer.

The standard Tello SDK lands the aircraft automatically when it receives no
command for 15 s. Five seconds leaves room for a lost reply and a retry.
"""

KEEPALIVE_COMMAND = "command"
"""A bare ``command``: the SDK handshake verb. It moves nothing.

The community uses it as the keepalive for a standard Tello (DJITelloPy's
``keepalive`` is an SDK 3.0 command this project must not use).
"""

_TAKEOFF_SECONDS = 5.0
_LAND_SECONDS = 5.0
_YAW_SECONDS_PER_90_DEG = 2.0
"""A rough yaw time for the estimate; it is not a promise of flight time."""


class PresetAction(StrEnum):
    TAKEOFF = "takeoff"
    HOLD = "hold"
    OBSERVE = "observe"
    YAW_LEFT = "yaw_left"
    YAW_RIGHT = "yaw_right"
    LEFT = "left"
    FORWARD = "forward"
    RIGHT = "right"
    BACK = "back"
    CLIMB = "up"
    LAND = "land"

    @property
    def label(self) -> str:
        return {
            PresetAction.TAKEOFF: "Take off",
            PresetAction.HOLD: "Hold position",
            PresetAction.OBSERVE: "Observe target",
            PresetAction.YAW_LEFT: "Turn left",
            PresetAction.YAW_RIGHT: "Turn right",
            PresetAction.LEFT: "Fly left",
            PresetAction.FORWARD: "Fly forward",
            PresetAction.RIGHT: "Fly right",
            PresetAction.BACK: "Fly backward",
            PresetAction.CLIMB: "Climb",
            PresetAction.LAND: "Land",
        }[self]

    @property
    def is_takeoff(self) -> bool:
        return self is PresetAction.TAKEOFF

    @property
    def is_landing(self) -> bool:
        return self is PresetAction.LAND

    @property
    def is_hold(self) -> bool:
        return self is PresetAction.HOLD

    @property
    def is_observation(self) -> bool:
        return self is PresetAction.OBSERVE

    @property
    def is_yaw(self) -> bool:
        return self in (PresetAction.YAW_LEFT, PresetAction.YAW_RIGHT)

    @property
    def is_translation(self) -> bool:
        return self in (
            PresetAction.LEFT,
            PresetAction.FORWARD,
            PresetAction.RIGHT,
            PresetAction.BACK,
        )

    @property
    def is_climb(self) -> bool:
        """True for a vertical climb after takeoff.

        The climb is relative to the takeoff hover height, not an absolute
        altitude: a standard Tello has no altitude setpoint to hold.
        """
        return self is PresetAction.CLIMB


@dataclass(frozen=True, slots=True)
class PresetStep:
    """One ordered step in a preset program.

    Which fields are meaningful depends on ``action``:
    ``HOLD`` and ``OBSERVE`` use ``hold_s``, a yaw step uses ``degrees``, a
    translation uses ``distance_cm`` and ``speed_cm_s``, and a climb uses
    ``distance_cm`` only (the SDK's ``up x`` has no speed argument). Validation
    rejects a step that carries a field its action does not use, so a typo cannot
    silently fly the wrong value.
    """

    action: PresetAction
    distance_cm: int = 0
    speed_cm_s: int | None = None
    hold_s: float = 0.0
    degrees: int = 0

    @classmethod
    def takeoff(cls) -> PresetStep:
        return cls(PresetAction.TAKEOFF)

    @classmethod
    def hold(cls, seconds: float) -> PresetStep:
        return cls(PresetAction.HOLD, hold_s=seconds)

    @classmethod
    def observe(cls, seconds: float) -> PresetStep:
        """Hold position while the operator shows the target to the camera.

        No flight command is sent. The UI, not this Qt-free module, runs the
        detection and draws the target.
        """
        return cls(PresetAction.OBSERVE, hold_s=seconds)

    @classmethod
    def turn_left(cls, degrees: int = 90) -> PresetStep:
        return cls(PresetAction.YAW_LEFT, degrees=degrees)

    @classmethod
    def turn_right(cls, degrees: int = 90) -> PresetStep:
        return cls(PresetAction.YAW_RIGHT, degrees=degrees)

    @classmethod
    def forward(cls, distance_cm: int, speed_cm_s: int = 30) -> PresetStep:
        return cls(PresetAction.FORWARD, distance_cm=distance_cm, speed_cm_s=speed_cm_s)

    @classmethod
    def climb(cls, distance_cm: int) -> PresetStep:
        """Climb ``distance_cm`` above the current hover height.

        The standard SDK has no per-move speed and no absolute altitude
        setpoint, so this is a relative ``up`` command at the aircraft's
        configured speed.
        """
        return cls(PresetAction.CLIMB, distance_cm=distance_cm)

    @classmethod
    def land(cls) -> PresetStep:
        return cls(PresetAction.LAND)

    @property
    def sdk_command(self) -> str | None:
        """The flight command this step sends, or ``None`` for a wait.

        A wait sends no flight command; a long hold or an observation still
        sends periodic ``command`` keepalives so the Tello does not auto-land.
        """
        if self.action.is_takeoff:
            return "takeoff"
        if self.action.is_landing:
            return "land"
        if self.action.is_hold or self.action.is_observation:
            return None
        if self.action is PresetAction.YAW_LEFT:
            return f"ccw {self.degrees}"
        if self.action is PresetAction.YAW_RIGHT:
            return f"cw {self.degrees}"
        if self.action.is_climb:
            # The SDK's ``up x`` has no speed argument; ``speed x`` would be a
            # separate command the step does not need.
            return f"up {self.distance_cm}"
        return f"{self.action.value} {self.distance_cm} {self.speed_cm_s}"

    @property
    def detail(self) -> str:
        if self.action.is_takeoff:
            return "standard takeoff to hover height"
        if self.action.is_landing:
            return "standard landing command"
        if self.action.is_hold:
            return f"wait {self.hold_s:g} s; keepalive only, no flight command"
        if self.action.is_observation:
            return (
                f"observe the YOLO target for up to {self.hold_s:g} s; "
                "keepalive only, no flight command"
            )
        if self.action.is_yaw:
            return f"turn {self.degrees}°"
        if self.action.is_climb:
            return f"climb {self.distance_cm} cm above the takeoff hover height"
        return f"{self.distance_cm} cm at {self.speed_cm_s} cm/s"


@dataclass(frozen=True, slots=True)
class PresetProgram:
    """A named, ordered preset program. Read-only by design."""

    program_id: str
    title: str
    summary: str
    steps: tuple[PresetStep, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.program_id:
            raise ValueError("PresetProgram.program_id must not be empty")
        if not self.title:
            raise ValueError("PresetProgram.title must not be empty")
        if not self.steps:
            raise ValueError("PresetProgram.steps must not be empty")

    @property
    def movement_count(self) -> int:
        return sum(1 for step in self.steps if step.action.is_translation)

    @property
    def command_count(self) -> int:
        return sum(1 for step in self.steps if step.sdk_command is not None)

    @property
    def has_observation(self) -> bool:
        """True when the UI must show the camera and run target detection."""
        return any(step.action.is_observation for step in self.steps)


@dataclass(frozen=True, slots=True)
class PresetIssue:
    step_index: int | None
    message: str

    def describe(self) -> str:
        if self.step_index is None:
            return self.message
        return f"Step {self.step_index + 1}: {self.message}"


def estimated_preset_duration_s(
    program: PresetProgram,
    limits: SafetyLimits = CONSERVATIVE_LIMITS,
) -> float:
    """A rough estimate that includes the takeoff settle wait.

    Yaw time is approximated and the Tello's actual timing varies; the UI must
    present this as an estimate, never as a promise.
    """
    seconds = limits.takeoff_settle_s
    for step in program.steps:
        if step.action.is_takeoff:
            seconds += _TAKEOFF_SECONDS
        elif step.action.is_landing:
            seconds += _LAND_SECONDS
        elif step.action.is_hold or step.action.is_observation:
            seconds += step.hold_s
        elif step.action.is_yaw:
            seconds += max(1.0, _YAW_SECONDS_PER_90_DEG * step.degrees / 90.0)
        else:
            # A climb has no speed of its own; the aircraft flies it at the
            # speed it already holds, so the estimate assumes a modest 30 cm/s.
            seconds += step.distance_cm / (step.speed_cm_s or 30)
    return round(seconds, 1)


def validate_preset(
    program: PresetProgram,
    limits: SafetyLimits = CONSERVATIVE_LIMITS,
) -> tuple[PresetIssue, ...]:
    """Every reason the program must not fly. Empty means it is within limits."""
    issues: list[PresetIssue] = []
    if not program.steps:
        return (PresetIssue(None, "The program has no steps."),)

    takeoffs = sum(1 for step in program.steps if step.action.is_takeoff)
    landings = sum(1 for step in program.steps if step.action.is_landing)
    if not program.steps[0].action.is_takeoff:
        issues.append(PresetIssue(0, "the program must start with takeoff."))
    if not program.steps[-1].action.is_landing:
        issues.append(
            PresetIssue(len(program.steps) - 1, "the program must end with landing.")
        )
    if takeoffs != 1:
        issues.append(PresetIssue(None, "the program must contain exactly one takeoff."))
    if landings != 1:
        issues.append(PresetIssue(None, "the program must contain exactly one landing."))
    for index, step in enumerate(program.steps[:-1]):
        if step.action.is_landing:
            issues.append(
                PresetIssue(index, "landing must be the last step; no step may follow it.")
            )

    for index, step in enumerate(program.steps):
        if step.action.is_takeoff or step.action.is_landing:
            if step.distance_cm or step.speed_cm_s is not None or step.hold_s or step.degrees:
                issues.append(
                    PresetIssue(
                        index,
                        f"{step.action.label.lower()} takes no distance, speed, "
                        "hold or turn angle.",
                    )
                )
        elif step.action.is_hold:
            if step.distance_cm or step.speed_cm_s is not None or step.degrees:
                issues.append(
                    PresetIssue(index, "a hold takes no distance, speed or turn angle.")
                )
            if not 0.1 <= step.hold_s <= 30.0:
                issues.append(PresetIssue(index, "hold must be within 0.1..30 s."))
        elif step.action.is_observation:
            if step.distance_cm or step.speed_cm_s is not None or step.degrees:
                issues.append(
                    PresetIssue(
                        index,
                        "an observation takes no distance, speed or turn angle.",
                    )
                )
            if not 1.0 <= step.hold_s <= OBSERVATION_MAX_S:
                issues.append(
                    PresetIssue(
                        index,
                        f"observation must be within 1..{OBSERVATION_MAX_S:g} s.",
                    )
                )
        elif step.action.is_yaw:
            if step.distance_cm or step.speed_cm_s is not None or step.hold_s:
                issues.append(
                    PresetIssue(index, "a turn takes no distance, speed or hold.")
                )
            if not 1 <= step.degrees <= 360:
                issues.append(PresetIssue(index, "turn must be within 1..360 degrees."))
        elif step.action.is_climb:
            if step.speed_cm_s is not None or step.hold_s or step.degrees:
                issues.append(
                    PresetIssue(index, "a climb takes no speed, hold or turn angle.")
                )
            if not 20 <= step.distance_cm <= limits.max_altitude_cm:
                issues.append(
                    PresetIssue(
                        index,
                        f"climb must be within 20..{limits.max_altitude_cm} cm; the "
                        "Tello SDK does not accept a shorter movement and the climb "
                        "limit is the configured altitude limit.",
                    )
                )
        else:
            if step.hold_s or step.degrees:
                issues.append(
                    PresetIssue(index, "a movement takes no hold or turn angle.")
                )
            if not 20 <= step.distance_cm <= 500:
                issues.append(
                    PresetIssue(index, "distance must be within 20..500 cm; the Tello "
                                 "SDK does not accept a shorter movement.")
                )
            elif step.distance_cm > limits.max_segment_distance_cm:
                issues.append(
                    PresetIssue(
                        index,
                        f"distance {step.distance_cm} cm exceeds the "
                        f"{limits.max_segment_distance_cm} cm segment limit.",
                    )
                )
            if step.speed_cm_s is None:
                issues.append(PresetIssue(index, "speed is required for a movement."))
            elif not 10 <= step.speed_cm_s <= 100:
                issues.append(PresetIssue(index, "speed must be within 10..100 cm/s."))
            elif step.speed_cm_s > limits.max_speed_cm_s:
                issues.append(
                    PresetIssue(
                        index,
                        f"speed {step.speed_cm_s} cm/s exceeds the "
                        f"{limits.max_speed_cm_s} cm/s limit.",
                    )
                )

    duration = estimated_preset_duration_s(program, limits)
    if duration > limits.max_mission_duration_s:
        issues.append(
            PresetIssue(
                None,
                f"estimated duration {duration:.1f} s exceeds the "
                f"{limits.max_mission_duration_s} s program limit.",
            )
        )
    return tuple(issues)


PRESET_TAKEOFF_HOVER_LAND = PresetProgram(
    program_id="takeoff-hover-land",
    title="Take off, hover 3 s, land",
    summary=(
        "The shortest useful program and the first one to try: take off, hold "
        "position for three seconds, then land."
    ),
    steps=(
        PresetStep.takeoff(),
        PresetStep.hold(3.0),
        PresetStep.land(),
    ),
    note=(
        "A hold is a wait in this application: it sends no flight command, so the "
        "Tello hovers on its own. A hold longer than five seconds also sends a bare "
        "command keepalive every five seconds, because a standard Tello lands "
        "itself after 15 s without any command; the keepalive moves nothing."
    ),
)

PRESET_SQUARE = PresetProgram(
    program_id="four-left-turns",
    title="Four left turns — 30 cm legs",
    summary=(
        "Take off, then fly one leg after each left turn: four left turns and "
        "four forward legs, followed by landing."
    ),
    steps=(
        PresetStep.takeoff(),
        PresetStep.turn_left(90),
        PresetStep.forward(30, 30),
        PresetStep.turn_left(90),
        PresetStep.forward(30, 30),
        PresetStep.turn_left(90),
        PresetStep.forward(30, 30),
        PresetStep.turn_left(90),
        PresetStep.forward(30, 30),
        PresetStep.land(),
    ),
    note=(
        "This program flies four 30 cm legs — about 1.2 m of travel in total. "
        "The Tello SDK's minimum movement is 20 cm, so a shorter leg cannot be "
        "sent. The loop is approximate: a standard Tello has no reliable indoor "
        "global position and will not return to its exact start point."
    ),
)

APPLE_CLIMB_CM = 50
"""Climb after takeoff for the apple preset.

The takeoff itself hovers about one metre up (the same wording the operator
docs use), so a 50 cm climb puts the demonstration near 1.5 m above the floor —
the configured altitude limit. A standard Tello has no altitude setpoint, so
1.5 m is the target, not a value the app can hold.
"""

PRESET_APPLE_RECOGNITION = PresetProgram(
    program_id="apple-recognition",
    title="Take off, hold, recognize an apple",
    summary=(
        "Take off, climb 50 cm to about 1.5 m, and hover while the "
        "operator shows an apple to the aircraft camera. The live camera runs YOLO "
        "for the configured target class — apple by default — and marks it in a "
        "green box. Press EMERGENCY LAND to land; the program then stops without "
        "sending a second landing."
    ),
    steps=(
        PresetStep.takeoff(),
        PresetStep.climb(APPLE_CLIMB_CM),
        PresetStep.observe(OBSERVATION_MAX_S),
        PresetStep.land(),
    ),
    note=(
        "After takeoff the program sends one climb of 50 cm, so the observation "
        "sits near 1.5 m above the floor: takeoff hover height (about one metre) "
        "plus the climb. That height is approximate — a standard Tello has no "
        "altitude setpoint and does not hold an exact height; watch the height in "
        "the Drone Control tab. The observation lasts up to 90 s. No flight command "
        "is sent during it, so the aircraft hovers on its own — a standard Tello has "
        "no position hold and may drift with the air. The program sends a bare "
        "command keepalive every 5 s so the aircraft does not land itself after 15 s "
        "without a command; the keepalive moves nothing. The camera starts with the "
        "program and stops when it ends. EMERGENCY LAND in "
        "the top bar lands the aircraft at any time and stops the program, so its "
        "own landing is not sent. If nobody lands first, the program sends its "
        "standard landing when the observation ends; that is a fallback, not the "
        "expected way to land. Stop Program leaves the aircraft airborne. Live "
        "camera commands are streamon/streamoff only; YOLO boxes are display-only."
    ),
)

PRESET_PROGRAMS: tuple[PresetProgram, ...] = (
    PRESET_TAKEOFF_HOVER_LAND,
    PRESET_SQUARE,
    PRESET_APPLE_RECOGNITION,
)
"""Ordered programs shown in the Preset Flight Missions tab."""


def _landing_confirmed(commands: Iterable[CommandResult]) -> bool:
    """True only when the landing was upgraded by independent telemetry.

    A plain ``SENT`` landing stays unconfirmed; only the adapter's ``CONFIRMED``
    status (telemetry received after the acknowledgement reporting height 0)
    qualifies. The wording must not claim more than that evidence supports.
    """
    return any(
        command.command == "land" and command.status is CommandStatus.CONFIRMED
        for command in commands
    )


class PresetRunner:
    """Runs one preset program sequentially; safe to cancel from another thread."""

    def __init__(
        self,
        drone: DroneAdapter,
        program: PresetProgram,
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
        self._program = program
        self._limits = limits
        self._telemetry = telemetry or drone.telemetry
        self._takeoff_settle_s = takeoff_settle_s
        self._telemetry_max_age_s = telemetry_max_age_s
        self._clock = clock
        self._sleep = sleep
        self._cancel = threading.Event()
        self._cancel_reason = ""

    @property
    def program(self) -> PresetProgram:
        return self._program

    @property
    def cancelling(self) -> bool:
        return self._cancel.is_set()

    def cancel(self, reason: str = "Stopped by the operator.") -> None:
        """Stop issuing new steps. The command already in flight still finishes."""
        self._cancel_reason = reason
        self._cancel.set()

    def run(self, *, operator_confirmed: bool) -> MissionResult:
        """Execute the program. Requires explicit confirmation; never auto-starts.

        Every gate decision, step and command outcome is logged so that a run
        that ends in a link loss leaves a timeline in the application log.
        """
        started_at = self._clock()
        _log.info(
            "Preset run requested",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "title": self._program.title,
                    "steps": len(self._program.steps),
                    "operator_confirmed": operator_confirmed,
                }
            },
        )
        result = self._run(operator_confirmed=operator_confirmed)
        landing_confirmed = _landing_confirmed(result.commands)
        level = (
            logging.INFO
            if result.outcome is MissionOutcome.COMPLETED
            else logging.WARNING
        )
        _log.log(
            level,
            "Preset run finished",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "outcome": result.outcome.value,
                    "commands_sent": len(result.commands),
                    "elapsed_s": round(self._clock() - started_at, 2),
                    "landing_confirmed": landing_confirmed,
                    "reason": result.reason,
                }
            },
        )
        return result

    def _run(self, *, operator_confirmed: bool) -> MissionResult:
        if not operator_confirmed:
            return self._reject(
                "Preset execution requires explicit operator confirmation."
            )
        issues = validate_preset(self._program, self._limits)
        if issues:
            return self._reject(
                "The preset is outside the safety limits: "
                + "; ".join(issue.describe() for issue in issues),
            )
        if not self._drone.connected:
            return self._reject(
                "Connect to the aircraft before starting a preset program."
            )

        telemetry = self._telemetry()
        battery = telemetry.battery_percent
        if battery is None:
            return self._reject("Battery has not been reported; takeoff is blocked.")
        if not self._telemetry_is_fresh(telemetry):
            return self._reject(
                "Telemetry is stale or has not been received; the program is blocked "
                "until the aircraft reports a current battery level.",
            )
        if battery < self._limits.min_battery_percent_for_takeoff:
            return self._reject(
                f"Battery {battery}% is below the takeoff minimum "
                f"{self._limits.min_battery_percent_for_takeoff}%.",
            )
        _log.info(
            "Preset gates passed",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "battery_percent": battery,
                    "temperature_c": telemetry.temperature_c,
                    "height_cm": telemetry.height_cm,
                    "telemetry_age_s": self._age_s(telemetry),
                    "telemetry_max_age_s": self._telemetry_max_age_s,
                    "takeoff_settle_s": self._takeoff_settle_s,
                }
            },
        )

        commands: list[CommandResult] = []
        for index, step in enumerate(self._program.steps, start=1):
            if self._cancel.is_set():
                return MissionResult(
                    MissionOutcome.CANCELLED, self._cancel_reason, tuple(commands)
                )
            _log.info(
                "Preset step starting",
                extra={
                    "context": {
                        "step": index,
                        "of": len(self._program.steps),
                        "action": step.action.value,
                        "command": step.sdk_command,
                    }
                },
            )
            if step.action.is_translation or step.action.is_yaw or step.action.is_climb:
                telemetry = self._telemetry()
                fresh = self._telemetry_is_fresh(telemetry)
                if not fresh:
                    # A stale reading is not evidence about the present. Do not
                    # abort a flight on old data, but record that this step ran
                    # without a current battery reading.
                    _log.warning(
                        "In-flight battery check skipped: telemetry is stale",
                        extra={
                            "context": {
                                "step": index,
                                "action": step.action.value,
                                "telemetry_age_s": self._age_s(telemetry),
                                "telemetry_max_age_s": self._telemetry_max_age_s,
                            }
                        },
                    )
                # A stale reading is the last thing the aircraft said, not
                # evidence about the present. Ignore it rather than aborting a
                # flight on old data; the next fresh report can still abort it.
                battery = telemetry.battery_percent if fresh else None
                if (
                    battery is not None
                    and battery < self._limits.min_battery_percent_in_flight
                ):
                    return MissionResult(
                        MissionOutcome.ABORTED,
                        f"Battery {battery}% is below the in-flight minimum "
                        f"{self._limits.min_battery_percent_in_flight}%. Remaining "
                        "steps were not sent.",
                        tuple(commands),
                    )

            if step.action.is_hold or step.action.is_observation:
                # Report the age of the last sample the runner actually took.
                # Logging never takes a sample of its own, so it cannot change
                # what the gates below see.
                event = (
                    "Preset observation" if step.action.is_observation else "Preset hold"
                )
                _log.info(
                    f"{event} starting",
                    extra={
                        "context": {
                            "step": index,
                            "hold_s": step.hold_s,
                            "gate_sample_age_s": self._age_s(telemetry),
                        }
                    },
                )
                if not self._pause(step.hold_s, keepalive=True, step_index=index):
                    return MissionResult(
                        MissionOutcome.CANCELLED, self._cancel_reason, tuple(commands)
                    )
                _log.info(
                    f"{event} finished",
                    extra={
                        "context": {
                            "step": index,
                            "hold_s": step.hold_s,
                            "gate_sample_age_s": self._age_s(telemetry),
                        }
                    },
                )
                continue

            results = self._send(step)
            for result in results:
                _log.log(
                    logging.INFO if result.ok else logging.WARNING,
                    "Preset command outcome",
                    extra={
                        "context": {
                            "step": index,
                            "command": result.command,
                            "status": result.status.value,
                            "detail": result.detail,
                        }
                    },
                )
            commands.extend(results)
            failed = next((result for result in results if not result.ok), None)
            if failed is not None:
                # Read the cached snapshot fresh for the diagnosis: the sample
                # used by the gates can predate a takeoff by many seconds, and
                # logging its height as the failure-time height was misleading.
                # This only reads the cache; it consumes no telemetry reading.
                failed_state = self._telemetry()
                _log.warning(
                    "Preset aborted at a failed step",
                    extra={
                        "context": {
                            "step": index,
                            "action": step.action.value,
                            "command": failed.command,
                            "status": failed.status.value,
                            "battery_percent": failed_state.battery_percent,
                            "temperature_c": failed_state.temperature_c,
                            "height_cm": failed_state.height_cm,
                            "telemetry_age_s": self._age_s(failed_state),
                        }
                    },
                )
                return MissionResult(
                    MissionOutcome.ABORTED,
                    self._abort_reason(index, step, failed),
                    tuple(commands),
                )
            if step.action.is_takeoff:
                if not self._pause(self._takeoff_settle_s):
                    return MissionResult(
                        MissionOutcome.CANCELLED, self._cancel_reason, tuple(commands)
                    )
                _log.info(
                    "Takeoff settle finished",
                    extra={
                        "context": {
                            "settle_s": self._takeoff_settle_s,
                            # Age of the last sample taken, never a new one:
                            # logging must not consume a telemetry reading. The
                            # name says *gate sample*, not live telemetry age;
                            # the receiver may still be reporting at 10 Hz.
                            "gate_sample_age_s": self._age_s(telemetry),
                        }
                    },
                )

        if _landing_confirmed(commands):
            reason = (
                "Preset commands acknowledged and the landing was confirmed by "
                "telemetry received after the acknowledgement. A standard Tello does "
                "not return to its exact start point."
            )
        else:
            reason = (
                "Preset commands acknowledged. Landing still requires visual "
                "confirmation; a standard Tello does not return to its exact start "
                "point."
            )
        return MissionResult(MissionOutcome.COMPLETED, reason, tuple(commands))

    # -- internals -----------------------------------------------------------

    def _reject(self, reason: str) -> MissionResult:
        _log.warning(
            "Preset gates refused the run",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "reason": reason,
                }
            },
        )
        return MissionResult(MissionOutcome.REJECTED, reason)

    def _abort_reason(
        self, index: int, step: PresetStep, failed: CommandResult
    ) -> str:
        """Say which step failed and what the app can honestly infer about flight.

        A refused takeoff is the aircraft's own answer that this program did not
        lift it off; a timed-out takeoff is not, because the reply may simply have
        been lost. Mid-program failures leave the aircraft airborne.
        """
        detail = failed.detail if failed.detail.endswith(".") else f"{failed.detail}."
        reason = (
            f"Step {index} ({step.action.value}) did not succeed: {detail} "
            "Remaining steps were not sent."
        )
        if any(later.action.is_observation for later in self._program.steps[index:]):
            # The observation is the step the demo exists for. Say plainly that
            # it never ran; the operator otherwise waits for a green box that
            # this run cannot produce.
            reason += (
                " The observation step did not run, so the target was not "
                "observed from the intended position."
            )
        refused_takeoff = (
            step.action.is_takeoff
            and failed.command == "takeoff"
            and failed.status is CommandStatus.FAILED
        )
        if refused_takeoff:
            return (
                reason
                + " The aircraft refused the takeoff, so this program did not take "
                "it off. Check that the phone app is not controlling it, that it is "
                "level and unobstructed, and that its battery is healthy. If it is "
                "already airborne under another controller, land it."
            )
        if step.action.is_takeoff and failed.command == "takeoff":
            return (
                reason
                + " The takeoff outcome is unknown: the aircraft may have taken off "
                "and may still be airborne — use Emergency Land if needed."
            )
        return (
            reason
            + " The aircraft may still be airborne — use Emergency Land if needed."
        )

    def _age_s(self, telemetry: Telemetry) -> float | None:
        """Age of the last state report in seconds, or ``None`` if never received."""
        received_at = telemetry.received_at
        if received_at is None:
            return None
        return round(max(0.0, self._clock() - received_at), 2)

    def _send(self, step: PresetStep) -> tuple[CommandResult, ...]:
        if step.action.is_takeoff:
            return (self._drone.takeoff(),)
        if step.action.is_landing:
            return (self._drone.land(),)
        if step.action is PresetAction.YAW_LEFT:
            return (self._drone.rotate("ccw", step.degrees),)
        if step.action is PresetAction.YAW_RIGHT:
            return (self._drone.rotate("cw", step.degrees),)
        return (
            self._drone.move(step.action.value, step.distance_cm, step.speed_cm_s),
        )

    def _telemetry_is_fresh(self, telemetry: Telemetry) -> bool:
        return telemetry_is_fresh(
            telemetry,
            now=self._clock(),
            max_age_s=self._telemetry_max_age_s,
        )

    def _pause(
        self,
        seconds: float,
        *,
        keepalive: bool = False,
        step_index: int | None = None,
    ) -> bool:
        """Wait locally without sending a flight command.

        With ``keepalive`` the wait also sends :data:`KEEPALIVE_COMMAND` every
        :data:`KEEPALIVE_INTERVAL_S`. A standard Tello lands itself after 15 s
        without any command, so an observation or long hold that sent nothing
        would end with the aircraft landing itself. The keepalive is the SDK
        handshake verb: it moves nothing, and it is not a flight step, so it is
        not added to the run's command results and cannot count as landing
        evidence.
        """
        deadline = self._clock() + seconds
        next_keepalive = self._clock() + KEEPALIVE_INTERVAL_S if keepalive else None
        while self._clock() < deadline:
            if self._cancel.is_set():
                return False
            now = self._clock()
            sleep_for = min(0.1, max(0.0, deadline - now))
            if next_keepalive is not None:
                sleep_for = min(sleep_for, max(0.0, next_keepalive - now))
            self._sleep(sleep_for)
            if self._cancel.is_set():
                return False
            now = self._clock()
            if next_keepalive is not None and now >= next_keepalive:
                if now >= deadline:
                    # The landing step follows immediately and resets the timer.
                    break
                self._send_keepalive(step_index)
                # Advance the schedule by one slot, not from "now": a slow or
                # timed-out send must not push the next keepalive past the
                # Tello's 15 s limit. Slots already consumed are skipped.
                next_keepalive += KEEPALIVE_INTERVAL_S
                while next_keepalive < self._clock():
                    next_keepalive += KEEPALIVE_INTERVAL_S
        return not self._cancel.is_set()

    def _send_keepalive(self, step_index: int | None) -> None:
        """Reset the Tello's no-command timer without moving the aircraft."""
        result = self._drone.send_command(
            KEEPALIVE_COMMAND,
            timeout=self._limits.command_timeout_s,
        )
        _log.log(
            logging.DEBUG if result.ok else logging.WARNING,
            "Preset keepalive sent" if result.ok else "Preset keepalive failed",
            extra={
                "context": {
                    "step": step_index,
                    "command": result.command,
                    "status": result.status.value,
                    "detail": result.detail,
                }
            },
        )
