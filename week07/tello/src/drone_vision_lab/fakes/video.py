"""Synthetic video source.

Produces a moving coloured square on a gradient background, so the UI, the
OpenCV demo path and the tests have frames to work with long before a real
video file or a Tello camera is available. Nothing is ever written to disk.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from ..domain import Frame
from ..errors import HardwareUnavailableError
from ..interfaces.video import VideoSourceState, VideoSourceStatus

__all__ = ["SyntheticVideoSource"]


class SyntheticVideoSource:
    """A pull-based, in-memory frame generator."""

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        source_id: str = "synthetic",
        fail_on_open: bool = False,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        if fps <= 0:
            raise ValueError("fps must be positive")
        self._lock = threading.Lock()
        self._width = width
        self._height = height
        self._fps = fps
        self._source_id = source_id
        self._fail_on_open = fail_on_open
        self._state = VideoSourceState.CLOSED
        self._index = 0
        self._looping = True
        self._seek_to: int | None = None
        self._background = self._make_background()

    # -- VideoSource ---------------------------------------------------------

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def state(self) -> VideoSourceState:
        with self._lock:
            return self._state

    @property
    def status(self) -> VideoSourceStatus:
        with self._lock:
            return {
                VideoSourceState.CLOSED: VideoSourceStatus.OFFLINE,
                VideoSourceState.OPENING: VideoSourceStatus.OFFLINE,
                VideoSourceState.READY: VideoSourceStatus.LIVE,
                VideoSourceState.PAUSED: VideoSourceStatus.STALE,
                VideoSourceState.ENDED: VideoSourceStatus.ENDED,
                VideoSourceState.ERROR: VideoSourceStatus.ERROR,
            }[self._state]

    @property
    def description(self) -> str:
        return f"Simulated camera {self._width}x{self._height} @ {self._fps:g} fps"

    def open(self) -> None:
        if self._fail_on_open:
            with self._lock:
                self._state = VideoSourceState.ERROR
            raise HardwareUnavailableError(
                "The simulated video source was configured to fail",
                user_message="The video source could not be opened.",
            )
        with self._lock:
            self._state = VideoSourceState.READY
            self._index = 0

    def close(self) -> None:
        with self._lock:
            self._state = VideoSourceState.CLOSED

    def read(self) -> Frame | None:
        with self._lock:
            if self._state is not VideoSourceState.READY:
                return None
            if self._seek_to is not None:
                self._index = self._seek_to
                self._seek_to = None
            index = self._index
            self._index += 1
        return Frame(
            image=self._render(index),
            captured_at=time.monotonic(),
            source_id=self._source_id,
            index=index,
        )

    def pause(self) -> None:
        with self._lock:
            if self._state is VideoSourceState.READY:
                self._state = VideoSourceState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self._state is VideoSourceState.PAUSED:
                self._state = VideoSourceState.READY

    def seek(self, position_seconds: float) -> bool:
        if position_seconds < 0:
            return False
        with self._lock:
            self._seek_to = int(position_seconds * self._fps)
            return True

    def set_looping(self, looping: bool) -> None:
        with self._lock:
            self._looping = looping

    # -- rendering -----------------------------------------------------------

    def _make_background(self) -> np.ndarray:
        ramp = np.linspace(40, 90, self._width, dtype=np.uint8)
        bg = np.empty((self._height, self._width, 3), dtype=np.uint8)
        bg[:, :, 0] = ramp
        bg[:, :, 1] = np.linspace(30, 70, self._height, dtype=np.uint8)[:, None]
        bg[:, :, 2] = 80
        return bg

    def _render(self, index: int) -> np.ndarray:
        image = self._background.copy()
        size = 80
        period = max(1, self._width - size)
        x = (index * 6) % period
        y = self._height // 2 - size // 2
        # BGR green-ish square, roughly the tennis-ball colour the lab calibrates on.
        image[y : y + size, x : x + size] = (60, 210, 200)
        return image
