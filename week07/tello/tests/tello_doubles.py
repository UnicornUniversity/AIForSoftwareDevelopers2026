"""Scripted doubles for the standard-Tello hardware tests.

Everything here runs in-process: no socket, no aircraft, no PyAV. The command
channel, state receiver and video receiver accept these doubles through their
normal injection points, so the production paths stay under test.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any

import numpy as np

from drone_vision_lab.domain import CommandResult, CommandStatus, Telemetry


def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    """Poll a background receiver without assuming a fixed delay."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeUdpSocket:
    """A UDP socket stand-in with scripted replies and recorded sends."""

    def __init__(
        self,
        replies: Iterable[bytes | str] = (),
        *,
        send_error: OSError | None = None,
        recv_error: OSError | None = None,
        bind_error: OSError | None = None,
        connect_error: OSError | None = None,
        local_address: str = "192.168.10.2",
        sender: tuple[str, int] = ("192.168.10.1", 8889),
        reply_factory: Callable[[str], bytes | str | None] | None = None,
    ) -> None:
        self._replies: deque[bytes] = deque(
            reply.encode("ascii") if isinstance(reply, str) else reply for reply in replies
        )
        self._unsolicited: deque[bytes] = deque()
        self._reply_factory = reply_factory
        self.deliver_replies_before_send = True
        """Whether ``recvfrom`` may hand out a scripted reply before any send.

        True models a receiver that only listens (state and video). The command
        channel sets it False, because a real reply cannot arrive before the
        command it answers is transmitted.
        """
        self._send_error = send_error
        self._recv_error = recv_error
        self._bind_error = bind_error
        self._connect_error = connect_error
        self._local_address = local_address
        self.sender = sender
        self._closed = False
        self.sent: list[tuple[str, tuple[str, int]]] = []
        self.bound: tuple[str, int] | None = None
        self.connected_to: tuple[str, int] | None = None
        self.timeout: float | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    # -- UdpSocket -----------------------------------------------------------

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def bind(self, address: tuple[str, int]) -> None:
        if self._bind_error is not None:
            raise self._bind_error
        self.bound = address

    def connect(self, address: tuple[str, int]) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.connected_to = address

    def getsockname(self) -> tuple[str, int]:
        return self._local_address, 50000

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        if self._send_error is not None:
            raise self._send_error
        command = data.decode("ascii")
        self.sent.append((command, address))
        if self._reply_factory is not None:
            reply = self._reply_factory(command)
            if reply is not None:
                self._replies.append(
                    reply.encode("ascii") if isinstance(reply, str) else reply
                )
        return len(data)

    def push_unsolicited(self, payload: bytes | str) -> None:
        """Queue a datagram that is present before the next command is sent.

        This models a stale reply — for example a late answer to a command that
        already timed out — rather than the reply to the command being sent.
        """
        self._unsolicited.append(
            payload.encode("ascii") if isinstance(payload, str) else payload
        )

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        if self._closed:
            raise OSError("socket closed")
        if self._recv_error is not None:
            raise self._recv_error
        if self._unsolicited:
            return self._unsolicited.popleft(), self.sender
        if self._replies and (self.deliver_replies_before_send or self.sent):
            return self._replies.popleft(), self.sender
        # Avoid a hot spin: behave like a socket that timed out.
        time.sleep(min(0.01, self.timeout if self.timeout is not None else 0.01))
        raise TimeoutError("timed out")

    def close(self) -> None:
        self._closed = True


class SocketFactory:
    """A socket factory that records every socket it created."""

    def __init__(self, sockets: Iterable[FakeUdpSocket]) -> None:
        self._pending = list(sockets)
        self.created: list[FakeUdpSocket] = []

    def __call__(self, *_args: object) -> FakeUdpSocket:
        socket = FakeUdpSocket() if not self._pending else self._pending.pop(0)
        self.created.append(socket)
        return socket


class FakeClock:
    """A monotonic clock the test advances explicitly."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class StubStateReceiver:
    """State receiver substitute with directly settable telemetry."""

    def __init__(self, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or Telemetry()
        self.opened = 0
        self.stopped = 0
        self._listening = False
        self.open_error: Exception | None = None

    @property
    def listening(self) -> bool:
        return self._listening

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1
        self._listening = True

    def stop(self) -> None:
        self.stopped += 1
        self._listening = False

    def latest(self) -> Telemetry:
        return self.telemetry


class StubCommandChannel:
    """Command channel substitute that records submissions.

    By default every command is acknowledged. A ``handler`` can return a
    scripted :class:`CommandResult` for a specific command (for example a
    timeout) while leaving the rest acknowledged.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        handler: Callable[[str], CommandResult | None] | None = None,
        open_error: OSError | None = None,
    ) -> None:
        self.calls: list[tuple[str, float | None, bool]] = []
        self.opened = 0
        self.closed = 0
        self._clock = clock
        self._handler = handler
        self._open_error = open_error
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    @property
    def sent_count(self) -> int:
        return len(self.calls)

    @property
    def last_error(self) -> str:
        return ""

    def open(self) -> None:
        if self._open_error is not None:
            raise self._open_error
        self.opened += 1
        self._available = True

    def close(self, timeout: float = 2.0) -> None:
        self.closed += 1
        self._available = False

    def submit(
        self,
        command: str,
        *,
        timeout: float | None = None,
        urgent: bool = False,
    ) -> CommandResult:
        self.calls.append((command, timeout, urgent))
        if self._handler is not None:
            result = self._handler(command)
            if result is not None:
                return result
        now = self._clock()
        return CommandResult(
            command,
            CommandStatus.SENT,
            "Acknowledged with ok.",
            requested_at=now,
            completed_at=now,
        )


class StubVideoReceiver:
    """Video receiver substitute that returns one image at a time."""

    def __init__(self, image: np.ndarray | None = None) -> None:
        self.image = image if image is not None else np.zeros((48, 64, 3), dtype=np.uint8)
        self.last_packet_at: float | None = None
        self.open_error: Exception | None = None
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1

    def close(self) -> None:
        self.closed += 1

    def read_frame(self) -> np.ndarray | None:
        return self.image


class FakeAvFrame:
    def __init__(self, image: np.ndarray) -> None:
        self._image = image

    def to_ndarray(self, format: str) -> np.ndarray:
        assert format == "bgr24"
        return self._image


class FakeH264Codec:
    """Returns one frame per packet, or fails on demand."""

    def __init__(self, image: np.ndarray | None = None, *, fail: bool = False) -> None:
        self._image = image if image is not None else np.zeros((48, 64, 3), dtype=np.uint8)
        self._fail = fail
        self.packets: list[bytes] = []

    def parse(self, payload: bytes) -> list[bytes]:
        self.packets.append(payload)
        return [payload]

    def decode(self, _packet: bytes) -> list[FakeAvFrame]:
        if self._fail:
            raise ValueError("cannot decode this packet")
        return [FakeAvFrame(self._image)]


def make_fake_av(
    image: np.ndarray | None = None,
    *,
    fail: bool = False,
) -> tuple[Any, FakeH264Codec]:
    """A minimal stand-in for the ``av`` module."""
    codec = FakeH264Codec(image, fail=fail)

    class CodecContext:
        @staticmethod
        def create(name: str, mode: str) -> FakeH264Codec:
            assert (name, mode) == ("h264", "r")
            return codec

    return SimpleNamespace(CodecContext=CodecContext, error=SimpleNamespace()), codec
