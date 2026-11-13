"""Telemetry receiver for the Tello's state packets.

The aircraft sends ``key:value;`` UDP packets to this computer's port 8890 while
it is powered on. A background thread receives them and keeps the latest parsed
snapshot; the UI polls that snapshot, which never blocks.

If the port cannot be bound the receiver raises a typed error. The adapter
treats that as "telemetry unavailable" rather than hiding it: a second Tello
tool may already own the port, and the UI must then show *not reported* rather
than a stale or guessed battery value.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from collections.abc import Callable

from ...domain import Telemetry
from ...errors import HardwareUnavailableError
from .command_channel import SocketFactory, UdpSocket
from .tello_protocol import TelloSettings, parse_state_packet

__all__ = ["TelloStateReceiver"]

_log = logging.getLogger(__name__)

_GAP_GRACE_MIN_S = 2.0
"""Minimum silence before a missing state stream is reported.

The aircraft reports state about ten times per second. A quiet receiver for a
couple of seconds is the first observable sign of a lost Wi-Fi link, and it is
recorded before any command timeout can be.
"""


class TelloStateReceiver:
    """Receives state packets on ``local_state_port`` and caches the latest."""

    def __init__(
        self,
        settings: TelloSettings | None = None,
        *,
        socket_factory: SocketFactory = socket.socket,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or TelloSettings()
        self._socket_factory = socket_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._socket: UdpSocket | None = None
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()
        self._latest = Telemetry()
        self._last_received_at: float | None = None
        self._packets_received = 0
        self._foreign_packets = 0
        self._parse_failures = 0
        self._opened_at: float | None = None
        self._gap_logged = False
        self._first_packet_logged = False
        self._parse_failure_logged = False

    # -- inspection ----------------------------------------------------------

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._socket is not None and not self._closing.is_set()

    @property
    def last_received_at(self) -> float | None:
        with self._lock:
            return self._last_received_at

    @property
    def last_packet_at(self) -> float | None:
        """When the last valid state packet arrived, for link-health reporting."""
        with self._lock:
            return self._last_received_at

    @property
    def state_gap_after_s(self) -> float:
        """Silence after which a missing state stream is reported in the log."""
        return max(_GAP_GRACE_MIN_S, self._settings.state_timeout_s * 3.0)

    @property
    def packets_received(self) -> int:
        with self._lock:
            return self._packets_received

    @property
    def parse_failures(self) -> int:
        with self._lock:
            return self._parse_failures

    @property
    def foreign_packets(self) -> int:
        """Datagrams dropped because they did not come from the configured host."""
        with self._lock:
            return self._foreign_packets

    def latest(self) -> Telemetry:
        """Latest reported telemetry; every field is ``None`` until reported."""
        with self._lock:
            return self._latest

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._socket is not None:
                return
            self._closing.clear()
            sock = None
            try:
                sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(0.25)
                sock.bind(("", self._settings.local_state_port))
            except OSError as exc:
                if sock is not None:
                    with contextlib.suppress(OSError):
                        sock.close()
                raise HardwareUnavailableError(
                    f"Could not listen for Tello state on UDP "
                    f"{self._settings.local_state_port}: {exc}",
                    user_message=(
                        f"Telemetry is unavailable: UDP port "
                        f"{self._settings.local_state_port} could not be opened "
                        f"({exc}). Close other Tello tools (for example the DJI "
                        "app or another SDK script) and check the firewall."
                    ),
                ) from exc
            self._socket = sock
            self._opened_at = self._clock()
            self._gap_logged = False
            self._first_packet_logged = False
            self._parse_failure_logged = False
            self._thread = threading.Thread(
                target=self._run, name="tello-state-receiver", daemon=True
            )
            self._thread.start()
            _log.info(
                "State receiver listening",
                extra={
                    "context": {
                        "local_port": self._settings.local_state_port,
                        "expected_host": self._settings.host,
                        "gap_warning_after_s": self.state_gap_after_s,
                    }
                },
            )

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            thread = self._thread
            sock = self._socket
            self._thread = None
            self._socket = None
            self._closing.set()
            packets = self._packets_received
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        _log.info(
            "State receiver stopped",
            extra={"context": {"packets_received": packets}},
        )

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        socket_error_logged = False
        while not self._closing.is_set():
            with self._lock:
                sock = self._socket
            if sock is None:
                return
            try:
                payload, sender = sock.recvfrom(4096)
            except TimeoutError:
                self._check_state_gap()
                continue
            except OSError as exc:
                if self._closing.is_set():
                    return
                if not socket_error_logged:
                    socket_error_logged = True
                    _log.warning(
                        "State receiver socket error",
                        extra={"context": {"error": str(exc)}},
                    )
                continue
            socket_error_logged = False
            if sender[0] != self._settings.host:
                # Only the configured aircraft may set the telemetry the safety
                # gates read; another host's packet is not evidence about this
                # aircraft, even if it parses as a state packet.
                with self._lock:
                    self._foreign_packets += 1
                _log.debug(
                    "Ignored a state packet from another host",
                    extra={"context": {"sender": sender[0]}},
                )
                continue
            received_at = self._clock()
            telemetry = parse_state_packet(payload, received_at=received_at)
            with self._lock:
                self._packets_received += 1
                gap_logged = self._gap_logged
                previous = self._last_received_at
                first = not self._first_packet_logged
                self._gap_logged = False
                if telemetry is None:
                    # A malformed packet is not a valid report, so the link
                    # warning stays open until a readable packet arrives.
                    self._gap_logged = gap_logged
                    self._parse_failures += 1
                    log_parse_failure = not self._parse_failure_logged
                    self._parse_failure_logged = True
                else:
                    self._latest = telemetry
                    self._last_received_at = received_at
                    self._first_packet_logged = True
                    log_parse_failure = False

            if telemetry is None:
                if log_parse_failure:
                    _log.warning(
                        "A state packet could not be parsed and was ignored",
                        extra={
                            "context": {
                                "payload_prefix": payload[:64].decode(
                                    "ascii", errors="replace"
                                )
                            }
                        },
                    )
                continue
            if gap_logged:
                silent_for = (
                    None if previous is None else round(received_at - previous, 2)
                )
                _log.info(
                    "State packets resumed",
                    extra={
                        "context": {
                            "silent_for_s": silent_for,
                            "battery_percent": telemetry.battery_percent,
                            "height_cm": telemetry.height_cm,
                        }
                    },
                )
            elif first:
                _log.info(
                    "First state packet received",
                    extra={
                        "context": {
                            "battery_percent": telemetry.battery_percent,
                            "height_cm": telemetry.height_cm,
                        }
                    },
                )

    def _check_state_gap(self) -> None:
        """Log once when the state stream goes quiet, before any command timeout."""
        now = self._clock()
        with self._lock:
            if self._gap_logged:
                return
            opened_at = self._opened_at
            last = self._last_received_at
            packets = self._packets_received
        threshold = self.state_gap_after_s
        # After a reconnect, silence before the new session started is not
        # evidence about the new link.
        reference = opened_at if last is None else max(opened_at or 0.0, last)
        if reference is None or now - reference < threshold:
            return
        with self._lock:
            if self._gap_logged:
                return
            self._gap_logged = True
        if last is None:
            _log.warning(
                "No state packet received since the receiver opened",
                extra={
                    "context": {
                        "waited_s": round(now - (opened_at or now), 2),
                        "local_port": self._settings.local_state_port,
                        "expected_host": self._settings.host,
                    }
                },
            )
        else:
            _log.warning(
                "State packets stopped arriving",
                extra={
                    "context": {
                        "silent_for_s": round(now - last, 2),
                        "packets_received": packets,
                        "local_port": self._settings.local_state_port,
                    }
                },
            )
