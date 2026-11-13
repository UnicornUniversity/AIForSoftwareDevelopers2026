"""The standard-Tello adapter: honest command results and no hidden flight actions."""

from __future__ import annotations

import threading

import pytest
from tello_doubles import FakeClock, StubCommandChannel, StubStateReceiver

from drone_vision_lab.adapters.drone.tello_drone import TelloDroneAdapter
from drone_vision_lab.domain import CommandResult, CommandStatus, Telemetry
from drone_vision_lab.errors import HardwareUnavailableError


def make_adapter(
    *,
    clock: FakeClock | None = None,
    channel: StubCommandChannel | None = None,
    state: StubStateReceiver | None = None,
) -> tuple[TelloDroneAdapter, StubCommandChannel, StubStateReceiver, FakeClock]:
    clock = clock or FakeClock()
    channel = channel or StubCommandChannel(clock=clock)
    state = state or StubStateReceiver()
    adapter = TelloDroneAdapter(
        command_channel=channel,
        state_receiver=state,
        clock=clock,
        sleep=clock.sleep,
    )
    return adapter, channel, state, clock


def connected_adapter() -> tuple[
    TelloDroneAdapter, StubCommandChannel, StubStateReceiver, FakeClock
]:
    adapter, channel, state, clock = make_adapter()
    result = adapter.connect()
    assert result.status is CommandStatus.SENT
    return adapter, channel, state, clock


def test_connect_sends_the_handshake_and_never_takes_off():
    adapter, channel, state, _clock = connected_adapter()

    assert channel.calls == [("command", 10.0, False)]
    assert state.opened == 1
    assert adapter.connected
    assert all("takeoff" not in command for command, _timeout, _urgent in channel.calls)


def test_connecting_twice_does_not_resend_the_handshake():
    adapter, channel, _state, _clock = connected_adapter()

    second = adapter.connect()

    assert second.status is CommandStatus.SENT
    assert second.detail == "Already connected."
    assert len(channel.calls) == 1


def test_a_failed_handshake_closes_the_channel_and_explains_the_likely_cause():
    channel = StubCommandChannel(
        handler=lambda command: CommandResult(
            command,
            CommandStatus.TIMEOUT,
            "No reply within the timeout.",
            requested_at=0.0,
            completed_at=5.0,
        )
    )
    adapter, channel, state, _clock = make_adapter(channel=channel)

    result = adapter.connect()

    assert result.status is CommandStatus.TIMEOUT
    assert "TELLO-xxxx" in result.detail
    assert "firewall" in result.detail
    assert channel.closed == 1
    assert state.opened == 0
    assert not adapter.connected


def test_an_unopenable_command_socket_is_reported_without_guessing():
    channel = StubCommandChannel(open_error=OSError("network unreachable"))
    adapter, _channel, state, _clock = make_adapter(channel=channel)

    result = adapter.connect()

    assert result.status is CommandStatus.FAILED
    assert "Could not open the command socket" in result.detail
    assert state.opened == 0


def test_missing_telemetry_is_reported_but_does_not_block_connect():
    state = StubStateReceiver()
    state.open_error = HardwareUnavailableError(
        "state port unavailable",
        user_message="Telemetry is unavailable: UDP port 8890 is busy.",
    )
    adapter, _channel, _state, _clock = make_adapter(state=state)

    result = adapter.connect()

    assert result.status is CommandStatus.SENT
    assert "Telemetry is unavailable: UDP port 8890 is busy." in result.detail
    assert "port 8890" in adapter.telemetry_warning
    assert adapter.telemetry() == Telemetry()


def test_land_is_only_confirmed_when_late_telemetry_shows_touchdown():
    adapter, _channel, state, clock = connected_adapter()
    state.telemetry = Telemetry(height_cm=0, received_at=clock.now)

    result = adapter.land()

    assert result.status is CommandStatus.CONFIRMED
    assert "observed in telemetry" in result.detail


def test_land_stays_sent_when_touchdown_was_not_observed():
    adapter, _channel, state, _clock = connected_adapter()
    state.telemetry = Telemetry(height_cm=42, received_at=0.0)

    result = adapter.land()

    assert result.status is CommandStatus.SENT
    assert result.status is not CommandStatus.CONFIRMED
    assert "not independently observed" in result.detail


def test_land_stays_sent_when_telemetry_is_not_listening():
    state = StubStateReceiver()
    state.open_error = HardwareUnavailableError("state port unavailable")
    adapter, _channel, _state, _clock = make_adapter(state=state)
    assert adapter.connect().status is CommandStatus.SENT

    result = adapter.land()

    assert result.status is CommandStatus.SENT
    assert "not independently observed" in result.detail


