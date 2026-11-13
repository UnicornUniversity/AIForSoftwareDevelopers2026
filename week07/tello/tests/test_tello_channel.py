"""Serialized, rate-limited command channel against a scripted UDP socket."""

from __future__ import annotations

import logging
import threading
import time

import pytest
from tello_doubles import FakeClock, FakeUdpSocket, SocketFactory

from drone_vision_lab.adapters.drone.command_channel import CommandChannel
from drone_vision_lab.adapters.drone.tello_protocol import TelloSettings
from drone_vision_lab.domain import CommandStatus

ADDRESS = ("192.168.10.1", 8889)


def make_settings(**overrides) -> TelloSettings:
    values = {"response_timeout_s": 0.5, "min_command_interval_s": 0.0}
    values.update(overrides)
    return TelloSettings(**values)


def open_channel(
    sock: FakeUdpSocket,
    *,
    settings: TelloSettings | None = None,
    clock=None,
    sleep=None,
) -> CommandChannel:
    # A real reply cannot be waiting before the command is transmitted, so the
    # scripted replies stand for answers that arrive after `sendto`.
    sock.deliver_replies_before_send = False
    channel = CommandChannel(
        settings or make_settings(),
        socket_factory=SocketFactory([sock]),
        clock=clock or time.monotonic,
        sleep=sleep or time.sleep,
    )
    channel.open()
    return channel


def test_an_acknowledged_command_is_reported_sent_not_confirmed():
    sock = FakeUdpSocket(["ok"])
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.5)
    finally:
        channel.close()

    assert result.status is CommandStatus.SENT
    assert result.status is not CommandStatus.CONFIRMED
    assert sock.sent == [("takeoff", ADDRESS)]
    assert "not independently confirmed" in result.detail


def test_an_error_reply_is_a_failure():
    sock = FakeUdpSocket(["error Not joystick"])
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.5)
    finally:
        channel.close()

    assert result.status is CommandStatus.FAILED
    assert "refused" in result.detail.lower()


def test_no_reply_times_out_and_says_the_outcome_is_unknown():
    sock = FakeUdpSocket([])
    channel = open_channel(sock)
    try:
        result = channel.submit("land", timeout=0.05)
    finally:
        channel.close()

    assert result.status is CommandStatus.TIMEOUT
    assert "unknown" in result.detail


def test_a_reply_from_another_host_is_not_treated_as_the_acknowledgement():
    sock = FakeUdpSocket(["ok"], sender=("192.168.10.99", 8889))
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.05)
    finally:
        channel.close()

    assert result.status is CommandStatus.TIMEOUT
    assert "unknown" in result.detail


def test_unrelated_packets_are_ignored_until_the_reply_arrives():
    sock = FakeUdpSocket(["keepalive", "hello", "ok"])
    channel = open_channel(sock)
    try:
        result = channel.submit("forward 20", timeout=0.5)
    finally:
        channel.close()

    assert result.status is CommandStatus.SENT


def test_a_datagram_queued_before_the_command_is_not_its_acknowledgement(caplog):
    """A late reply to an earlier command must never mask this command's outcome.

    The Tello SDK replies carry no request id. When an old ``ok`` is already in
    the receive buffer, reading it would report ``SENT`` for a command the
    aircraft has not answered yet — the failure this drain exists to prevent.
    """
    caplog.set_level(
        logging.WARNING, logger="drone_vision_lab.adapters.drone.command_channel"
    )
    sock = FakeUdpSocket([])
    sock.push_unsolicited("ok")
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.05)
    finally:
        channel.close()

    assert result.status is CommandStatus.TIMEOUT
    discarded = [
        record
        for record in caplog.records
        if record.getMessage().startswith("Discarded datagrams")
    ]
    assert len(discarded) == 1
    assert discarded[0].context["count"] == 1
    assert discarded[0].context["command"] == "takeoff"


def test_a_stale_ok_does_not_hide_the_aircrafts_refusal():
    sock = FakeUdpSocket([], reply_factory=lambda _command: "error Not joystick")
    sock.push_unsolicited("ok")
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.5)
    finally:
        channel.close()

    assert result.status is CommandStatus.FAILED
    assert "refused" in result.detail.lower()


def test_a_command_is_refused_before_the_channel_is_open():
    channel = CommandChannel(make_settings(), socket_factory=SocketFactory([]))

    result = channel.submit("takeoff", timeout=0.1)

    assert result.status is CommandStatus.FAILED
    assert "Not connected" in result.detail


def test_an_injected_line_break_never_reaches_the_socket():
    sock = FakeUdpSocket([])
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff\nland", timeout=0.1)
    finally:
        channel.close()

    assert result.status is CommandStatus.REJECTED
    assert sock.sent == []


def test_commands_are_rate_limited():
    clock = FakeClock()
    # Generate each reply when its command is sent: a real reply cannot be
    # waiting before the send, and the drain would rightly discard one.
    sock = FakeUdpSocket([], reply_factory=lambda _command: "ok")
    settings = make_settings(min_command_interval_s=0.1)
    channel = open_channel(sock, settings=settings, clock=clock, sleep=clock.sleep)
    try:
        first = channel.submit("takeoff", timeout=1.0)
        second = channel.submit("land", timeout=1.0)
    finally:
        channel.close()

    assert first.status is CommandStatus.SENT
    assert second.status is CommandStatus.SENT
    assert clock.sleeps == [pytest.approx(0.1)]


