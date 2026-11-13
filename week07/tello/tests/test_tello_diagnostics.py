"""Laptop-side checks: readable, honest, and they send no commands."""

from __future__ import annotations

from typing import Any

from tello_doubles import FakeUdpSocket

from drone_vision_lab.adapters.drone.diagnostics import (
    DiagnosticCheck,
    format_diagnostic_report,
    is_tello_address,
    run_tello_diagnostics,
)


class RecordingFactory:
    """A socket factory that records every socket it hands out."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self.sockets: list[FakeUdpSocket] = []

    def __call__(self, *_args: object) -> FakeUdpSocket:
        sock = FakeUdpSocket(**self._kwargs)
        self.sockets.append(sock)
        return sock


def socket_factory(**kwargs: Any) -> RecordingFactory:
    return RecordingFactory(**kwargs)


def by_name(checks, name: str) -> DiagnosticCheck:
    return next(check for check in checks if check.name == name)


def test_a_tello_network_address_passes_the_route_check():
    factory = socket_factory(local_address="192.168.10.2")

    checks = run_tello_diagnostics(socket_factory=factory)

    route = by_name(checks, "Route to the Tello")
    assert route.ok is True
    assert "192.168.10.2" in route.detail
    assert all(sock.sent == [] for sock in factory.sockets)


def test_an_internet_address_fails_and_explains_the_one_adapter_trap():
    factory = socket_factory(local_address="10.0.0.5")

    checks = run_tello_diagnostics(socket_factory=factory)

    route = by_name(checks, "Route to the Tello")
    assert route.ok is False
    assert "TELLO-xxxx" in route.detail
    assert "one Wi-Fi adapter" in route.detail


def test_a_connect_failure_does_not_crash_the_report():
    factory = socket_factory(connect_error=OSError("no route to host"))

    checks = run_tello_diagnostics(socket_factory=factory)

    route = by_name(checks, "Route to the Tello")
    assert route.ok is False
    assert "could not choose a local address" in route.detail


def test_busy_ports_fail_the_matching_checks():
    factory = socket_factory(bind_error=OSError("address already in use"))

    checks = run_tello_diagnostics(socket_factory=factory)

    assert by_name(checks, "Telemetry port UDP 8890").ok is False
    assert by_name(checks, "Video port UDP 11111").ok is False
    assert by_name(checks, "Command socket").ok is False


def test_a_port_held_by_this_application_is_informational():
    factory = socket_factory(bind_error=OSError("address already in use"))

    checks = run_tello_diagnostics(socket_factory=factory, app_connected=True)

    state_port = by_name(checks, "Telemetry port UDP 8890")
    assert state_port.ok is None
    assert "own receiver" in state_port.detail
    assert by_name(checks, "Video port UDP 11111").ok is False
    assert by_name(checks, "Command socket").ok is False


def test_the_active_video_port_is_informational_too():
    factory = socket_factory(bind_error=OSError("address already in use"))

    checks = run_tello_diagnostics(
        socket_factory=factory, app_connected=True, video_active=True
    )

    assert by_name(checks, "Video port UDP 11111").ok is None


def test_firewall_and_control_authority_are_informational_only():
    checks = run_tello_diagnostics(socket_factory=socket_factory())

    firewall = by_name(checks, "Windows firewall")
    authority = by_name(checks, "Control authority")
    assert firewall.ok is None
    assert authority.ok is None
    assert "UDP" in firewall.detail
    assert "does not arbitrate" in authority.detail


def test_the_report_marks_pass_fail_and_info_without_overstating():
    report = format_diagnostic_report(
        (
            DiagnosticCheck("route", True, "on the Tello network"),
            DiagnosticCheck("telemetry", False, "port busy"),
            DiagnosticCheck("firewall", None, "cannot be checked here"),
        )
    )

    assert "[PASS] route" in report
    assert "[FAIL] telemetry" in report
    assert "[INFO] firewall" in report
    assert "cannot be checked here" in report


def test_only_the_tello_subnet_is_recognised():
    assert is_tello_address("192.168.10.1") is True
    assert is_tello_address("192.168.11.1") is False
    assert is_tello_address("not an address") is False
