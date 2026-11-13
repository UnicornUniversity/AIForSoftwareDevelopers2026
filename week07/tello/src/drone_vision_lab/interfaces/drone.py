"""Drone adapter interface.

Every aircraft interaction goes through one adapter so the simulated drone, the
fake test drone and the real Tello share a single contract. Implementations are
expected to serialize commands internally: the application must never have two
threads writing to the command channel at once.

The interface models *intent* rather than Tello SDK strings. That keeps
EDU-only or vendor-specific details inside the adapter, and lets the safety
layer reject an intent before anything reaches the wire.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain import CommandResult, Telemetry

__all__ = ["DroneAdapter", "MovementDirection", "RotationDirection"]

MovementDirection = str
"""One of ``"up"``, ``"down"``, ``"left"``, ``"right"``, ``"forward"``, ``"back"``."""

RotationDirection = str
"""One of ``"clockwise"`` (``"cw"``) or ``"counter_clockwise"`` (``"ccw"``)."""


@runtime_checkable
class DroneAdapter(Protocol):
    """Control and observation contract for the aircraft."""

    @property
    def connected(self) -> bool:
        """True only while the command channel is known to be usable."""

    def connect(self, timeout: float = 10.0) -> CommandResult:
        """Open the command and state channels. Never takes off."""

    def disconnect(self) -> None:
        """Close all channels. Must be safe to call when already disconnected."""

    def send_command(self, command: str, timeout: float = 5.0) -> CommandResult:
        """Send a raw SDK command.

        Escape hatch for the few SDK verbs with no modeled method. Callers are
        responsible for safety checks; the adapter is responsible for
        serialization and timeouts.
        """

    def takeoff(self, timeout: float = 20.0) -> CommandResult:
        """Request takeoff. Only valid when landed and connected."""

    def land(self, timeout: float = 20.0) -> CommandResult:
        """Request a normal landing."""

    def emergency_land(self, timeout: float = 5.0) -> CommandResult:
        """Request an immediate landing, preempting queued commands.

        Sends the standard ``land`` command. It must not cut motors, and it must
        report ``SENT``-at-best when the command channel is available. When the
        channel is gone the result is ``FAILED`` or ``TIMEOUT`` and the UI must
        say the landing could not be confirmed.
        """

    def move(
        self,
        direction: MovementDirection,
        distance_cm: int,
        speed: int | None = None,
        timeout: float = 10.0,
    ) -> CommandResult:
        """Translate in body frame. ``speed`` in cm/s when supported."""

    def rotate(
        self,
        direction: RotationDirection,
        degrees: int,
        timeout: float = 10.0,
    ) -> CommandResult:
        """Rotate in place by ``degrees`` clockwise or counter-clockwise."""

    def start_video_stream(self) -> CommandResult:
        """Ask the aircraft to start its video stream."""

    def stop_video_stream(self) -> CommandResult:
        """Ask the aircraft to stop its video stream."""

    def telemetry(self) -> Telemetry:
        """Latest known telemetry. Unreported values are ``None``."""