def test_land_passes_through_a_channel_timeout_unchanged():
    def handler(command: str) -> CommandResult | None:
        if command == "land":
            return CommandResult(
                "land",
                CommandStatus.TIMEOUT,
                "No reply within the timeout; the outcome is unknown.",
                requested_at=0.0,
                completed_at=1.0,
            )
        return None

    adapter, _channel, _state, _clock = make_adapter(
        channel=StubCommandChannel(handler=handler)
    )
    assert adapter.connect().status is CommandStatus.SENT

    result = adapter.land()

    assert result.status is CommandStatus.TIMEOUT
    assert "unknown" in result.detail


def test_emergency_land_is_urgent_and_never_reported_as_confirmed():
    adapter, channel, state, clock = connected_adapter()
    state.telemetry = Telemetry(height_cm=0, received_at=clock.now)

    result = adapter.emergency_land()

    assert result.status is CommandStatus.SENT
    assert result.status is not CommandStatus.CONFIRMED
    assert "Motors were not cut" in result.detail
    assert ("land", 5.0, True) in channel.calls
    assert all("motorstop" not in command for command, _timeout, _urgent in channel.calls)


def test_emergency_land_without_a_channel_says_it_cannot_force_a_landing():
    adapter, channel, _state, _clock = make_adapter()

    result = adapter.emergency_land()

    assert result.status is CommandStatus.FAILED
    assert "cannot force a landing" in result.detail
    assert channel.calls == []


def test_move_sends_the_speed_setting_before_the_translation():
    adapter, channel, _state, _clock = connected_adapter()

    result = adapter.move("forward", 50, speed=40)

    assert result.status is CommandStatus.SENT
    assert [command for command, _timeout, _urgent in channel.calls] == [
        "command",
        "speed 40",
        "forward 50",
    ]


def test_move_stops_before_translating_when_the_speed_command_fails():
    def handler(command: str) -> CommandResult | None:
        if command == "speed 40":
            return CommandResult(
                "speed 40",
                CommandStatus.FAILED,
                "The aircraft refused the command (error).",
                requested_at=0.0,
                completed_at=0.0,
            )
        return None

    adapter, channel, _state, _clock = make_adapter(
        channel=StubCommandChannel(handler=handler)
    )
    assert adapter.connect().status is CommandStatus.SENT
    sent_before = len(channel.calls)

    result = adapter.move("forward", 50, speed=40)

    assert result.status is CommandStatus.FAILED
    assert len(channel.calls) == sent_before + 1
    assert channel.calls[-1][0] == "speed 40"


@pytest.mark.parametrize(
    ("direction", "distance"),
    [("sideways", 50), ("forward", 19), ("forward", 501)],
)
def test_invalid_moves_are_rejected_before_transmission(direction, distance):
    adapter, channel, _state, _clock = connected_adapter()

    result = adapter.move(direction, distance)

    assert result.status is CommandStatus.REJECTED
    assert "Refused locally" in result.detail
    assert len(channel.calls) == 1  # only the connect handshake


def test_an_out_of_range_speed_is_rejected_before_transmission():
    adapter, channel, _state, _clock = connected_adapter()

    result = adapter.move("forward", 50, speed=5)

    assert result.status is CommandStatus.REJECTED
    assert "speed must be" in result.detail
    assert len(channel.calls) == 1


def test_move_and_rotate_require_a_connection():
    adapter, channel, _state, _clock = make_adapter()

    assert adapter.move("forward", 50).status is CommandStatus.FAILED
    assert adapter.rotate("cw", 90).status is CommandStatus.FAILED
    assert channel.calls == []


def test_rotate_uses_the_sdk_syntax():
    adapter, channel, _state, _clock = connected_adapter()

    result = adapter.rotate("clockwise", 90)

    assert result.status is CommandStatus.SENT
    assert channel.calls[-1] == ("cw 90", 10.0, False)


def test_an_invalid_rotation_is_rejected():
    adapter, channel, _state, _clock = connected_adapter()

    result = adapter.rotate("left", 90)

    assert result.status is CommandStatus.REJECTED
    assert len(channel.calls) == 1


def test_video_stream_start_and_stop_are_explicit_commands():
    adapter, channel, _state, _clock = connected_adapter()

    started = adapter.start_video_stream()
    streaming_after_start = adapter.video_streaming
    stopped = adapter.stop_video_stream()

    assert started.status is CommandStatus.SENT
    assert streaming_after_start is True
    assert stopped.status is CommandStatus.SENT
    assert adapter.video_streaming is False
    assert [command for command, _timeout, _urgent in channel.calls[-2:]] == [
        "streamon",
        "streamoff",
    ]


