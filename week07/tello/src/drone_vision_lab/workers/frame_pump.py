"""Frame delivery worker.

Pulls frames from a video source on a background thread and hands them to the
GUI thread through Qt signals. Decoding never runs on the Qt main thread.

The thread is a plain ``threading.Thread`` emitting from a ``QObject`` that
lives in the GUI thread, so Qt delivers frames queued — no widgets are touched
from the worker.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from ..domain import Frame
from ..interfaces.video import VideoSource, VideoSourceStatus

__all__ = ["FramePump"]

_log = logging.getLogger(__name__)


class FramePump(QObject):
    """Continuously reads frames until stopped, paused or the source ends."""

    frame_ready = Signal(object)
    status_changed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source: VideoSource,
        *,
        target_fps: float = 30.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")
        self._source = source
        self._interval = 1.0 / target_fps
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status: VideoSourceStatus | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="drone-vision-frame-pump", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def pump_once(self) -> Frame | None:
        """Read and emit exactly one frame. Exposed for deterministic tests."""
        try:
            frame = self._source.read()
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator
            _log.exception("Video source failed while reading a frame")
            self.failed.emit(str(exc))
            self._stop_event.set()
            return None

        self._emit_status()
        if frame is None:
            return None
        self.frame_ready.emit(frame)
        return frame

    # -- internals -----------------------------------------------------------

    def _emit_status(self) -> None:
        status = self._source.status
        if status is not self._last_status:
            self._last_status = status
            self.status_changed.emit(status)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            frame = self.pump_once()
            if self._stop_event.is_set():
                break
            if frame is None:
                status = self._source.status
                if status in (
                    VideoSourceStatus.ENDED,
                    VideoSourceStatus.ERROR,
                    VideoSourceStatus.OFFLINE,
                ):
                    break
                self._stop_event.wait(min(0.1, self._interval))
                continue
            remaining = self._interval - (time.monotonic() - started)
            if remaining > 0:
                self._stop_event.wait(remaining)
