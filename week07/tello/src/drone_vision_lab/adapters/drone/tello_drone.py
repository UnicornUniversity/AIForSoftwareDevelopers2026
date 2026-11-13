"""Standard DJI Tello adapter.

Command socket, state receiver and video receiver stay separate:

* :class:`CommandChannel` owns UDP 8889 (sent), serializes and rate-limits;
* :class:`TelloStateReceiver` owns UDP 8890 (received telemetry);
* :class:`TelloVideoReceiver` (in :mod:`.video_stream`) owns UDP 11111.

Nothing here takes off, starts a video stream or arms anything on its own: every
one of those is an explicit call from the operator's action, after the safety
layer has allowed it.

``SENT`` vs ``CONFIRMED``: an ``ok`` reply only proves the aircraft accepted the
command. Landing is upgraded to ``CONFIRMED`` only when telemetry received
*after* the acknowledgement reports height 0. Emergency Land never upgrades.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable

from ...domain import CommandResult, CommandStatus, Telemetry
from .command_channel import CommandChannel
from .state_receiver import TelloStateReceiver
from .tello_protocol import (
    TelloSettings,
    build_move_command,
    build_rotate_command,
)

__all__ = ["TelloDroneAdapter"]

_log = logging.getLogger(__name__)


class TelloDroneAdapter:
    """The real aircraft, behind the same interface as the simulated drone."""

    def __init__(
        self,
        settings: TelloSettings | None = None,
        *,
        command_channel: CommandChannel | None = None,
        state_receiver: TelloStateReceiver | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings or TelloSettings()
        self._channel = command_channel or CommandChannel(self._settings)
        self._state = state_receiver or TelloStateReceiver(self._settings)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._connected = False
        self._telemetry_warning = ""
        self._video_streaming = False
        # A ``streamoff`` already on the wire must not be submitted a second
        # time by ``disconnect``; the first submission owns the reply.
        self._stream_stop_pending = False

    # -- inspection ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected and self._channel.available

    @property
    def telemetry_warning(self) -> str:
        """Why telemetry is unavailable, or ``""`` when it is listening."""
        with self._lock:
            return self._telemetry_warning

    @property
    def video_streaming(self) -> bool:
        with self._lock:
            return self._video_streaming

    @property
    def telemetry_max_age_s(self) -> float:
        """Age beyond which a state snapshot is stale and gates must refuse it.

        Derived from ``state_timeout_s`` on purpose: a reading older than the
        gap the state receiver already treats as a dead stream must not satisfy
        a flight gate. The simulated aircraft uses the same value
        (:attr:`config.SafetyLimits.telemetry_max_age_s`); keep them in step.
        """
        return self._settings.state_timeout_s

    @property
    def command_channel(self) -> CommandChannel:
        return self._channel

    # -- DroneAdapter --------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> CommandResult:
        """Open the channels and perform the SDK ``command`` handshake.

        Connecting never takes off and never starts the video stream.
        """
        with self._lock:
            if self._connected and self._channel.available:
                # Telemetry is optional and may have failed on the first
                # attempt; retry it here so a later Connect can recover it
                # without tearing down a working command channel.
                warning = ""
                if not self._state.listening:
                    try:
                        self._state.open()
                    except Exception as exc:  # noqa: BLE001 - telemetry stays optional
                        warning = getattr(exc, "user_message", str(exc))
                    self._telemetry_warning = warning
                detail = "Already connected."
                if warning:
                    detail += f" Telemetry is still unavailable: {warning}"
                now = self._clock()
                return CommandResult(
                    "command",
                    CommandStatus.SENT,
                    detail,
                    requested_at=now,
                    completed_at=now,
                )

            try:
                self._channel.open()
            except OSError as exc:
                self._connected = False
                _log.warning(
                    "Connect failed: the command socket could not be opened",
                    extra={"context": {"error": str(exc)}},
                )
                now = self._clock()
                return CommandResult(
                    "command",
                    CommandStatus.FAILED,
                    f"Could not open the command socket: {exc}",
                    requested_at=now,
                    completed_at=now,
                )

            handshake = self._channel.submit("command", timeout=timeout)
            if not handshake.ok:
                self._channel.close()
                self._connected = False
                _log.warning(
                    "Connect failed: the aircraft did not answer the handshake",
                    extra={
                        "context": {
                            "status": handshake.status.value,
                            "detail": handshake.detail,
                        }
                    },
                )
                return CommandResult(
                    "command",
                    handshake.status,
                    self._connect_failure_detail(handshake),
                    requested_at=handshake.requested_at,
                    completed_at=handshake.completed_at,
                )

            self._connected = True
            warning = ""
            try:
                self._state.open()
                warning = ""
            except Exception as exc:  # noqa: BLE001 - telemetry is optional, reported
                warning = getattr(exc, "user_message", str(exc))
            self._telemetry_warning = warning

        detail = "Command channel acknowledged. No takeoff was sent."
        if warning:
            detail += f" Telemetry is unavailable: {warning}"
        now = self._clock()
        _log.info(
            "Connected to the aircraft; no takeoff was sent",
            extra={
                "context": {
                    "host": self._settings.host,
                    "handshake_status": handshake.status.value,
                    "telemetry_warning": warning or None,
                }
            },
        )
        return CommandResult(
            "command",
            CommandStatus.SENT,
            detail,
            requested_at=handshake.requested_at,
            completed_at=now,
        )

    def disconnect(self) -> None:
        """Close every channel. Safe to call when already disconnected.

        If the camera stream is still on, a best-effort ``streamoff`` is sent
        first so the aircraft stops transmitting. It is a camera command, not a
        flight command: closing the application still never lands the aircraft.
        """
        with self._lock:
            channel = self._channel if self.connected else None
            streaming = (
                self._video_streaming
                and not self._stream_stop_pending
                and channel is not None
            )
            self._connected = False
            self._video_streaming = False
            self._stream_stop_pending = False
        if streaming and channel is not None:
            # Bounded and best effort: a missing reply must not stop the
            # sockets below from being released.
            _log.info("Disconnect: sending a best-effort streamoff; no flight command")
            with contextlib.suppress(Exception):
                channel.submit("streamoff", timeout=1.0)
        self._state.stop()
        self._channel.close()
        _log.info("Disconnected from the aircraft")

    def send_command(self, command: str, timeout: float = 5.0) -> CommandResult:
        if not self.connected:
            return self._not_connected(command)
        return self._channel.submit(command, timeout=timeout)

    def takeoff(self, timeout: float = 20.0) -> CommandResult:
        """Explicit takeoff request. Never called automatically."""
        if not self.connected:
            return self._not_connected("takeoff")
        return self._channel.submit("takeoff", timeout=timeout)

    def land(self, timeout: float = 20.0) -> CommandResult:
        """Send ``land`` and look for telemetry evidence of touchdown."""
        if not self.connected:
            return self._not_connected("land")
        result = self._channel.submit("land", timeout=timeout)
        if not result.ok:
            _log.warning(
                "Landing command did not succeed; the aircraft may still be airborne",
                extra={
                    "context": {
                        "status": result.status.value,
                        "detail": result.detail,
                    }
                },
            )
            return result
        sent_at = result.completed_at if result.completed_at is not None else self._clock()
        if self._observed_landing(after=sent_at):
            _log.info("Landing observed in telemetry received after the acknowledgement")
            return CommandResult(
                "land",
                CommandStatus.CONFIRMED,
                "Landing observed in telemetry received after the acknowledgement.",
                requested_at=result.requested_at,
                completed_at=self._clock(),
            )
        _log.warning(
            "Landing acknowledged but touchdown was not observed in telemetry",
            extra={
                "context": {
                    "telemetry_age_s": self._telemetry_age_s(),
                }
            },
        )
        return CommandResult(
            "land",
            CommandStatus.SENT,
            "Landing command acknowledged; touchdown was not independently observed. "
            "Watch the aircraft and confirm visually.",
            requested_at=result.requested_at,
            completed_at=self._clock(),
        )

    def emergency_land(self, timeout: float = 5.0) -> CommandResult:
        """Send the standard ``land`` command ahead of everything queued.

        It never cuts the motors and it is never reported as ``CONFIRMED``: the
        acknowledgement comes from the command channel, not from the aircraft's
        state. When the channel is gone the result says the command could not be
        sent, because this laptop cannot force a landing offline.
        """
        if not self.connected:
            now = self._clock()
            return CommandResult(
                "land",
                CommandStatus.FAILED,
                "No command channel. The landing command could not be sent; the "
                "laptop cannot force a landing without a connection.",
                requested_at=now,
                completed_at=now,
            )
        result = self._channel.submit("land", timeout=timeout, urgent=True)
        if result.ok:
            return CommandResult(
                "land",
                CommandStatus.SENT,
                "Standard land command sent. Motors were not cut. Touchdown is not "
                "confirmed by this result.",
                requested_at=result.requested_at,
                completed_at=result.completed_at,
            )
        if result.status is CommandStatus.TIMEOUT:
            return CommandResult(
                "land",
                CommandStatus.TIMEOUT,
                "The emergency landing command timed out; whether it reached the "
                "aircraft is unknown.",
                requested_at=result.requested_at,
                completed_at=result.completed_at,
            )
        return CommandResult(
            "land",
            CommandStatus.FAILED,
            f"The emergency landing command could not be sent: {result.detail}",
            requested_at=result.requested_at,
            completed_at=result.completed_at,
        )

    def move(
        self,
        direction: str,
        distance_cm: int,
        speed: int | None = None,
        timeout: float = 10.0,
    ) -> CommandResult:
        try:
            move_command = build_move_command(direction, distance_cm)
        except ValueError as exc:
            return self._rejected(f"{direction} {distance_cm}", str(exc))
        if speed is not None and (
            isinstance(speed, bool) or not isinstance(speed, int) or not 10 <= speed <= 100
        ):
            return self._rejected("speed", "speed must be an integer between 10 and 100 cm/s")
        if not self.connected:
            return self._not_connected(move_command)

        # The standard SDK has no per-move speed argument: ``speed x`` sets the
        # aircraft-wide speed and ``<direction> x`` translates. Sending
        # ``forward 50 40`` would be an invalid command, so the speed is a
        # separate, serialized command.
        if speed is not None:
            speed_result = self._channel.submit(f"speed {speed}", timeout=timeout)
            if not speed_result.ok:
                return speed_result
        return self._channel.submit(move_command, timeout=timeout)

    def rotate(self, direction: str, degrees: int, timeout: float = 10.0) -> CommandResult:
        try:
            rotate_command = build_rotate_command(direction, degrees)
        except ValueError as exc:
            return self._rejected(f"{direction} {degrees}", str(exc))
        if not self.connected:
            return self._not_connected(rotate_command)
        return self._channel.submit(rotate_command, timeout=timeout)

    def start_video_stream(self) -> CommandResult:
        if not self.connected:
            return self._not_connected("streamon")
        result = self._channel.submit("streamon", timeout=self._settings.response_timeout_s)
        if result.ok:
            with self._lock:
                self._video_streaming = True
        return result

    def stop_video_stream(self) -> CommandResult:
        if not self.connected:
            with self._lock:
                self._video_streaming = False
            return self._not_connected("streamoff")
        # Mark the stop as in flight so ``disconnect`` does not queue a second
        # ``streamoff`` behind this one and report it as another timeout.
        with self._lock:
            self._stream_stop_pending = True
        try:
            result = self._channel.submit(
                "streamoff", timeout=self._settings.response_timeout_s
            )
        finally:
            with self._lock:
                self._stream_stop_pending = False
                self._video_streaming = False
        return result

    def telemetry(self) -> Telemetry:
        """Latest state the aircraft actually reported; otherwise all ``None``."""
        if not self._state.listening:
            return Telemetry()
        return self._state.latest()

    # -- internals -----------------------------------------------------------

    def _telemetry_age_s(self) -> float | None:
        """Age of the last state report, or ``None`` when none was received."""
        telemetry = self._state.latest() if self._state.listening else Telemetry()
        received_at = telemetry.received_at
        if received_at is None:
            return None
        return round(max(0.0, self._clock() - received_at), 2)

    def _observed_landing(self, *, after: float) -> bool:
        deadline = self._clock() + self._settings.landing_confirm_timeout_s
        while self._clock() < deadline:
            telemetry = self._state.latest() if self._state.listening else Telemetry()
            received_at = telemetry.received_at
            if (
                received_at is not None
                and received_at >= after
                and telemetry.height_cm == 0
            ):
                return True
            self._sleep(0.1)
            if not self.connected:
                return False
        return False

    def _connect_failure_detail(self, result: CommandResult) -> str:
        if result.status is CommandStatus.TIMEOUT:
            return (
                "The aircraft did not answer the command handshake. Check that this "
                "computer is on the TELLO-xxxx Wi-Fi network, that UDP 8889 is allowed "
                "through the firewall, and that no other app owns the connection."
            )
        return result.detail or "The aircraft refused the connection handshake."

    def _not_connected(self, command: str) -> CommandResult:
        now = self._clock()
        return CommandResult(
            command,
            CommandStatus.FAILED,
            "Not connected: no command channel available.",
            requested_at=now,
            completed_at=now,
        )

    def _rejected(self, command: str, detail: str) -> CommandResult:
        now = self._clock()
        return CommandResult(
            command,
            CommandStatus.REJECTED,
            f"Refused locally before transmission: {detail}",
            requested_at=now,
            completed_at=now,
        )
