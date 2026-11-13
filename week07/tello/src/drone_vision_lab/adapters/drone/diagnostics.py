"""Local checks before blaming the aircraft.

When a Tello does not answer, the cause is usually the laptop: it is still on
the classroom Wi-Fi instead of the Tello's own network, a firewall blocks the
UDP replies, another Tello tool owns port 8890/11111, or the machine has only
one Wi-Fi adapter and cannot be on both networks at once.

These checks are read-only and send no command. They cannot prove the aircraft
is reachable — only a ``command`` handshake does that — so the report says what
it checked and what it cannot check.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from dataclasses import dataclass

from .command_channel import SocketFactory
from .tello_protocol import TelloSettings

__all__ = [
    "DiagnosticCheck",
    "TELLO_NETWORK",
    "format_diagnostic_report",
    "is_tello_address",
    "run_tello_diagnostics",
]

TELLO_NETWORK = ipaddress.ip_network("192.168.10.0/24")


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    ok: bool | None
    """``None`` means the check is informational and cannot pass or fail."""
    detail: str


def is_tello_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address) in TELLO_NETWORK
    except ValueError:
        return False


def run_tello_diagnostics(
    settings: TelloSettings | None = None,
    *,
    socket_factory: SocketFactory = socket.socket,
    app_connected: bool = False,
    video_active: bool = False,
) -> tuple[DiagnosticCheck, ...]:
    """Run the laptop-side checklist. Sends no UDP packets.

    ``app_connected`` and ``video_active`` say whether this application already
    owns the state or video port. A bind failure then means "this app is
    listening", not a fault, so the check is reported as informational rather
    than as a failure.
    """
    settings = settings or TelloSettings()
    checks: list[DiagnosticCheck] = []

    local_address: str | None = None
    route_socket = None
    try:
        route_socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        route_socket.connect((settings.host, settings.command_port))
        local_address = route_socket.getsockname()[0]
    except (OSError, AttributeError) as exc:
        checks.append(
            DiagnosticCheck(
                "Route to the Tello",
                False,
                f"Windows could not choose a local address for {settings.host}: {exc}",
            )
        )
    else:
        if is_tello_address(local_address):
            checks.append(
                DiagnosticCheck(
                    "Route to the Tello",
                    True,
                    f"This computer routes Tello traffic from {local_address} "
                    "(the Tello network).",
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    "Route to the Tello",
                    False,
                    f"Windows would send Tello traffic from {local_address}, which is "
                    "not on 192.168.10.0/24. Join the TELLO-xxxx Wi-Fi network. If the "
                    "laptop has one Wi-Fi adapter, it cannot stay on the internet and "
                    "the Tello network at the same time; use a second Wi-Fi/USB "
                    "adapter or disconnect from the internet for the flight.",
                )
            )
    finally:
        if route_socket is not None:
            _close(route_socket)

    checks.append(
        _bind_check(
            socket_factory,
            "Command socket",
            settings,
            None,
            "An outbound UDP command socket can be created.",
        )
    )
    checks.append(
        _bind_check(
            socket_factory,
            f"Telemetry port UDP {settings.local_state_port}",
            settings,
            settings.local_state_port,
            "State packets can be received. Another Tello tool holding this port "
            "would leave telemetry unavailable.",
            in_use_by_app=app_connected,
        )
    )
    checks.append(
        _bind_check(
            socket_factory,
            f"Video port UDP {settings.local_video_port}",
            settings,
            settings.local_video_port,
            "Tello video can be received on this port.",
            in_use_by_app=video_active,
        )
    )
    checks.append(
        DiagnosticCheck(
            "Windows firewall",
            None,
            "Allow the Python interpreter or the packaged application on Private "
            "networks for UDP: commands are sent to 8889, telemetry arrives on 8890 "
            "and video on 11111. A blocked inbound rule shows up as a command "
            "timeout, not as a clear firewall error.",
        )
    )
    checks.append(
        DiagnosticCheck(
            "Control authority",
            None,
            "Close the DJI Tello app's control session first. A standard Tello does "
            "not arbitrate: the phone app and this application would both take effect.",
        )
    )
    return tuple(checks)


def format_diagnostic_report(checks: tuple[DiagnosticCheck, ...]) -> str:
    lines = []
    for check in checks:
        marker = "PASS" if check.ok is True else "FAIL" if check.ok is False else "INFO"
        lines.append(f"[{marker}] {check.name}\n    {check.detail}")
    return "\n\n".join(lines)


def _bind_check(
    socket_factory: SocketFactory,
    name: str,
    settings: TelloSettings,
    port: int | None,
    success: str,
    *,
    in_use_by_app: bool = False,
) -> DiagnosticCheck:
    sock = None
    try:
        sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", 0) if port is None else ("", port))
    except (OSError, AttributeError) as exc:
        if in_use_by_app:
            return DiagnosticCheck(
                name,
                None,
                f"UDP port {port} is already bound ({exc}). This application is "
                "using it, so the conflict most likely comes from its own "
                "receiver. If the corresponding data is arriving, no action is "
                "needed; another Tello tool would also hold the port exclusively.",
            )
        return DiagnosticCheck(name, False, f"Could not open UDP port {port}: {exc}")
    finally:
        if sock is not None:
            _close(sock)
    return DiagnosticCheck(name, True, success)


def _close(sock: object) -> None:
    with contextlib.suppress(OSError, AttributeError):
        sock.close()  # type: ignore[attr-defined]
