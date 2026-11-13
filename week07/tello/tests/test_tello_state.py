"""State receiver: reported telemetry only, and a clear failure when the port is taken."""

from __future__ import annotations

import logging

import pytest
from tello_doubles import FakeClock, FakeUdpSocket, SocketFactory, wait_until

from drone_vision_lab.adapters.drone.state_receiver import TelloStateReceiver
from drone_vision_lab.errors import HardwareUnavailableError


def make_receiver(
    sock: FakeUdpSocket,
    *,
    clock: FakeClock | None = None,
) -> TelloStateReceiver:
    return TelloStateReceiver(
        socket_factory=SocketFactory([sock]),
        clock=clock or FakeClock(),
    )


def test_state_packets_become_the_latest_telemetry():
    sock = FakeUdpSocket(["bat:88;h:0;time:5;templ:50.0;"])
    clock = FakeClock(now=10.0)
    receiver = make_receiver(sock, clock=clock)
    receiver.open()
    try:
        assert wait_until(lambda: receiver.packets_received == 1)
        telemetry = receiver.latest()
    finally:
        receiver.stop()

    assert telemetry.battery_percent == 88
    assert telemetry.height_cm == 0
    assert telemetry.flight_time_s == 5
    assert telemetry.temperature_c == 50.0
    assert telemetry.received_at == 10.0
    assert receiver.last_received_at == 10.0
    assert receiver.listening is False


def test_the_receiver_binds_the_documented_state_port():
    sock = FakeUdpSocket(["bat:50;"])
    receiver = make_receiver(sock)
    receiver.open()
    try:
        assert sock.bound == ("", 8890)
        assert receiver.listening is True
    finally:
        receiver.stop()


def test_unparseable_packets_are_counted_and_leave_telemetry_unreported():
    sock = FakeUdpSocket(["not a state packet"])
    receiver = make_receiver(sock)
    receiver.open()
    try:
        assert wait_until(lambda: receiver.packets_received == 1)
        assert receiver.parse_failures == 1
        telemetry = receiver.latest()
    finally:
        receiver.stop()

    assert telemetry.battery_percent is None
    assert receiver.last_received_at is None


def test_packets_from_another_host_never_become_telemetry():
    sock = FakeUdpSocket(["bat:88;h:0;"], sender=("192.168.10.99", 8890))
    receiver = make_receiver(sock)
    receiver.open()
    try:
        assert wait_until(lambda: receiver.foreign_packets == 1)
        telemetry = receiver.latest()
    finally:
        receiver.stop()

    assert telemetry.battery_percent is None
    assert receiver.packets_received == 0
    assert receiver.last_received_at is None


def test_a_busy_port_raises_a_user_facing_error_and_closes_the_socket():
    sock = FakeUdpSocket(bind_error=OSError("address already in use"))
    receiver = make_receiver(sock)

    with pytest.raises(HardwareUnavailableError) as caught:
        receiver.open()

    assert "UDP port 8890" in caught.value.user_message
    assert sock.closed is True
    assert receiver.listening is False


def test_stop_is_safe_before_open():
    sock = FakeUdpSocket([])
    receiver = make_receiver(sock)

    receiver.stop()

    assert receiver.listening is False
    assert sock.closed is False


# -- logging -----------------------------------------------------------------


def test_the_first_state_packet_is_logged(caplog):
    caplog.set_level(
        logging.INFO, logger="drone_vision_lab.adapters.drone.state_receiver"
    )
    sock = FakeUdpSocket(["bat:88;h:0;"])
    receiver = make_receiver(sock)
    receiver.open()
    try:
        assert wait_until(lambda: receiver.packets_received == 1)
        assert wait_until(
            lambda: any(
                record.getMessage() == "First state packet received"
                for record in caplog.records
            )
        )
    finally:
        receiver.stop()


def test_telemetry_silence_is_reported_once_so_the_link_loss_is_datestamped(caplog):
    caplog.set_level(
        logging.WARNING, logger="drone_vision_lab.adapters.drone.state_receiver"
    )
    sock = FakeUdpSocket([])
    clock = FakeClock(now=10.0)
    receiver = make_receiver(sock, clock=clock)
    receiver.open()
    try:
        clock.now = 10.0 + receiver.state_gap_after_s + 1.0
        assert wait_until(
            lambda: any(
                record.getMessage()
                == "No state packet received since the receiver opened"
                for record in caplog.records
            )
        )
        # The worker keeps polling; the warning must not repeat on every timeout.
        clock.now += 1.0
    finally:
        receiver.stop()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
