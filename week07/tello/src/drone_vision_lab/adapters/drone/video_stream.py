"""Tello camera receiver: UDP packets in, decoded BGR frames out.

The Tello sends an H.264 elementary stream as UDP datagrams to port 11111. This
receiver owns that socket and a PyAV decoder. It never writes anything to disk,
so the "no automatic video recording" rule holds by construction rather than by
a flag somebody could forget.

PyAV is imported lazily; without it the rest of the application still runs, and
opening the camera reports which extra to install. Decoding is best effort: a
lost or garbled packet is counted and skipped, and the next keyframe recovers.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import time
from collections.abc import Callable
from types import ModuleType

import numpy as np

from ...errors import HardwareUnavailableError
from ..optional import require_av
from .command_channel import SocketFactory, UdpSocket
from .tello_protocol import TelloSettings

__all__ = ["TelloVideoReceiver"]

_log = logging.getLogger(__name__)

_MAX_PACKETS_PER_READ = 300
"""Cap on packets one :meth:`TelloVideoReceiver.read_frame` call will consume.

A busy stream can carry many packets that do not complete a frame. Without a
cap, one poll could spin for an unbounded time and starve the caller; returning
``None`` asks the caller to poll again, which the frame pump already does.
"""


class TelloVideoReceiver:
    """Socket plus H.264 decoder for the live camera."""

    def __init__(
        self,
        settings: TelloSettings | None = None,
        *,
        socket_factory: SocketFactory = socket.socket,
        av_module: ModuleType | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or TelloSettings()
        self._socket_factory = socket_factory
        self._av = av_module
        self._clock = clock
        self._socket: UdpSocket | None = None
        self._codec = None
        self._last_packet_at: float | None = None
        self._frames_decoded = 0
        self._decode_errors = 0
        self._packets_received = 0
        self._foreign_packets = 0
        self._error = ""
        self._closed = False
        self._first_packet_logged = False
        self._decode_error_logged = False

    # -- inspection ----------------------------------------------------------

    @property
    def last_packet_at(self) -> float | None:
        return self._last_packet_at

    @property
    def frames_decoded(self) -> int:
        return self._frames_decoded

    @property
    def decode_errors(self) -> int:
        return self._decode_errors

    @property
    def packets_received(self) -> int:
        return self._packets_received

    @property
    def foreign_packets(self) -> int:
        """Datagrams dropped because they did not come from the configured host."""
        return self._foreign_packets

    @property
    def error(self) -> str:
        return self._error

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        if self._socket is not None:
            return
        av = self._av or require_av()
        try:
            codec = av.CodecContext.create("h264", "r")
            # Decode on one thread. A UDP camera stream starts mid-GOP and
            # loses packets, so the decoder regularly receives truncated
            # data. PyAV/FFmpeg's slice-threaded H.264 decoder can fault
            # natively on such input (PyAV issue #2344); a native access
            # violation kills the whole application and cannot be caught in
            # Python. 960x720 H.264 still decodes comfortably on one thread.
            # PyAV opens the context on the first ``decode``, so the setting
            # applies without an explicit ``open``.
            codec.thread_count = 1
            codec.thread_type = "NONE"
        except Exception as exc:  # noqa: BLE001 - PyAV raises several types here
            raise HardwareUnavailableError(
                f"PyAV could not create an H.264 decoder: {exc}",
                user_message=(
                    "The H.264 decoder could not be created. Reinstall the hardware "
                    'extra with: pip install -e ".[hardware]"'
                ),
            ) from exc

        sock: UdpSocket | None = None
        try:
            sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.25)
            sock.bind(("", self._settings.local_video_port))
        except OSError as exc:
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.close()
            raise HardwareUnavailableError(
                f"Could not listen for Tello video on UDP "
                f"{self._settings.local_video_port}: {exc}",
                user_message=(
                    f"The Tello video port UDP {self._settings.local_video_port} "
                    f"could not be opened ({exc}). Close other video tools and check "
                    "the firewall, then start the camera again."
                ),
            ) from exc

        self._av = av
        self._codec = codec
        self._socket = sock
        self._closed = False
        self._error = ""
        self._last_packet_at = None
        self._first_packet_logged = False
        self._decode_error_logged = False
        _log.info(
            "Video receiver listening",
            extra={
                "context": {
                    "local_port": self._settings.local_video_port,
                    "expected_host": self._settings.host,
                }
            },
        )

    def close(self) -> None:
        self._closed = True
        sock = self._socket
        self._socket = None
        self._codec = None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()
        _log.info(
            "Video receiver closed",
            extra={
                "context": {
                    "packets_received": self._packets_received,
                    "frames_decoded": self._frames_decoded,
                    "decode_errors": self._decode_errors,
                }
            },
        )

    # -- frames --------------------------------------------------------------

    def read_frame(self) -> np.ndarray | None:
        """Decode pending packets until one frame is produced or the socket idles.

        Returns ``None`` when no frame is available right now. A timeout is
        ordinary: the video stream has gaps, and the caller polls again.
        """
        sock = self._socket
        codec = self._codec
        if sock is None or codec is None:
            return None

        for _ in range(_MAX_PACKETS_PER_READ):
            try:
                payload, sender = sock.recvfrom(65535)
            except TimeoutError:
                return None
            except OSError as exc:
                if self._closed:
                    return None
                if not self._error:
                    _log.warning(
                        "Video receiver socket failed",
                        extra={"context": {"error": str(exc)}},
                    )
                self._error = f"The video socket failed: {exc}"
                return None

            if sender[0] != self._settings.host:
                # Only the configured aircraft's stream is decoded; a datagram
                # from another host is not part of this camera feed.
                self._foreign_packets += 1
                continue

            now = self._clock()
            self._packets_received += 1
            self._last_packet_at = now
            if not self._first_packet_logged:
                self._first_packet_logged = True
                _log.info(
                    "First Tello video packet received",
                    extra={
                        "context": {
                            "sender": sender[0],
                            "bytes": len(payload),
                            "local_port": self._settings.local_video_port,
                        }
                    },
                )
            try:
                packets = codec.parse(payload)
                frames = []
                for packet in packets:
                    frames.extend(codec.decode(packet))
            except Exception as exc:  # noqa: BLE001 - a lost packet must not stop the stream
                self._decode_errors += 1
                if not self._decode_error_logged:
                    self._decode_error_logged = True
                    _log.warning(
                        "Video stream decode error (first one; counted, stream continues)",
                        extra={"context": {"error": str(exc)}},
                    )
                else:
                    _log.debug(
                        "Video packet could not be decoded",
                        extra={"context": {"error": str(exc)}},
                    )
                continue
            if not frames:
                continue
            image = _to_bgr(frames[-1])
            if image is None:
                self._decode_errors += 1
                continue
            self._frames_decoded += 1
            return image
        return None


def _to_bgr(frame: object) -> np.ndarray | None:
    """Convert one PyAV frame to a contiguous uint8 BGR array."""
    try:
        image = frame.to_ndarray(format="bgr24")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - an unknown frame type is a decode failure
        return None
    if not isinstance(image, np.ndarray):
        return None
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        return None
    return np.ascontiguousarray(image)
