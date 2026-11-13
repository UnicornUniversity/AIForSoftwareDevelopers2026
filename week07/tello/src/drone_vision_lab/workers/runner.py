"""One-shot background jobs.

Detectors run on the Qt thread pool so the GUI thread never does inference or
image processing. A runner keeps at most one job in flight: a slow detector
must not build an unbounded backlog, it must drop frames instead.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, SignalInstance

__all__ = ["CallableRunner"]

_log = logging.getLogger(__name__)


class _Job(QRunnable):
    def __init__(self, fn, signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            _log.exception("Background job failed")
            self._emit(self._signals.failed, str(exc))
            return
        self._emit(self._signals.finished, result)

    @staticmethod
    def _emit(signal: SignalInstance, payload: object) -> None:
        try:
            signal.emit(payload)
        except RuntimeError:
            # The widget that owned the runner closed before the job finished,
            # so nobody is listening any more. Dropping the result is correct.
            _log.debug("Dropped a worker result: its receiver was destroyed")


class _Signals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class CallableRunner(QObject):
    """Runs one callable at a time on the global thread pool."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        # Deliberately parentless. A job keeps its own reference, so a result
        # can still be emitted after the widget that owned this runner has been
        # destroyed; Qt then has no receiver left and simply drops it. Making
        # the signals a child here would delete the signal source in the middle
        # of a job (RuntimeError: Signal source has been deleted).
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._busy = threading.Event()

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def submit(self, fn) -> bool:
        """Queue ``fn``; returns False when a job is already running."""
        if self._busy.is_set():
            return False
        self._busy.set()
        self._pool.start(_Job(fn, self._signals))
        return True

    def _on_finished(self, result: object) -> None:
        self._busy.clear()
        self.finished.emit(result)

    def _on_failed(self, message: str) -> None:
        self._busy.clear()
        self.failed.emit(message)