def test_an_emergency_command_preempts_queued_commands():
    sock = FakeUdpSocket(
        [],
        reply_factory=lambda command: "ok" if command == "land" else None,
    )
    channel = open_channel(sock, settings=make_settings(response_timeout_s=0.3))
    results: dict[str, object] = {}
    threads: list[threading.Thread] = []

    def submit(
        name: str,
        command: str,
        timeout: float,
        *,
        urgent: bool = False,
    ) -> None:
        thread = threading.Thread(
            target=lambda: results.update(
                {name: channel.submit(command, timeout=timeout, urgent=urgent)}
            ),
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    try:
        submit("first", "forward 50", 0.3)
        time.sleep(0.06)
        submit("queued", "cw 90", 0.3)
        time.sleep(0.06)
        submit("emergency", "land", 0.3, urgent=True)
        for thread in threads:
            thread.join(2.0)
    finally:
        channel.close()

    assert results["first"].status is CommandStatus.TIMEOUT
    assert results["queued"].status is CommandStatus.REJECTED
    assert "emergency" in results["queued"].detail.lower()
    assert results["emergency"].status is CommandStatus.SENT
    assert [command for command, _address in sock.sent] == ["forward 50", "land"]


def test_closing_the_channel_rejects_what_is_still_queued():
    sock = FakeUdpSocket([], reply_factory=lambda _command: None)
    channel = open_channel(sock, settings=make_settings(response_timeout_s=0.3))
    results: dict[str, object] = {}
    threads: list[threading.Thread] = []

    def submit(name: str, command: str) -> None:
        thread = threading.Thread(
            target=lambda: results.update({name: channel.submit(command, timeout=0.3)}),
            daemon=True,
        )
        threads.append(thread)
        thread.start()

    submit("in_flight", "forward 20")
    time.sleep(0.06)
    submit("queued", "back 20")
    time.sleep(0.06)
    channel.close()
    for thread in threads:
        thread.join(2.0)

    assert results["in_flight"].status is CommandStatus.FAILED
    assert results["queued"].status is CommandStatus.REJECTED


def test_a_socket_failure_marks_the_channel_unavailable():
    sock = FakeUdpSocket([], send_error=OSError("network unreachable"))
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.1)
        available_after = channel.available
    finally:
        channel.close()

    assert result.status is CommandStatus.FAILED
    assert "could not be sent" in result.detail
    assert available_after is False


def test_a_lost_socket_while_waiting_is_a_failure():
    sock = FakeUdpSocket([], recv_error=ConnectionResetError("connection reset"))
    channel = open_channel(sock)
    try:
        result = channel.submit("takeoff", timeout=0.2)
    finally:
        channel.close()

    assert result.status is CommandStatus.FAILED
    assert "channel failed" in result.detail.lower()


# -- logging -----------------------------------------------------------------


def test_every_command_leaves_a_timeline_in_the_log(caplog):
    caplog.set_level(
        logging.INFO, logger="drone_vision_lab.adapters.drone.command_channel"
    )
    sock = FakeUdpSocket(["ok"])
    channel = open_channel(sock)
    try:
        channel.submit("takeoff", timeout=0.5)
    finally:
        channel.close()

    messages = [record.getMessage() for record in caplog.records]
    assert "Command channel opened" in messages
    assert "Command transmitted" in messages
    assert "Command outcome" in messages
    assert "Command channel closed" in messages

    outcome = next(
        record for record in caplog.records if record.getMessage() == "Command outcome"
    )
    assert outcome.context["command"] == "takeoff"
    assert outcome.context["status"] == "sent"


def test_a_timeout_is_logged_as_a_warning_with_an_unknown_outcome(caplog):
    caplog.set_level(
        logging.INFO, logger="drone_vision_lab.adapters.drone.command_channel"
    )
    sock = FakeUdpSocket([])
    channel = open_channel(sock)
    try:
        channel.submit("land", timeout=0.05)
    finally:
        channel.close()

    outcome = next(
        record for record in caplog.records if record.getMessage() == "Command outcome"
    )
    assert outcome.levelno == logging.WARNING
    assert outcome.context["status"] == "timeout"
    assert "outcome is unknown" in outcome.context["detail"].lower()


def test_a_lost_channel_is_logged_with_its_reason(caplog):
    caplog.set_level(
        logging.WARNING, logger="drone_vision_lab.adapters.drone.command_channel"
    )
    sock = FakeUdpSocket([], send_error=OSError("network unreachable"))
    channel = open_channel(sock)
    try:
        channel.submit("takeoff", timeout=0.1)
    finally:
        channel.close()

    lost = next(
        record
        for record in caplog.records
        if record.getMessage() == "Command channel marked unavailable"
    )
    assert "network unreachable" in lost.context["reason"]
