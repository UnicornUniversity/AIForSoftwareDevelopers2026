"""Yaw-only target tracking (Qt-free).

The controller turns detection results into bounded yaw decisions. It never
moves the aircraft toward or away from the target, never changes altitude and
never calls the drone itself: the UI submits :class:`TrackingCommand` to a
background runner so the GUI thread never waits for a UDP reply.

Safety rules encoded here:

* Only OpenCV and YOLO are accepted. Constructing a controller for any other
  detector kind raises, so the advisory vision-language model has no path to
  the flight controller.
* Tracking starts only when autonomy was explicitly armed after a dry run and
  the aircraft is already flying under manual control.
* A stale result, a failed detector, repeated target loss or the session time
  limit ends the session. The caller moves the state to operator attention; it
  does not land by itself.
* Corrections are proportional, saturate at a small step and are rate limited.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import SafetyLimits
from .domain import DetectionResult, DetectorKind
from .interfaces.drone import DroneAdapter
from .state import AppStateSnapshot, SafetyState

__all__ = [
    "DEFAULT_TRACKING_SETTINGS",
    "TrackingCommand",
    "TrackingController",
    "TrackingSettings",
    "TrackingUpdate",
    "yaw_command_for_error",
]

_ALLOWED_KINDS = frozenset({DetectorKind.OPENCV, DetectorKind.YOLO})


@dataclass(frozen=True, slots=True)
class TrackingSettings:
    """Conservative classroom defaults."""

    deadband: float = 0.10
    """Normalized horizontal error ignored as "already centred"."""

    gain_deg_per_unit: float = 30.0
    """Proportional gain: error 1.0 would ask for 30°, then saturate."""

    min_step_deg: int = 5
    max_step_deg: int = 20
    min_command_interval_s: float = 0.6
    stale_after_s: float = 0.5
    """A detection produced longer ago than this is too old to act on."""

    max_missed_results: int = 3
    """Consecutive no-target results before the session ends."""

    session_limit_s: float = 60.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.deadband < 0.5:
            raise ValueError("deadband must be within 0.0..0.5")
        if self.gain_deg_per_unit <= 0:
            raise ValueError("gain_deg_per_unit must be positive")
        if not 1 <= self.min_step_deg <= self.max_step_deg <= 90:
            raise ValueError("yaw steps must satisfy 1 <= min <= max <= 90")
        if self.min_command_interval_s < 0:
            raise ValueError("min_command_interval_s must not be negative")
        if self.stale_after_s <= 0:
            raise ValueError("stale_after_s must be positive")
        if self.max_missed_results < 1:
            raise ValueError("max_missed_results must be at least 1")
        if self.session_limit_s <= 0:
            raise ValueError("session_limit_s must be positive")


DEFAULT_TRACKING_SETTINGS = TrackingSettings()


@dataclass(frozen=True, slots=True)
class TrackingCommand:
    """One yaw step. ``direction`` is the drone adapter's yaw direction."""

    direction: str
    degrees: int
    error: float

    def __post_init__(self) -> None:
        if self.direction not in ("clockwise", "counter_clockwise"):
            raise ValueError(f"Unsupported yaw direction: {self.direction!r}")
        if not 1 <= self.degrees <= 90:
            raise ValueError("Tracking yaw degrees must be within 1..90")

    def describe(self) -> str:
        side = "right" if self.direction == "clockwise" else "left"
        return f"yaw {side} {self.degrees}° (error {self.error:+.2f})"


def yaw_command_for_error(
    error: float,
    settings: TrackingSettings = DEFAULT_TRACKING_SETTINGS,
) -> TrackingCommand | None:
    """Return the bounded yaw step for a normalized horizontal error.

    ``None`` means the error is inside the deadband and no correction is
    needed. This is the pure decision geometry: it applies no rate limit, reads
    no clock and never touches an aircraft. The tracking controller and the
    advisory-only pursuit rehearsal share it so both speak the same numbers.
    """
    if abs(error) <= settings.deadband:
        return None
    degrees = round(abs(error) * settings.gain_deg_per_unit)
    degrees = max(settings.min_step_deg, min(settings.max_step_deg, degrees))
    return TrackingCommand(
        direction="counter_clockwise" if error < 0 else "clockwise",
        degrees=degrees,
        error=error,
    )


@dataclass(frozen=True, slots=True)
class TrackingUpdate:
    """What the UI should do with one processed result."""

    command: TrackingCommand | None = None
    error: float | None = None
    centered: bool = False
    rate_limited: bool = False
    target_lost: bool = False
    stop_reason: str | None = None

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None


