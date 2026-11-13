"""Bridge between the thread-safe state store and Qt widgets.

The store may be updated from any thread; this object re-emits changes as a Qt
signal so widgets always receive them on the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ..state import AppStateSnapshot, AppStateStore

__all__ = ["StateBridge"]


class StateBridge(QObject):
    changed = Signal(object)

    def __init__(self, store: AppStateStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._detach: Callable[[], None] | None = store.subscribe(self._emit_changed)

    def _emit_changed(self, snapshot: AppStateSnapshot) -> None:
        # Emitting a signal is thread-safe; the connection is resolved on the
        # receiver's thread, which is the GUI thread for every consumer.
        self.changed.emit(snapshot)

    def snapshot(self) -> AppStateSnapshot:
        return self._store.snapshot()

    def close(self) -> None:
        if self._detach is not None:
            self._detach()
            self._detach = None
