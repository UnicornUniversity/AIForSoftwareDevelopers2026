"""One exclusive camera session shared by the video tabs.

The Tello Flight tab and the Object detection & feedback tab both need the same
lifecycle: refuse to start while another tab owns the camera, send ``streamon``
for a Tello source, open the local receiver, decode on a :class:`FramePump` and
release everything on stop. Keeping one implementation means the UDP-11111
protocol and its token handling cannot drift between tabs.

This module owns no widgets. It emits signals; the tab decides what to show.
The only commands it ever sends are ``streamon`` and ``streamoff``.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, Signal

from ..container import AppServices
from ..domain import CommandResult, Frame
from ..interfaces import VideoSource, VideoSourceStatus
from ..workers import CallableRunner, FramePump

__all__ = ["VideoSession"]

_log = logging.getLogger(__name__)

_SOURCE_TELLO = "tello"


class VideoSession(QObject):
    """Exclusive ownership of one camera source at a time."""

    starting = Signal(str)
    opened = Signal(object, str)
    closed = Signal()
    failed = Signal(str, str)
    frame_ready = Signal(object, int)
    status_changed = Signal(object, int)
    pump_failed = Signal(str, int)

    def __init__(
        self,
        services: AppServices,
        *,
        owner: str,
        source_factory: Callable[[str, str | None], VideoSource] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._owner = owner
        self._source_factory = source_factory or services.video_source_factory
        self._source: VideoSource | None = None
        self._pump: FramePump | None = None
        self._kind: str | None = None
        self._source_seq = 0
        self._starting = False
        self._camera_token = 0
        self._submitted_token = 0
        self._closed_emitted = True
        self._stream_stop_thread: threading.Thread | None = None

        self._camera_runner = CallableRunner(self)
        self._camera_runner.finished.connect(self._on_start_finished)
        self._camera_runner.failed.connect(self._on_start_failed)

    # -- inspection ----------------------------------------------------------

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def source(self) -> VideoSource | None:
        return self._source

    @property
    def kind(self) -> str | None:
        return self._kind

    @property
    def source_seq(self) -> int:
        return self._source_seq

    @property
    def active(self) -> bool:
        return self._source is not None

    @property
    def busy(self) -> bool:
        return self._starting or self._camera_runner.busy

    @property
    def source_description(self) -> str:
        source = self._source
        return source.description if source is not None else ""

    def is_current(self, seq: int | None) -> bool:
        return seq is None or seq == self._source_seq

    # -- lifecycle -----------------------------------------------------------

    def start(
        self,
        kind: str,
        path: str | None = None,
        *,
        looping: bool = True,
    ) -> bool:
        """Open a source; returns False when refused or already busy.

        Refusals and open failures are reported through :attr:`failed`.
        """
        if self.active or self.busy:
            return False
        snapshot = self._services.state.snapshot()
        if snapshot.video_active and snapshot.video_owner != self._owner:
            self.failed.emit(
                "Camera",
                "Another tab is using the camera. Stop it there before starting "
                "a source here.",
            )
            return False
        if kind == _SOURCE_TELLO:
            if self._services.drone_mode != "tello":
                self.failed.emit(
                    "Tello camera",
                    "The live Tello camera is available only in hardware mode. "
                    "Start the application with --tello.",
                )
                return False
            if not snapshot.drone_connected:
                self.failed.emit(
                    "Tello camera",
                    "Connect to the Tello on the Drone Control tab first.",
                )
                return False
            self._closed_emitted = False
            self._starting = True
            self._camera_token += 1
            self._submitted_token = self._camera_token
            self.starting.emit(kind)
            if not self._camera_runner.submit(
                self._services.drone.start_video_stream
            ):
                self._starting = False
                self._closed_emitted = True
                return False
            return True

        self._closed_emitted = False
        self.starting.emit(kind)
        return self._open_source(kind, path, looping=looping)

    def stop(self, *, stop_stream: bool = True) -> None:
        """Close the source; never sends a flight command."""
        was_kind = self._kind
        self._source_seq += 1
        self._camera_token += 1
        self._starting = False
        pump, source = self._pump, self._source
        self._pump = None
        self._source = None
        self._kind = None
        if pump is not None:
            pump.stop()
        if source is not None:
            source.close()
        if (
            stop_stream
            and was_kind == _SOURCE_TELLO
            and self._services.drone_mode == "tello"
            and self._services.state.snapshot().drone_connected
        ):
            self._stop_stream_async()
        self._release_ownership()
        self._notify_closed()

    def shutdown(self) -> None:
        """Stop and give ``streamoff`` a bounded chance to be sent."""
        self.stop()
        thread = self._stream_stop_thread
        if thread is not None and thread.is_alive():
            thread.join(2.0)

    # -- streamon ------------------------------------------------------------

    def _on_start_finished(self, result: object) -> None:
        self._starting = False
        if self._submitted_token != self._camera_token:
            # The operator pressed Stop while streamon was in flight. Do not
            # open the camera now; if the aircraft acknowledged anyway, turn the
            # stream back off.
            if isinstance(result, CommandResult) and result.ok:
                self._stop_stream_async()
            self._notify_closed()
            return
        if not isinstance(result, CommandResult):
            self._notify_closed()
            return
        if not result.ok:
            self.failed.emit(
                "Tello camera",
                result.detail or "The aircraft did not acknowledge streamon.",
            )
            self._notify_closed()
            return
        self._open_source(_SOURCE_TELLO, None, looping=False)

    def _on_start_failed(self, message: str) -> None:
        self._starting = False
        if self._submitted_token != self._camera_token:
            self._notify_closed()
            return
        self.failed.emit("Tello camera", message)
        self._notify_closed()

    # -- source --------------------------------------------------------------

    def _open_source(self, kind: str, path: str | None, *, looping: bool) -> bool:
        self._source_seq += 1
        seq = self._source_seq
        try:
            source = self._source_factory(kind, path)
            source.open()
            source.set_looping(looping)
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            _log.exception(
                "Could not open video source", extra={"context": {"kind": kind}}
            )
            if kind == _SOURCE_TELLO:
                self._stop_stream_async()
            self.failed.emit("Video source", str(exc))
            self._release_ownership()
            self._notify_closed()
            return False

        pump = FramePump(source, target_fps=30.0, parent=self)
        pump.frame_ready.connect(partial(self._relay_frame, seq=seq))
        pump.status_changed.connect(partial(self._relay_status, seq=seq))
        pump.failed.connect(partial(self._relay_failure, seq=seq))

        self._source = source
        self._pump = pump
        self._kind = kind
        self._services.state.update(
            video_active=True,
            video_source_type=kind,
            video_owner=self._owner,
        )
        self._closed_emitted = False
        self.opened.emit(source, kind)
        pump.start()
        return True

    def _relay_frame(self, frame: object, *, seq: int) -> None:
        if not self.is_current(seq) or not isinstance(frame, Frame):
            return
        self.frame_ready.emit(frame, seq)

    def _relay_status(self, status: object, *, seq: int) -> None:
        if not self.is_current(seq):
            return
        if isinstance(status, VideoSourceStatus):
            self.status_changed.emit(status, seq)

    def _relay_failure(self, message: str, *, seq: int) -> None:
        if not self.is_current(seq):
            return
        self.pump_failed.emit(message, seq)

    # -- internals -----------------------------------------------------------

    def _release_ownership(self) -> None:
        if self._services.state.snapshot().video_owner == self._owner:
            self._services.state.update(
                video_active=False,
                video_source_type=None,
                video_owner=None,
            )

    def _notify_closed(self) -> None:
        if self._closed_emitted:
            return
        self._closed_emitted = True
        self.closed.emit()

    def _stop_stream_async(self) -> None:
        """Send ``streamoff`` without blocking the GUI or close path."""
        drone = self._services.drone
        previous = self._stream_stop_thread
        if previous is not None and previous.is_alive():
            previous.join(0.5)

        def _run() -> None:
            try:
                drone.stop_video_stream()
            except Exception:  # noqa: BLE001 - best effort while shutting down
                _log.warning("Could not stop the video stream", exc_info=True)

        thread = threading.Thread(
            target=_run, name=f"{self._owner}-streamoff", daemon=True
        )
        self._stream_stop_thread = thread
        thread.start()
