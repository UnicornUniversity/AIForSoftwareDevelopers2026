"""Simulated drone adapter.

Records every command instead of transmitting anything, which makes it the
default target of the whole application until real hardware support lands.
It is also used by tests to assert command ordering, serialization and
emergency priority.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..domain import CommandResult, CommandStatus, Telemetry

__all__ = ["FakeDroneAdapter", "RecordedCommand"]


@dataclass(frozen=True, slots=True)
class RecordedCommand:
    command: str
    at: float
    status: CommandStatus


class FakeDroneAdapter:
    """In-memory drone. Never opens a socket."""

    def __init__(
        self,
        *,
        reachable: bool = True,
        battery_percent: int | None = 87,
        confirm_landing: bool = False,
        command_delay: float = 0.0,
    ) -> None:
        self._lock = threading.Lock()
        self._connected = False
        self._reachable = reachable
        self._battery_percent = battery_percent
        self._confirm_landing = confirm_landing
        self._command_delay = command_delay
        self._flying = False
        self._log: list[RecordedCommand] = []

    # -- inspection helpers for the UI and tests -----------------------------

    @property
    def command_log(self) -> tuple[RecordedCommand, ...]:
        with self._lock:
            return tuple(self._log)

    @property
    def commands(self) -> tuple[str, ...]:
        return tuple(entry.command for entry in self.command_log)

    @property
    def flying(self) -> bool:
        return self._flying

    def set_reachable(self, reachable: bool) -> None:
        with self._lock:
            self._reachable = reachable
            if not reachable:
                self._connected = False

    def set_battery(self, percent: int | None) -> None:
        with self._lock:
            self._battery_percent = percent

    # -- DroneAdapter --------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, timeout: float = 10.0) -> CommandResult:
        now = time.monotonic()
        with self._lock:
            if not self._reachable:
                return self._record(
                    CommandResult(
                        "connect",
                        CommandStatus.FAILED,
                        "Simulated drone is unreachable",
                        requested_at=now,
                        completed_at=time.monotonic(),
                    )
                )
            self._connected = True
            return self._record(
                CommandResult("connect", CommandStatus.SENT, requested_at=now, completed_at=now)
            )

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def send_command(self, command: str, timeout: float = 5.0) -> CommandResult:
        return self._submit(command)

    def takeoff(self, timeout: float = 20.0) -> CommandResult:
        result = self._submit("takeoff")
        if result.status.acknowledged:
            with self._lock:
                self._flying = True
        return result

    def land(self, timeout: float = 20.0) -> CommandResult:
        result = self._submit("land")
        if result.status.acknowledged:
            with self._lock:
                self._flying = False
            if self._confirm_landing:
                return CommandResult(
                    "land",
                    CommandStatus.CONFIRMED,
                    "Landing observed in simulated telemetry",
                    requested_at=result.requested_at,
                    completed_at=time.monotonic(),
                )
        return result

    def emergency_land(self, timeout: float = 5.0) -> CommandResult:
        # Emergency landing is just the standard land command; it never cuts motors.
        return self.land(timeout=timeout)

    def move(
        self,
        direction: str,
        distance_cm: int,
        speed: int | None = None,
        timeout: float = 10.0,
    ) -> CommandResult:
        speed_part = f" {speed}" if speed is not None else ""
        return self._submit(f"{direction} {distance_cm}{speed_part}")

    def rotate(self, direction: str, degrees: int, timeout: float = 10.0) -> CommandResult:
        return self._submit(f"{direction} {degrees}")

    def start_video_stream(self) -> CommandResult:
        return self._submit("streamon")

    def stop_video_stream(self) -> CommandResult:
        return self._submit("streamoff")

    def telemetry(self) -> Telemetry:
        return Telemetry(battery_percent=self._battery_percent, received_at=time.monotonic())

    # -- internals -----------------------------------------------------------

    def _submit(self, command: str) -> CommandResult:
        if self._command_delay:
            time.sleep(self._command_delay)
        now = time.monotonic()
        with self._lock:
            if not self._connected:
                return self._record(
                    CommandResult(
                        command,
                        CommandStatus.FAILED,
                        "Not connected: no command channel available",
                        requested_at=now,
                        completed_at=now,
                    )
                )
            return self._record(
                CommandResult(command, CommandStatus.SENT, requested_at=now, completed_at=now)
            )

    def _record(self, result: CommandResult) -> CommandResult:
        """Append to the log. Callers hold ``self._lock``."""
        self._log.append(RecordedCommand(result.command, result.requested_at, result.status))
        return result
