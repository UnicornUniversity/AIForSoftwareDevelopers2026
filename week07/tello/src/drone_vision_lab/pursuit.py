"""Advisory-only target pursuit for the classroom rehearsal (Qt-free).

The advisor turns detection results into the yaw decision the real tracker
*would* make. It never holds a :class:`~drone_vision_lab.interfaces.drone.DroneAdapter`,
never imports the safety state and never sends anything: the message is the
whole output. This is what lets a Tello that reports a sensor error and cannot
take off still demonstrate yaw-only target pursuit.

The decision geometry (deadband, proportional gain, step limits) is shared with
:class:`~drone_vision_lab.tracking.TrackingController` through
:func:`~drone_vision_lab.tracking.yaw_command_for_error`, so the rehearsal and
the real tracker never disagree about a number. The rate limit, stale limit and
missed-result stop rule mirror the tracker as well.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .domain import BoundingBox, DetectionResult, DetectorKind
from .tracking import (
    DEFAULT_TRACKING_SETTINGS,
    TrackingCommand,
    TrackingSettings,
    yaw_command_for_error,
)

__all__ = ["PursuitAction", "PursuitAdvisor", "PursuitDecision"]

_ALLOWED_KINDS = frozenset({DetectorKind.OPENCV, DetectorKind.YOLO})


class PursuitAction(StrEnum):
    """What the advisor is telling the operator right now."""

    IDLE = "idle"
    CENTERED = "centered"
    YAW_LEFT = "yaw_left"
    YAW_RIGHT = "yaw_right"
    HOLDING = "holding"
    NO_TARGET = "no_target"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class PursuitDecision:
    """One advisory decision. Nothing here can reach an aircraft."""

    action: PursuitAction
    message: str
    error: float | None = None
    command: TrackingCommand | None = None
    target_box: BoundingBox | None = None
    misses: int = 0
    rate_limited: bool = False

    @property
    def stopped(self) -> bool:
        return self.action is PursuitAction.STOPPED

    @property
    def banner(self) -> str:
        """Display text that can never look like a command was issued."""
        disclaimer = (
            "no command was sent" if self.stopped else "no command is sent"
        )
        return f"ADVISORY ONLY — {disclaimer}. {self.message}"


def _capitalized(label: str) -> str:
    label = label.strip()
    if not label:
        return "Target"
    return label[:1].upper() + label[1:]


class PursuitAdvisor:
    """Decides yaw advisories; it has no way to execute one."""

    def __init__(
        self,
        *,
        settings: TrackingSettings = DEFAULT_TRACKING_SETTINGS,
        detector_kind: DetectorKind = DetectorKind.YOLO,
        target_label: str = "apple",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if detector_kind not in _ALLOWED_KINDS:
            raise ValueError(
                "The pursuit advisor supports OpenCV and YOLO only. The "
                "vision-language model is advisory and has no control path."
            )
        self._settings = settings
        self._kind = detector_kind
        self._target_label = target_label
        self._clock = clock
        self._active = False
        self._stop_reason = ""
        self._misses = 0
        self._last_result_at: float | None = None
        self._last_decision_at: float | None = None
        self._last_decision: PursuitDecision | None = None

    # -- inspection ----------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    @property
    def stop_reason(self) -> str:
        return self._stop_reason

    @property
    def settings(self) -> TrackingSettings:
        return self._settings

    @property
    def target_label(self) -> str:
        return self._target_label

    @property
    def last_decision(self) -> PursuitDecision | None:
        return self._last_decision

    def set_target_label(self, label: str) -> None:
        self._target_label = label

    # -- session -------------------------------------------------------------

    def start(self, *, now: float | None = None) -> PursuitDecision:
        """Become active and wait for the first detection."""
        self._active = True
        self._stop_reason = ""
        self._misses = 0
        self._last_result_at = None
        self._last_decision_at = None
        return self._make(
            PursuitAction.IDLE,
            f"Watching for the {self._target_label or 'target'}.",
        )

    def stop(self, reason: str = "Advisory stopped by the operator") -> PursuitDecision:
        """Stop and stay stopped until :meth:`start` is called again."""
        return self._finish(f"{reason} — advisory stopped.")

    # -- decisions -----------------------------------------------------------

    def process(
        self,
        result: DetectionResult,
        *,
        now: float | None = None,
    ) -> PursuitDecision:
        """Turn one detection result into an advisory decision."""
        if not self._active:
            return self._last_decision or self._idle()
        current = self._clock() if now is None else now

        if result.kind is not self._kind:
            return self._last_decision or self._idle()
        if result.failed:
            return self._finish(
                f"The detector failed: {result.error} — advisory stopped."
            )

        produced_at = result.processed_at or result.frame_timestamp
        if produced_at <= 0 or current - produced_at > self._settings.stale_after_s:
            return self._finish("Detector results are stale — advisory stopped.")

        self._last_result_at = current
        boxes = [detection.box for detection in result.detections if detection.box.normalized]
        label = _capitalized(self._target_label)
        if not boxes:
            self._misses += 1
            if self._misses >= self._settings.max_missed_results:
                return self._finish(
                    f"Target lost after {self._misses} consecutive misses — "
                    "advisory stopped. Press Resume advisories to continue."
                )
            return self._make(
                PursuitAction.NO_TARGET,
                f"No {self._target_label or 'target'} detected "
                f"({self._misses} of {self._settings.max_missed_results} misses) "
                "→ hold heading.",
                misses=self._misses,
            )

        self._misses = 0
        box = max(boxes, key=lambda item: item.area)
        error = box.center[0] - 0.5
        command = yaw_command_for_error(error, self._settings)
        if command is None:
            return self._make(
                PursuitAction.CENTERED,
                f"{label} is centered → hold heading.",
                error=error,
                target_box=box,
            )

        side = "left" if command.direction == "counter_clockwise" else "right"
        if (
            self._last_decision_at is not None
            and current - self._last_decision_at
            < self._settings.min_command_interval_s
        ):
            return self._make(
                PursuitAction.HOLDING,
                f"{label} is {side} of center → holding before the next advisory.",
                error=error,
                target_box=box,
                rate_limited=True,
            )

        self._last_decision_at = current
        action = (
            PursuitAction.YAW_LEFT
            if command.direction == "counter_clockwise"
            else PursuitAction.YAW_RIGHT
        )
        return self._make(
            action,
            f"{label} is {side} of center → yaw {side} {command.degrees}°.",
            error=error,
            command=command,
            target_box=box,
        )

    def check_health(self, *, now: float | None = None) -> PursuitDecision:
        """Called by a UI timer even when no new frame arrives."""
        if not self._active:
            return self._last_decision or self._idle()
        if self._last_result_at is None:
            # Nothing has been analyzed yet; waiting is honest, not stale.
            return self._last_decision or self._idle()
        current = self._clock() if now is None else now
        if current - self._last_result_at > self._settings.stale_after_s:
            return self._finish(
                "No fresh detector result arrived — advisory stopped."
            )
        return self._last_decision or self._idle()

    # -- internals -----------------------------------------------------------

    def _idle(self) -> PursuitDecision:
        return self._make(PursuitAction.IDLE, "Not running — start a source.")

    def _make(
        self,
        action: PursuitAction,
        message: str,
        *,
        error: float | None = None,
        command: TrackingCommand | None = None,
        target_box: BoundingBox | None = None,
        misses: int = 0,
        rate_limited: bool = False,
    ) -> PursuitDecision:
        decision = PursuitDecision(
            action=action,
            message=message,
            error=error,
            command=command,
            target_box=target_box,
            misses=misses,
            rate_limited=rate_limited,
        )
        self._last_decision = decision
        return decision

    def _finish(self, message: str) -> PursuitDecision:
        self._active = False
        self._stop_reason = message
        return self._make(PursuitAction.STOPPED, message)
