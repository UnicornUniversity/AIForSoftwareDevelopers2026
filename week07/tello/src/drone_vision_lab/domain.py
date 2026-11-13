"""Domain types shared by adapters, the application state model and the UI.

These types deliberately depend on nothing but the standard library and NumPy:
no Qt, no network, no model runtime. That keeps every adapter, fake and unit
test usable without a display, a drone or a GPU.

Video frame convention used throughout the project:

* ``Frame.image`` is a contiguous ``uint8`` NumPy array in OpenCV's BGR order
  with shape ``(height, width, 3)``.
* ``Frame.captured_at`` is a *monotonic* timestamp in seconds taken at the
  moment the frame was read from the source. Wall-clock time is only used for
  display and export; latency is always computed from monotonic values.
* ``Frame.index`` is the per-source frame counter, so dropped frames are
  detectable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

__all__ = [
    "BoundingBox",
    "CommandResult",
    "CommandStatus",
    "Detection",
    "DetectionResult",
    "DetectorKind",
    "Frame",
    "Telemetry",
    "telemetry_is_fresh",
]


class CommandStatus(StrEnum):
    """Outcome of a single command sent towards the aircraft.

    ``SENT`` and ``CONFIRMED`` are deliberately distinct: for a standard Tello
    an ``ok`` reply only proves the command was accepted, not that the state
    change happened. Landing, in particular, is never reported as confirmed
    unless a later observation (telemetry or video) supports it.
    """

    REJECTED = "rejected"
    """Refused locally by a safety check or a mission limit; nothing was transmitted."""

    REQUESTED = "requested"
    """Accepted by the application and queued; not yet transmitted."""

    SENT = "sent"
    """Transmitted and acknowledged by the aircraft's command channel."""

    CONFIRMED = "confirmed"
    """Transmitted *and* independently observed in telemetry."""

    FAILED = "failed"
    """Transmission failed or the aircraft replied with an error."""

    TIMEOUT = "timeout"
    """No reply within the configured timeout; the outcome is unknown."""

    @property
    def acknowledged(self) -> bool:
        """True when the aircraft is known to have accepted the command."""
        return self in (CommandStatus.SENT, CommandStatus.CONFIRMED)

    @property
    def outcome_unknown(self) -> bool:
        """True when the command may or may not have reached the aircraft."""
        return self in (CommandStatus.TIMEOUT, CommandStatus.REQUESTED)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of one command attempt.

    Never construct a ``CONFIRMED`` result from an acknowledgement alone; pass
    it only once a subsequent telemetry observation supports it.
    """

    command: str
    status: CommandStatus
    detail: str = ""
    requested_at: float = 0.0
    completed_at: float | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("CommandResult.command must not be empty")

    @property
    def ok(self) -> bool:
        return self.status.acknowledged


@dataclass(frozen=True, slots=True)
class Telemetry:
    """A telemetry snapshot.

    Every field is optional: a value stays ``None`` when the aircraft has not
    reported it. The UI must render ``None`` as "not reported" rather than
    guessing a plausible-looking number.
    """

    battery_percent: int | None = None
    height_cm: int | None = None
    flight_time_s: int | None = None
    wifi_snr: int | None = None
    temperature_c: float | None = None
    received_at: float | None = None

    def __post_init__(self) -> None:
        if self.battery_percent is not None and not 0 <= self.battery_percent <= 100:
            raise ValueError("battery_percent must be within 0..100")
        if self.height_cm is not None and self.height_cm < 0:
            raise ValueError("height_cm must not be negative")
        if self.flight_time_s is not None and self.flight_time_s < 0:
            raise ValueError("flight_time_s must not be negative")


def telemetry_is_fresh(
    telemetry: Telemetry,
    *,
    now: float,
    max_age_s: float,
) -> bool:
    """True only when the snapshot was received within ``max_age_s``.

    A snapshot with no ``received_at`` has never been received, so it is never
    fresh. A negative age means the caller's clock is behind the receiver's;
    that is treated as fresh rather than rejecting a report that is provably
    recent. Stale data must never be used to satisfy a safety gate.
    """
    received_at = telemetry.received_at
    if received_at is None:
        return False
    return now - received_at <= max_age_s


@dataclass(frozen=True, slots=True)
class Frame:
    """One captured image plus its provenance and timing."""

    image: np.ndarray
    captured_at: float
    source_id: str
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.image, np.ndarray):
            raise TypeError("Frame.image must be a numpy.ndarray")
        if self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError(f"Frame.image must be HxWx3 BGR, got shape {self.image.shape}")
        if self.image.dtype != np.uint8:
            raise ValueError(f"Frame.image must be uint8, got {self.image.dtype}")
        if not self.source_id:
            raise ValueError("Frame.source_id must not be empty")

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def shape(self) -> tuple[int, int]:
        """``(width, height)`` in pixels."""
        return self.width, self.height


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned box in either normalized ``[0, 1]`` or pixel units.

    Normalized boxes use ``x``/``y`` as the top-left corner and ``w``/``h`` as
    the size, with the origin at the top-left of the image. Constructor input
    is validated so a malformed model or detector output fails loudly at the
    boundary instead of producing a box that silently renders off-screen.
    """

    x: float
    y: float
    w: float
    h: float
    normalized: bool = True

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError("BoundingBox width and height must be positive")
        if self.normalized:
            if not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
                raise ValueError("Normalized bounding box origin must be within [0, 1]")
            if self.x + self.w > 1.0 + 1e-6 or self.y + self.h > 1.0 + 1e-6:
                raise ValueError("Normalized bounding box must not extend past the image")

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2.0, self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

    def to_pixels(self, frame_shape: tuple[int, int]) -> BoundingBox:
        """Convert a normalized box to whole pixels for the given ``(width, height)``."""
        if not self.normalized:
            return self
        width, height = frame_shape
        x = round(self.x * width)
        y = round(self.y * height)
        w = max(1, round(self.w * width))
        h = max(1, round(self.h * height))
        return BoundingBox(x, y, min(w, width - x), min(h, height - y), normalized=False)

    def to_normalized(self, frame_shape: tuple[int, int]) -> BoundingBox:
        """Convert a pixel box to normalized coordinates."""
        if self.normalized:
            return self
        width, height = frame_shape
        return BoundingBox(
            self.x / width,
            self.y / height,
            self.w / width,
            self.h / height,
            normalized=True,
        )