class TrackingController:
    """Decides yaw corrections; the caller executes and reports failures."""

    def __init__(
        self,
        drone: DroneAdapter,
        *,
        detector_kind: DetectorKind,
        settings: TrackingSettings = DEFAULT_TRACKING_SETTINGS,
        limits: SafetyLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
        detector_ready: Callable[[], bool] | None = None,
        on_error: Callable[[float], None] | None = None,
    ) -> None:
        if detector_kind not in _ALLOWED_KINDS:
            raise ValueError(
                "Tracking supports OpenCV and YOLO only. The vision-language "
                "model is advisory and has no path to flight control."
            )
        if limits is not None:
            settings = TrackingSettings(
                deadband=settings.deadband,
                gain_deg_per_unit=settings.gain_deg_per_unit,
                min_step_deg=settings.min_step_deg,
                max_step_deg=settings.max_step_deg,
                min_command_interval_s=settings.min_command_interval_s,
                stale_after_s=settings.stale_after_s,
                max_missed_results=settings.max_missed_results,
                session_limit_s=min(settings.session_limit_s, limits.max_tracking_session_s),
            )
        self._drone = drone
        self._kind = detector_kind
        self._settings = settings
        self._clock = clock
        self._detector_ready = detector_ready or (lambda: True)
        self._on_error = on_error
        self._active = False
        self._started_at: float | None = None
        self._last_result_at: float | None = None
        self._last_command_at: float | None = None
        self._misses = 0
        self._last_stop_reason = ""

    # -- inspection ----------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    @property
    def detector_kind(self) -> DetectorKind:
        return self._kind

    @property
    def settings(self) -> TrackingSettings:
        return self._settings

    @property
    def last_stop_reason(self) -> str:
        return self._last_stop_reason

    def elapsed_s(self, now: float | None = None) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock_or(now) - self._started_at)

    # -- session -------------------------------------------------------------

    def start(self, snapshot: AppStateSnapshot) -> str:
        """Begin a session; returns ``""`` or the refusal reason."""
        if self._active:
            return "Tracking is already active."
        if not self._drone.connected or not snapshot.drone_connected:
            return "Connect to the aircraft before starting tracking."
        if snapshot.safety_state is not SafetyState.FLYING_MANUAL:
            return (
                "Tracking starts only while the aircraft is flying under manual "
                "control. Take off with explicit manual control first."
            )
        if not snapshot.autonomy_armed:
            return "Autonomy is not armed. Arm it after a successful dry run first."
        if self._kind.value not in snapshot.dry_run_passed_kinds:
            return "Run a successful dry run for the selected detector first."
        if not self._detector_ready():
            return "The selected detector is not ready; reload or reconfigure it."

        now = self._clock()
        self._active = True
        self._started_at = now
        self._last_result_at = now
        self._last_command_at = None
        self._misses = 0
        self._last_stop_reason = ""
        return ""

    def stop(self, reason: str = "Tracking stopped by the operator.") -> None:
        self._active = False
        self._last_stop_reason = reason

    # -- decisions -----------------------------------------------------------

    def process(
        self,
        result: DetectionResult,
        *,
        now: float | None = None,
    ) -> TrackingUpdate:
        """Process one detection result and decide whether to yaw."""
        if not self._active:
            return TrackingUpdate()
        current = self._clock_or(now)

        expired = self._session_limit_reason(current)
        if expired:
            return self._finish(expired)
        if result.kind is not self._kind:
            return TrackingUpdate()
        if result.failed:
            return self._finish(
                "The selected detector failed; tracking stopped. "
                "The aircraft is still airborne."
            )

        produced_at = result.processed_at or result.frame_timestamp
        if produced_at <= 0 or current - produced_at > self._settings.stale_after_s:
            return self._finish(
                "Detector results are stale; tracking stopped. "
                "The aircraft is still airborne."
            )

        self._last_result_at = current
        boxes = [detection.box for detection in result.detections if detection.box.normalized]
        if not boxes:
            self._misses += 1
            if self._misses >= self._settings.max_missed_results:
                return self._finish(
                    "Target lost; tracking stopped. The aircraft is still airborne."
                )
            return TrackingUpdate(target_lost=True)

        self._misses = 0
        box = max(boxes, key=lambda item: item.area)
        error = box.center[0] - 0.5
        if self._on_error is not None:
            self._on_error(abs(error))

        command = yaw_command_for_error(error, self._settings)
        if command is None:
            return TrackingUpdate(error=error, centered=True)
        if (
            self._last_command_at is not None
            and current - self._last_command_at < self._settings.min_command_interval_s
        ):
            return TrackingUpdate(error=error, rate_limited=True)

        self._last_command_at = current
        return TrackingUpdate(error=error, command=command)

    def check_health(self, *, now: float | None = None) -> TrackingUpdate:
        """Called by a UI timer even when no new frame arrives."""
        if not self._active:
            return TrackingUpdate()
        current = self._clock_or(now)
        expired = self._session_limit_reason(current)
        if expired:
            return self._finish(expired)
        last_signal = self._last_result_at if self._last_result_at is not None else current
        if current - last_signal > self._settings.stale_after_s:
            return self._finish(
                "No fresh detector result arrived; tracking stopped. "
                "The aircraft is still airborne."
            )
        return TrackingUpdate()

    # -- internals -----------------------------------------------------------

    def _clock_or(self, now: float | None) -> float:
        return self._clock() if now is None else now

    def _session_limit_reason(self, now: float) -> str | None:
        if self._started_at is None:
            return None
        if now - self._started_at >= self._settings.session_limit_s:
            return (
                f"Tracking session reached its {self._settings.session_limit_s:.0f} s "
                "limit; tracking stopped. The aircraft is still airborne."
            )
        return None

    def _finish(self, reason: str) -> TrackingUpdate:
        self._active = False
        self._last_stop_reason = reason
        return TrackingUpdate(stop_reason=reason)
