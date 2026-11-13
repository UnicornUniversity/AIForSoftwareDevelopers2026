"""Tello camera: decode-only input, stale when packets stop, never recorded."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from tello_doubles import (
    FakeAvFrame,
    FakeClock,
    FakeUdpSocket,
    SocketFactory,
    StubVideoReceiver,
    make_fake_av,
)

from drone_vision_lab.adapters.drone.video_stream import TelloVideoReceiver
from drone_vision_lab.adapters.video import SOURCE_TELLO, make_video_source
from drone_vision_lab.adapters.video.tello_video import TelloVideoSource
from drone_vision_lab.errors import HardwareUnavailableError
from drone_vision_lab.interfaces.video import VideoSourceState, VideoSourceStatus


def make_receiver(sock: FakeUdpSocket, av, *, clock: FakeClock | None = None):
    return TelloVideoReceiver(
        socket_factory=SocketFactory([sock]),
        av_module=av,
        clock=clock or FakeClock(),
    )


def test_packets_are_decoded_into_bgr_images():
    image = np.full((48, 64, 3), 7, dtype=np.uint8)
    av, codec = make_fake_av(image)
    sock = FakeUdpSocket([b"h264-payload"])
    clock = FakeClock(now=3.0)
    receiver = make_receiver(sock, av, clock=clock)
    receiver.open()
    try:
        frame = receiver.read_frame()
    finally:
        receiver.close()

    assert frame is not None
    assert frame.shape == (48, 64, 3)
    assert frame.dtype == np.uint8
    assert receiver.frames_decoded == 1
    assert receiver.packets_received == 1
    assert receiver.last_packet_at == 3.0
    assert codec.packets == [b"h264-payload"]


def test_the_decoder_is_single_threaded_for_corrupt_packet_safety():
    """Slice-threaded H.264 decode has crashed natively on truncated UDP data.

    A native access violation cannot be caught in Python, so the decoder is
    pinned to one thread; this test keeps the mitigation from being removed.
    """
    av, codec = make_fake_av()
    sock = FakeUdpSocket([b"payload"])
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        assert codec.thread_count == 1
        assert codec.thread_type == "NONE"
    finally:
        receiver.close()


def test_the_receiver_never_sends_commands_or_writes_files():
    av, _codec = make_fake_av()
    sock = FakeUdpSocket([b"payload"])
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        receiver.read_frame()
    finally:
        receiver.close()

    assert sock.bound == ("", 11111)
    assert sock.sent == []


def test_packets_from_another_host_are_not_decoded():
    av, _codec = make_fake_av()
    sock = FakeUdpSocket([b"payload"], sender=("192.168.10.99", 11111))
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        frame = receiver.read_frame()
    finally:
        receiver.close()

    assert frame is None
    assert receiver.packets_received == 0
    assert receiver.foreign_packets == 1


def test_one_read_call_decodes_a_bounded_number_of_packets():
    class Codec:
        def parse(self, payload: bytes) -> list[bytes]:
            return [] if payload == b"filler" else [payload]

        def decode(self, _packet: bytes) -> list[FakeAvFrame]:
            return [FakeAvFrame(np.zeros((48, 64, 3), dtype=np.uint8))]

    class CodecContext:
        @staticmethod
        def create(name: str, mode: str) -> Codec:
            assert (name, mode) == ("h264", "r")
            return Codec()

    av = SimpleNamespace(CodecContext=CodecContext)
    sock = FakeUdpSocket([b"filler"] * 400 + [b"frame"])
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        first = receiver.read_frame()
        consumed_by_first = receiver.packets_received
        second = receiver.read_frame()
    finally:
        receiver.close()

    # One call must not spin through an unbounded number of packets; it
    # returns so the caller can poll again, and the later frame still arrives.
    assert first is None
    assert consumed_by_first < 401
    assert second is not None
    assert receiver.frames_decoded == 1


def test_a_decode_failure_is_counted_and_does_not_stop_the_stream():
    av, _codec = make_fake_av(fail=True)
    sock = FakeUdpSocket([b"payload"])
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        frame = receiver.read_frame()
    finally:
        receiver.close()

    assert frame is None
    assert receiver.decode_errors == 1


def test_an_idle_stream_returns_none_rather_than_blocking():
    av, _codec = make_fake_av()
    sock = FakeUdpSocket([])
    receiver = make_receiver(sock, av)
    receiver.open()
    try:
        frame = receiver.read_frame()
    finally:
        receiver.close()

    assert frame is None
    assert receiver.frames_decoded == 0


def test_a_decoder_that_cannot_be_created_is_a_hardware_error():
    class BrokenCodecContext:
        @staticmethod
        def create(name: str, mode: str) -> None:
            raise RuntimeError("no h264 decoder")

    av = SimpleNamespace(CodecContext=BrokenCodecContext)
    sock = FakeUdpSocket([])
    receiver = make_receiver(sock, av)

    with pytest.raises(HardwareUnavailableError) as caught:
        receiver.open()

    assert "H.264 decoder" in caught.value.user_message
    assert sock.closed is False


def test_a_busy_video_port_is_a_hardware_error():
    av, _codec = make_fake_av()
    sock = FakeUdpSocket([], bind_error=OSError("address already in use"))
    receiver = make_receiver(sock, av)

    with pytest.raises(HardwareUnavailableError) as caught:
        receiver.open()

    assert "UDP 11111" in caught.value.user_message
    assert sock.closed is True


def test_the_source_reports_stale_until_packets_arrive_and_again_when_they_stop():
    receiver = StubVideoReceiver()
    clock = FakeClock()
    source = TelloVideoSource(receiver, stale_after_s=2.0, clock=clock)

    assert source.status is VideoSourceStatus.OFFLINE
    source.open()
    assert source.state is VideoSourceState.READY
    assert source.status is VideoSourceStatus.STALE
    assert source.description == "Tello camera — waiting for video"

    receiver.last_packet_at = 0.0
    assert source.status is VideoSourceStatus.LIVE

    clock.now = 2.1
    assert source.status is VideoSourceStatus.STALE


def test_frames_carry_provenance_and_advance_the_index():
    receiver = StubVideoReceiver(np.zeros((48, 64, 3), dtype=np.uint8))
    clock = FakeClock(now=5.0)
    source = TelloVideoSource(receiver, clock=clock)
    source.open()

    first = source.read()
    second = source.read()

    assert first is not None and second is not None
    assert first.source_id == "tello::camera"
    assert first.index == 0
    assert second.index == 1
    assert first.captured_at == 5.0
    assert source.description == "Tello camera — 64x48, H.264 over UDP"
    assert source.seek(1.0) is False
    assert source.set_looping(True) is None


def test_pausing_stops_reading_without_closing_the_camera():
    receiver = StubVideoReceiver()
    source = TelloVideoSource(receiver)
    source.open()

    source.pause()

    assert source.state is VideoSourceState.PAUSED
    assert source.status is VideoSourceStatus.STALE
    assert source.read() is None

    source.resume()

    assert source.state is VideoSourceState.READY
    assert source.read() is not None


def test_an_open_failure_is_surfaced_and_the_source_is_in_error():
    receiver = StubVideoReceiver()
    receiver.open_error = HardwareUnavailableError("no video port")
    source = TelloVideoSource(receiver)

    with pytest.raises(HardwareUnavailableError):
        source.open()

    assert source.state is VideoSourceState.ERROR
    assert source.status is VideoSourceStatus.ERROR


def test_close_releases_the_receiver():
    receiver = StubVideoReceiver()
    source = TelloVideoSource(receiver)
    source.open()

    source.close()

    assert source.state is VideoSourceState.CLOSED
    assert source.status is VideoSourceStatus.OFFLINE
    assert receiver.closed == 1


def test_the_tello_source_is_available_through_the_factory():
    source = make_video_source(SOURCE_TELLO, None)

    assert isinstance(source, TelloVideoSource)
    assert source.source_id == "tello::camera"
