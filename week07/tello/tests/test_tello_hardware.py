"""Opt-in checks against a physical Tello on the ground.

Never run by default. Enable explicitly after powering on the aircraft and
joining its ``TELLO-xxxx`` Wi-Fi network:

    $env:TELLO_HARDWARE_TEST = "1"
    .venv\\Scripts\\python.exe -m pytest -m hardware -s

These tests send only the SDK ``command`` handshake and the camera commands
``streamon``/``streamoff``. They never take off, move, arm or change an aircraft
setting. If a test fails, the messages name the laptop-side cause to check
(network, UDP port, firewall, PyAV, other Tello tools).
"""

from __future__ import annotations

import os
import time

import pytest

from drone_vision_lab.adapters.drone import TelloDroneAdapter
from drone_vision_lab.adapters.drone.video_stream import TelloVideoReceiver
from drone_vision_lab.adapters.video import TelloVideoSource
from drone_vision_lab.domain import CommandResult, CommandStatus, Telemetry, telemetry_is_fresh
from drone_vision_lab.interfaces.video import VideoSourceStatus

pytestmark = pytest.mark.hardware

_TELEMETRY_WAIT_S = 10.0
_VIDEO_WAIT_S = 15.0
_POLL_S = 0.1


def _require_hardware() -> None:
    if os.environ.get("TELLO_HARDWARE_TEST") != "1":
        pytest.skip(
            "Set TELLO_HARDWARE_TEST=1, power on the Tello and join TELLO-xxxx "
            "to run the hardware check."
        )


def _connect(adapter: TelloDroneAdapter) -> CommandResult:
    result = adapter.connect(timeout=10.0)
    assert result.status is CommandStatus.SENT, result.detail
    assert result.status is not CommandStatus.CONFIRMED
    assert "No takeoff was sent" in result.detail
    assert adapter.connected
    return result


def _wait_for_fresh_telemetry(
    adapter: TelloDroneAdapter, timeout_s: float = _TELEMETRY_WAIT_S
) -> Telemetry:
    """Poll until a state packet arrives that is still within the freshness limit."""
    deadline = time.monotonic() + timeout_s
    telemetry = adapter.telemetry()
    while time.monotonic() < deadline:
        telemetry = adapter.telemetry()
        if telemetry_is_fresh(
            telemetry,
            now=time.monotonic(),
            max_age_s=adapter.telemetry_max_age_s,
        ):
            return telemetry
        time.sleep(_POLL_S)
    return telemetry


def _wait_for_frame(source: TelloVideoSource, timeout_s: float = _VIDEO_WAIT_S):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = source.read()
        if frame is not None:
            return frame
        time.sleep(_POLL_S)
    return None


def _receiver_counters(receiver: TelloVideoReceiver) -> str:
    return (
        f"packets={receiver.packets_received}, "
        f"decoded={receiver.frames_decoded}, "
        f"decode_errors={receiver.decode_errors}, "
        f"foreign={receiver.foreign_packets}, "
        f"error={receiver.error!r}"
    )


def test_connect_handshake_and_telemetry_only():
    _require_hardware()

    adapter = TelloDroneAdapter()
    try:
        _connect(adapter)

        telemetry = adapter.telemetry()
        print(f"Telemetry: {telemetry}")
        if telemetry.battery_percent is not None:
            print(f"Battery: {telemetry.battery_percent}%")
        else:
            print("Telemetry unavailable; connect still succeeded.")
    finally:
        adapter.disconnect()


def test_connection_telemetry_and_camera_signal_are_ready():
    """Ground check: connected, fresh telemetry, and decodable camera frames.

    This is the automated version of the "no-flight" readiness check: it proves
    the laptop can command the aircraft, receive its state packets and decode
    its H.264 stream. It sends no flight command and records nothing to disk.
    """
    _require_hardware()

    adapter = TelloDroneAdapter()
    receiver = TelloVideoReceiver()
    source = TelloVideoSource(receiver)
    try:
        _connect(adapter)
        assert adapter.telemetry_warning == "", (
            "The command channel works but telemetry did not start: "
            f"{adapter.telemetry_warning}"
        )

        telemetry = _wait_for_fresh_telemetry(adapter)
        assert telemetry.received_at is not None, (
            f"No state packet arrived within {_TELEMETRY_WAIT_S:.0f} s. Check the "
            "TELLO-xxxx Wi-Fi network, UDP 8890 inbound in the firewall, and that "
            "no other Tello tool owns the telemetry port."
        )
        assert telemetry_is_fresh(
            telemetry,
            now=time.monotonic(),
            max_age_s=adapter.telemetry_max_age_s,
        ), (
            "Telemetry arrived but is older than the freshness limit "
            f"({adapter.telemetry_max_age_s:.1f} s). The link is dropping packets; "
            f"last snapshot: {telemetry}"
        )
        assert telemetry.battery_percent is not None, (
            f"Telemetry arrived without a battery report: {telemetry}"
        )
        assert 0 <= telemetry.battery_percent <= 100, (
            f"Implausible battery report: {telemetry.battery_percent}"
        )
        assert telemetry.height_cm is not None, (
            f"Telemetry arrived without a height report: {telemetry}"
        )
        print(f"Telemetry: {telemetry}")

        stream = adapter.start_video_stream()
        assert stream.status is CommandStatus.SENT, stream.detail
        assert adapter.video_streaming is True
        assert "streamon" in stream.command

        source.open()
        frame = _wait_for_frame(source)
        assert frame is not None, (
            f"No decodable frame arrived within {_VIDEO_WAIT_S:.0f} s after "
            "streamon. Check UDP 11111 inbound, that PyAV is installed "
            '(`pip install -e ".[hardware]"`), and that no other tool owns the '
            f"video port. {_receiver_counters(receiver)}"
        )
        assert frame.image.ndim == 3 and frame.image.shape[2] == 3, (
            f"Decoded frame is not a BGR image: shape={frame.image.shape}"
        )
        assert frame.image.shape[0] > 0 and frame.image.shape[1] > 0
        assert source.status is VideoSourceStatus.LIVE, (
            f"Frames decoded but the source reports {source.status}: "
            f"{_receiver_counters(receiver)}"
        )
        height, width = frame.image.shape[:2]
        print(
            f"Video: {width}x{height}, first frame after {_receiver_counters(receiver)}"
        )
    finally:
        source.close()
        adapter.stop_video_stream()
        adapter.disconnect()
