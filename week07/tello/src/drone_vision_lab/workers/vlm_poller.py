"""Periodic VLM analysis.

The VLM is slow, so it never runs per frame. A timer asks for one analysis per
configured interval, and a second tick while inference is still running is
skipped rather than queued — a backlog of stale answers is worse than no new
answer.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain import DetectionResult, Frame
from ..interfaces import Detector
from .runner import CallableRunner

__all__ = ["VlmPoller"]

_MIN_INTERVAL_MS = 100


class VlmPoller(QObject):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        detector: Detector,
        frame_provider: Callable[[], Frame | None],
        *,
        interval_s: float = 1.0,
        parent: QObject | None = None,
        runner: CallableRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self._detector = detector
        self._frame_provider = frame_provider
        self._runner = runner or CallableRunner(self)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self.set_interval(interval_s)
        self._ticks = 0
        self._skipped = 0

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    @property
    def interval_ms(self) -> int:
        return self._timer.interval()

    @property
    def ticks(self) -> int:
        return self._ticks

    @property
    def skipped(self) -> int:
        return self._skipped

    def set_interval(self, seconds: float) -> None:
        self._timer.setInterval(max(_MIN_INTERVAL_MS, int(round(seconds * 1000.0))))

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> None:
        """One scheduled opportunity to analyze the latest frame."""
        self._ticks += 1
        if self._runner.busy:
            self._skipped += 1
            return
        frame = self._frame_provider()
        if frame is None:
            return
        self._runner.submit(lambda: self._detector.detect(frame))

    def _on_finished(self, result: object) -> None:
        if isinstance(result, DetectionResult):
            self.result_ready.emit(result)

    def _on_failed(self, message: str) -> None:
        self.failed.emit(message)