class DetectorKind(StrEnum):
    """The three vision families compared in the Computer Vision Lab."""

    OPENCV = "opencv"
    YOLO = "yolo"
    VLM = "vlm"


@dataclass(frozen=True, slots=True)
class Detection:
    """A single detected object.

    ``confidence`` is ``None`` when the algorithm has no defensible score.
    Classic threshold-and-contour detection has no probability, so it must not
    invent one; use ``metrics`` (e.g. mask fill ratio) if a quality indicator is
    needed, and label it as such in the UI.
    """

    label: str
    box: BoundingBox
    confidence: float | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("Detection.label must not be empty")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Detection.confidence must be within [0, 1] or None")


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Output of one detector run over one frame.

    ``error`` set means the detector failed for this frame; ``detections`` empty
    with ``error is None`` means the detector ran and found no target. The UI
    must keep those two states visually distinct.
    """

    detector_name: str
    kind: DetectorKind
    detections: tuple[Detection, ...] = ()
    frame_timestamp: float = 0.0
    processed_at: float = 0.0
    latency_ms: float | None = None
    error: str | None = None
    detail: str = ""
    """Untrusted, display-only text from the detector (e.g. the raw VLM answer).

    Never parse this back into behaviour and never feed it to flight control.
    """

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def found(self) -> bool:
        return not self.failed and bool(self.detections)

    @property
    def age_seconds(self) -> float:
        """How long ago this result was produced relative to its source frame."""
        return max(0.0, self.processed_at - self.frame_timestamp)
