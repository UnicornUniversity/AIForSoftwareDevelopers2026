"""Standard Tello protocol: state parsing and command syntax."""

from __future__ import annotations

import pytest

from drone_vision_lab.adapters.drone.tello_protocol import (
    TelloSettings,
    build_move_command,
    build_rotate_command,
    is_acknowledgement,
    is_error_reply,
    normalize_command,
    parse_state_packet,
)

STANDARD_PACKET = (
    "pitch:0;roll:0;yaw:0;vgx:0;vgy:0;vgz:0;templ:66.0;temph:68.0;tof:10;"
    "h:42;bat:83;baro:12.3;time:71;agx:0.0;agy:0.0;agz:-1000.0;"
)


def test_standard_state_packet_is_parsed_without_guessing():
    telemetry = parse_state_packet(STANDARD_PACKET, received_at=123.5)

    assert telemetry is not None
    assert telemetry.battery_percent == 83
    assert telemetry.height_cm == 42
    assert telemetry.flight_time_s == 71
    assert telemetry.temperature_c == 68.0
    assert telemetry.received_at == 123.5
    # Fields the packet does not contain stay unreported.
    assert telemetry.wifi_snr is None


def test_bytes_and_partial_packets_are_accepted():
    telemetry = parse_state_packet(b"bat:55;h:0;", received_at=1.0)

    assert telemetry is not None
    assert telemetry.battery_percent == 55
    assert telemetry.height_cm == 0
    assert telemetry.flight_time_s is None


def test_malformed_fields_are_dropped_not_guessed():
    telemetry = parse_state_packet(
        "bat:not-a-number;h:-4;time:x;templ:nan;temph:inf;",
        received_at=1.0,
    )

    assert telemetry is not None
    assert telemetry.battery_percent is None
    assert telemetry.height_cm is None
    assert telemetry.flight_time_s is None
    assert telemetry.temperature_c is None


def test_impossible_battery_and_negative_height_are_not_reported():
    telemetry = parse_state_packet("bat:150;h:-3;", received_at=1.0)

    assert telemetry is not None
    assert telemetry.battery_percent is None
    assert telemetry.height_cm is None


def test_temperature_falls_back_to_the_low_reading():
    telemetry = parse_state_packet("templ:44.5;", received_at=1.0)

    assert telemetry is not None
    assert telemetry.temperature_c == 44.5


@pytest.mark.parametrize("payload", ["", "   ", "no fields here", "; ; ;"])
def test_non_state_payloads_return_none(payload):
    assert parse_state_packet(payload) is None


def test_acknowledgement_helpers_do_not_overstate():
    assert is_acknowledgement("ok\r\n") is True
    assert is_acknowledgement("OK") is True
    assert is_acknowledgement("error Not joystick") is False
    assert is_error_reply("error Not joystick") is True
    assert is_error_reply("ok") is False


def test_commands_are_normalized_and_line_breaks_refused():
    assert normalize_command("  takeoff  ") == "takeoff"
    with pytest.raises(ValueError):
        normalize_command("takeoff\nland")
    with pytest.raises(ValueError):
        normalize_command("")
    with pytest.raises(ValueError):
        normalize_command("x" * 65)
    with pytest.raises(ValueError):
        normalize_command(42)  # type: ignore[arg-type]


def test_move_command_uses_the_sdk_syntax_and_limits():
    assert build_move_command("forward", 50) == "forward 50"
    with pytest.raises(ValueError):
        build_move_command("sideways", 50)
    with pytest.raises(ValueError):
        build_move_command("forward", 19)
    with pytest.raises(ValueError):
        build_move_command("forward", 501)
    with pytest.raises(ValueError):
        build_move_command("forward", True)  # type: ignore[arg-type]


def test_rotation_accepts_both_direction_names():
    assert build_rotate_command("clockwise", 90) == "cw 90"
    assert build_rotate_command("counter_clockwise", 45) == "ccw 45"
    assert build_rotate_command("ccw", 360) == "ccw 360"
    with pytest.raises(ValueError):
        build_rotate_command("left", 90)
    with pytest.raises(ValueError):
        build_rotate_command("cw", 0)
    with pytest.raises(ValueError):
        build_rotate_command("cw", 361)


def test_settings_reject_impossible_ports_and_negative_times():
    with pytest.raises(ValueError):
        TelloSettings(command_port=70000)
    with pytest.raises(ValueError):
        TelloSettings(response_timeout_s=-1)
    with pytest.raises(ValueError):
        TelloSettings(host="")