def test_a_refused_stream_request_leaves_streaming_false():
    def handler(command: str) -> CommandResult | None:
        if command == "streamon":
            return CommandResult(
                "streamon",
                CommandStatus.FAILED,
                "The aircraft refused the command (error).",
                requested_at=0.0,
                completed_at=0.0,
            )
        return None

    adapter, _channel, _state, _clock = make_adapter(
        channel=StubCommandChannel(handler=handler)
    )
    assert adapter.connect().status is CommandStatus.SENT

    result = adapter.start_video_stream()

    assert result.status is CommandStatus.FAILED
    assert adapter.video_streaming is False


def test_the_stream_cannot_be_started_without_a_connection():
    adapter, channel, _state, _clock = make_adapter()

    result = adapter.start_video_stream()

    assert result.status is CommandStatus.FAILED
    assert channel.calls == []
    assert adapter.video_streaming is False


def test_telemetry_is_empty_until_the_aircraft_reports_values():
    adapter, _channel, _state, _clock = make_adapter()

    assert adapter.telemetry() == Telemetry()


def test_telemetry_returns_the_latest_reported_snapshot():
    adapter, _channel, state, clock = connected_adapter()
    reported = Telemetry(battery_percent=77, height_cm=30, received_at=clock.now)
    state.telemetry = reported

    assert adapter.telemetry() == reported


def test_connecting_again_retries_telemetry_that_failed_the_first_time():
    state = StubStateReceiver()
    state.open_error = HardwareUnavailableError(
        "state port unavailable",
        user_message="Telemetry is unavailable: UDP port 8890 is busy.",
    )
    adapter, _channel, prepared_state, _clock = make_adapter(state=state)
    first = adapter.connect()
    assert "Telemetry is unavailable" in first.detail
    assert prepared_state.opened == 0

    state.open_error = None
    second = adapter.connect()

    assert second.detail == "Already connected."
    assert prepared_state.opened == 1
    assert adapter.telemetry_warning == ""


def test_disconnect_stops_a_camera_stream_it_started():
    adapter, channel, _state, _clock = connected_adapter()
    assert adapter.start_video_stream().ok

    adapter.disconnect()

    assert ("streamoff", 1.0, False) in channel.calls
    assert adapter.video_streaming is False


def test_disconnect_while_a_stream_stop_is_pending_sends_one_streamoff():
    stop_started = threading.Event()
    release_stop = threading.Event()

    def handler(command: str) -> CommandResult | None:
        if command == "streamoff":
            stop_started.set()
            release_stop.wait(2.0)
        return None

    channel = StubCommandChannel(handler=handler)
    adapter, channel, _state, _clock = make_adapter(channel=channel)
    assert adapter.connect().ok
    assert adapter.start_video_stream().ok

    stopper = threading.Thread(target=adapter.stop_video_stream, daemon=True)
    stopper.start()
    try:
        assert stop_started.wait(2.0)
        adapter.disconnect()
    finally:
        release_stop.set()
        stopper.join(2.0)

    streamoffs = [call for call in channel.calls if call[0] == "streamoff"]
    assert len(streamoffs) == 1


def test_disconnect_without_a_stream_sends_no_extra_command():
    adapter, channel, _state, _clock = connected_adapter()
    calls_before = len(channel.calls)

    adapter.disconnect()

    assert len(channel.calls) == calls_before
    assert all(command != "streamoff" for command, _timeout, _urgent in channel.calls)


def test_disconnect_closes_both_channels():
    adapter, channel, state, _clock = connected_adapter()

    adapter.disconnect()

    assert not adapter.connected
    assert state.stopped == 1
    assert channel.closed == 1


def test_a_lost_command_channel_can_be_reconnected():
    adapter, channel, _state, _clock = connected_adapter()
    channel.close()

    assert not adapter.connected
    assert adapter.send_command("takeoff").status is CommandStatus.FAILED

    result = adapter.connect()

    assert result.status is CommandStatus.SENT
    assert adapter.connected
    assert channel.opened == 2
    assert [command for command, _timeout, _urgent in channel.calls].count("command") == 2


def test_nothing_is_transmitted_while_the_channel_is_lost():
    adapter, channel, _state, _clock = connected_adapter()
    channel.close()
    transmitted_before = len(channel.calls)

    assert adapter.emergency_land().status is CommandStatus.FAILED
    assert adapter.move("forward", 50).status is CommandStatus.FAILED
    assert adapter.rotate("cw", 90).status is CommandStatus.FAILED
    assert len(channel.calls) == transmitted_before
