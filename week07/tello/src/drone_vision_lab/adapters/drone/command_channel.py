"""Serialized, rate-limited UDP command channel for a standard Tello.

One worker thread owns the socket. Every caller — the UI, a mission runner or a
future tracking controller — submits a request and waits for its result, so two
threads can never write to the aircraft at the same time.

Two limits are deliberate:

* **Serialization.** Tello expects one command at a time; the SDK answers
  ``ok``/``error`` per command. Requests are queued, never interleaved.
* **Rate limiting.** Commands are spaced by ``min_command_interval_s``. A
  backlog of stick-like commands must not become a UDP flood.

An *urgent* submission (Emergency Land) is placed ahead of everything still
queued, and the queued requests are rejected with ``REJECTED`` — nothing is
transmitted for them. It cannot interrupt a command already on the wire,
because the aircraft replies to that command; the code says so rather than
pretending otherwise.

The SDK gives replies no request id: a reply is correlated with a command only
by arrival order. A datagram already queued before a command was transmitted
therefore cannot answer that command, and using it would report ``ok`` for a
command the aircraft has not answered yet. Such leftovers — usually a late
reply to a command that timed out — are discarded and logged before each send.


The socket is injected, so the whole channel is tested against a scripted fake
with no network.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ...domain import CommandResult, CommandStatus
from .tello_protocol import TelloSettings, is_acknowledgement, is_error_reply, normalize_command

__all__ = ["CommandChannel", "UdpSocket"]

_log = logging.getLogger(__name__)

_MAX_STALE_DATAGRAMS = 16
"""Bound on datagrams drained before a send; a stuck peer must not stall us."""

_DRAIN_TIMEOUT_S = 0.0
"""Non-blocking read while draining leftover replies."""


class UdpSocket(Protocol):
    """The subset of ``socket.socket`` the drone adapters use.

    Fakes implement these methods with scripted replies; nothing here is ever
    handed to a real network in the unit tests.
    """

    def settimeout(self, value: float | None) -> None: ...

    def bind(self, address: tuple[str, int]) -> None: ...

    def connect(self, address: tuple[str, int]) -> None: ...

    def getsockname(self) -> tuple[str, int]: ...

    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]: ...

    def close(self) -> None: ...


SocketFactory = Callable[..., UdpSocket]


@dataclass
class _Request:
    command: str
    timeout: float
    urgent: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    result: CommandResult | None = None


class CommandChannel:
    """A single-threaded command queue around one UDP socket."""

    def __init__(
        self,
        settings: TelloSettings | None = None,
        *,
        socket_factory: SocketFactory = socket.socket,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings or TelloSettings()
        self._socket_factory = socket_factory
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closing = threading.Event()
        self._socket: UdpSocket | None = None
        self._thread: threading.Thread | None = None
        self._queue: deque[_Request] = deque()
        self._urgent: deque[_Request] = deque()
        self._last_sent_at: float | None = None
        self._sent_count = 0
        self._last_error = ""

    # -- lifecycle -----------------------------------------------------------

    @property
    def available(self) -> bool:
        with self._lock:
            return self._socket is not None and not self._closing.is_set()

    @property
    def sent_count(self) -> int:
        with self._lock:
            return self._sent_count

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def open(self) -> None:
        """Bind an ephemeral UDP socket and start the worker.

        An ephemeral local port is correct: the Tello replies to the address
        the command came from. Binding a fixed local port is not required and
        would collide with another Tello tool.
        """
        with self._lock:
            if self._socket is not None and not self._closing.is_set():
                return
        if self._socket is not None:
            # A previous connection failed; tear it down before rebuilding.
            self.close()
        with self._lock:
            if self._socket is not None:  # opened concurrently
                return
            self._closing.clear()
            self._wake.clear()
            self._queue.clear()
            self._urgent.clear()
            self._last_sent_at = None
            try:
                sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            except OSError as exc:
                self._last_error = f"Could not create the command socket: {exc}"
                raise
            with contextlib.suppress(OSError):
                sock.settimeout(0.25)
            self._socket = sock
            self._thread = threading.Thread(
                target=self._run, name="tello-command-channel", daemon=True
            )
            self._thread.start()
            _log.info(
                "Command channel opened",
                extra={
                    "context": {
                        "host": self._settings.host,
                        "port": self._settings.command_port,
                        "response_timeout_s": self._settings.response_timeout_s,
                    }
                },
            )

    def close(self, timeout: float = 2.0) -> None:
        """Stop the worker, reject everything still queued and close the socket."""
        with self._lock:
            thread = self._thread
            sock = self._socket
            self._thread = None
            self._socket = None
            self._closing.set()
            self._wake.set()
            self._reject_queued("The command channel was closed; nothing was transmitted.")
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        _log.info(
            "Command channel closed",
            extra={"context": {"commands_sent": self.sent_count}},
        )

    # -- submission ----------------------------------------------------------

    def submit(
        self,
        command: str,
        *,
        timeout: float | None = None,
        urgent: bool = False,
    ) -> CommandResult:
        """Queue one command and wait for its result.

        Blocks for at most the command timeout, which is why the UI calls it
        from a worker thread.
        """
        try:
            cleaned = normalize_command(command)
        except ValueError as exc:
            result = self._local_result(
                command or "<empty>", CommandStatus.REJECTED, str(exc)
            )
            _log.warning(
                "Command refused before transmission",
                extra={
                    "context": {
                        "command": result.command,
                        "status": result.status.value,
                        "detail": result.detail,
                    }
                },
            )
            return result

        request = _Request(
            command=cleaned,
            timeout=self._settings.response_timeout_s if timeout is None else timeout,
            urgent=urgent,
        )
        if request.timeout <= 0:
            result = self._local_result(
                cleaned,
                CommandStatus.REJECTED,
                "The command timeout must be positive.",
            )
            _log.warning(
                "Command refused before transmission",
                extra={"context": {"command": cleaned, "status": result.status.value}},
            )
            return result

        with self._lock:
            if not self.available:
                result = self._local_result(
                    cleaned,
                    CommandStatus.FAILED,
                    "Not connected: no command channel available.",
                )
                _log.warning(
                    "Command not sent: the command channel is not available",
                    extra={
                        "context": {
                            "command": cleaned,
                            "status": result.status.value,
                        }
                    },
                )
                return result
            if urgent:
                _log.warning(
                    "Emergency command preempts queued commands",
                    extra={
                        "context": {
                            "command": cleaned,
                            "queued": len(self._queue) + len(self._urgent),
                        }
                    },
                )
                self._reject_queued(
                    "Preempted by an emergency command; nothing was transmitted."
                )
                self._urgent.append(request)
            else:
                self._queue.append(request)
        self._wake.set()

        finished = request.done.wait(request.timeout + 1.0)
        if not finished or request.result is None:
            result = self._local_result(
                cleaned,
                CommandStatus.TIMEOUT,
                "The command worker did not answer in time; the outcome is unknown.",
            )
            _log.warning(
                "Command worker did not answer",
                extra={
                    "context": {
                        "command": cleaned,
                        "timeout_s": request.timeout,
                        "status": result.status.value,
                    }
                },
            )
            return result
        return request.result

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        while True:
            request = self._take_request()
            if request is None:
                return
            if request.done.is_set():  # rejected while waiting to be sent
                continue
            self._respect_rate_limit()
            result = self._transmit(request)
            request.result = result
            request.done.set()
            if result.status is CommandStatus.FAILED and not self.available:
                with self._lock:
                    self._reject_queued(
                        "The command channel was lost; the command was not transmitted."
                    )

    def _take_request(self) -> _Request | None:
        while True:
            with self._lock:
                if self._closing.is_set():
                    return None
                if self._urgent:
                    return self._urgent.popleft()
                if self._queue:
                    return self._queue.popleft()
                if self._socket is None:
                    return None
            self._wake.wait(0.25)
            self._wake.clear()

    def _respect_rate_limit(self) -> None:
        interval = self._settings.min_command_interval_s
        if interval <= 0:
            return
        with self._lock:
            last = self._last_sent_at
        if last is None:
            return
        remaining = interval - (self._clock() - last)
        if remaining > 0:
            self._sleep(remaining)

    def _transmit(self, request: _Request) -> CommandResult:
        with self._lock:
            sock = self._socket
        if sock is None:
            return self._outcome(
                request,
                CommandStatus.FAILED,
                "The command channel was closed before the command was sent.",
                requested_at=self._clock(),
            )

        # No datagram can answer this command before it is on the wire. Drop
        # anything already queued so a late reply to an earlier command is not
        # reported as this command's acknowledgement.
        self._discard_stale_replies(sock, request.command)

        requested_at = self._clock()
        address = (self._settings.host, self._settings.command_port)
        try:
            sock.sendto(request.command.encode("ascii"), address)
        except (UnicodeEncodeError, OSError) as exc:
            self._mark_unavailable(str(exc))
            return self._outcome(
                request,
                CommandStatus.FAILED,
                f"The command could not be sent: {exc}",
                requested_at=requested_at,
            )

        with self._lock:
            self._last_sent_at = self._clock()
            self._sent_count += 1
        _log.info(
            "Command transmitted",
            extra={
                "context": {
                    "command": request.command,
                    "host": self._settings.host,
                    "port": self._settings.command_port,
                    "timeout_s": request.timeout,
                }
            },
        )

        deadline = self._clock() + request.timeout
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._outcome(
                    request,
                    CommandStatus.TIMEOUT,
                    "No reply within the timeout; the outcome is unknown.",
                    requested_at=requested_at,
                )
            try:
                sock.settimeout(min(0.25, remaining))
                payload, sender = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError as exc:
                if self._closing.is_set():
                    return self._outcome(
                        request,
                        CommandStatus.FAILED,
                        "The command channel was closed before a reply arrived.",
                        requested_at=requested_at,
                    )
                self._mark_unavailable(str(exc))
                return self._outcome(
                    request,
                    CommandStatus.FAILED,
                    f"The command channel failed while waiting for a reply: {exc}",
                    requested_at=requested_at,
                )
            except UnicodeDecodeError:  # pragma: no cover - guarded by decode below
                continue

            if sender[0] != self._settings.host:
                # A datagram from another host must never be read as this
                # aircraft's acknowledgement. Keep waiting for the real reply.
                _log.debug(
                    "Ignored a reply datagram from another host",
                    extra={"context": {"sender": sender[0]}},
                )
                continue

            reply = payload.decode("ascii", errors="ignore").strip()
            if is_acknowledgement(reply):
                return self._outcome(
                    request,
                    CommandStatus.SENT,
                    "Acknowledged with ok; the state change is not independently confirmed.",
                    requested_at=requested_at,
                )
            if is_error_reply(reply):
                return self._outcome(
                    request,
                    CommandStatus.FAILED,
                    f"The aircraft refused the command ({reply}).",
                    requested_at=requested_at,
                )
            # Anything else (stray packets, keep-alives) is not a reply to this
            # command; keep waiting until the deadline.

    # -- internals -----------------------------------------------------------

    def _discard_stale_replies(self, sock: UdpSocket, command: str) -> None:
        """Drop datagrams that arrived before ``command`` was transmitted.

        The Tello SDK has no request ids, so a reply is correlated with a
        command only by arrival order. A datagram queued before the send cannot
        be its reply, and reading it would report ``SENT`` for a command the
        aircraft has not answered yet. This is logged because it is abnormal:
        the usual source is a late reply to a command that timed out, and it
        means the reply for one of the commands was not read in time.
        """
        discarded: list[str] = []
        sock.settimeout(_DRAIN_TIMEOUT_S)
        while len(discarded) < _MAX_STALE_DATAGRAMS:
            try:
                payload, sender = sock.recvfrom(2048)
            except (TimeoutError, BlockingIOError):
                break
            except OSError:
                # A socket error is diagnosed by the send and wait path; it is
                # not a stale reply.
                break
            text = payload.decode("ascii", errors="ignore").strip()
            discarded.append(f"{sender[0]}: {text[:64]!r}")
        if discarded:
            _log.warning(
                "Discarded datagrams that arrived before the command was transmitted; "
                "they cannot answer it",
                extra={
                    "context": {
                        "command": command,
                        "count": len(discarded),
                        "datagrams": discarded,
                    }
                },
            )

    def _outcome(
        self,
        request: _Request,
        status: CommandStatus,
        detail: str,
        *,
        requested_at: float,
    ) -> CommandResult:
        """Build the result and log it, so every command has a log timeline."""
        completed_at = self._clock()
        result = CommandResult(
            request.command,
            status,
            detail,
            requested_at=requested_at,
            completed_at=completed_at,
        )
        _log.log(
            logging.INFO if status.acknowledged else logging.WARNING,
            "Command outcome",
            extra={
                "context": {
                    "command": request.command,
                    "status": status.value,
                    "elapsed_s": round(max(0.0, completed_at - requested_at), 3),
                    "detail": detail,
                }
            },
        )
        return result

    def _mark_unavailable(self, reason: str) -> None:
        with self._lock:
            self._last_error = reason
            self._closing.set()
            self._wake.set()
            self._reject_queued(
                "The command channel was lost; the command was not transmitted."
            )
        _log.warning(
            "Command channel marked unavailable",
            extra={"context": {"reason": reason}},
        )

    def _reject_queued(self, reason: str) -> None:
        """Reject queued requests. Caller holds ``self._lock``."""
        pending = list(self._urgent) + list(self._queue)
        self._urgent.clear()
        self._queue.clear()
        if pending:
            _log.warning(
                "Queued commands rejected",
                extra={"context": {"count": len(pending), "reason": reason}},
            )
        for request in pending:
            if request.done.is_set():
                continue
            request.result = self._local_result(request.command, CommandStatus.REJECTED, reason)
            request.done.set()

    def _local_result(
        self,
        command: str,
        status: CommandStatus,
        detail: str,
    ) -> CommandResult:
        now = self._clock()
        return CommandResult(command, status, detail, requested_at=now, completed_at=now)
