"""Tello Flight: live aircraft camera with all-class object detection.

This is the second consumer of the Tello camera, so it owns the video source
exclusively while it runs; the Computer Vision Lab refuses to start a source
until this tab stops. The tab sends only ``streamon`` and ``streamoff`` — it
never takes off, lands, moves, records video or feeds a detection into flight
control. Boxes and class titles are drawn for the operator to read.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...container import AppServices
from ...domain import DetectionResult, DetectorKind, Frame
from ...interfaces import ObjectDetector, VideoSource, VideoSourceStatus
from ...state import AppStateSnapshot
from ...workers import CallableRunner
from .. import widgets
from ..detection_overlay import render_frame
from ..video_session import VideoSession
from ..video_view import VideoView
from ..yolo_settings_dialog import YoloSettingsDialog

__all__ = ["TelloFlightTab"]

_log = logging.getLogger(__name__)

_VIDEO_OWNER = "tello_flight"
_DETECTION_LINE_LIMIT = 8
_STATUS_MAP = {
    VideoSourceStatus.OFFLINE: ("Offline", "idle"),
    VideoSourceStatus.LIVE: ("Live", "ok"),
    VideoSourceStatus.STALE: ("Stale", "warn"),
    VideoSourceStatus.ENDED: ("Ended", "warn"),
    VideoSourceStatus.ERROR: ("Error", "error"),
}


class TelloFlightTab(QWidget):
    """Operator view: live Tello camera plus YOLO boxes for every class."""

    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
        *,
        source_factory: Callable[[str, str | None], VideoSource] | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._pending_seq: int | None = None
        self._pending_frame: Frame | None = None
        self._last_frame: Frame | None = None
        self._last_result: DetectionResult | None = None

        self._session = VideoSession(
            services,
            owner=_VIDEO_OWNER,
            source_factory=source_factory,
            parent=self,
        )
        self._session.starting.connect(self._on_session_starting)
        self._session.opened.connect(self._on_source_opened)
        self._session.closed.connect(self._on_source_closed)
        self._session.failed.connect(self._on_session_failed)
        self._session.frame_ready.connect(self._on_frame)
        self._session.status_changed.connect(self._on_status)
        self._session.pump_failed.connect(self._on_pump_failed)

        self._analysis_runner = CallableRunner(self)
        self._analysis_runner.finished.connect(self._on_analysis_finished)
        self._analysis_runner.failed.connect(self._on_analysis_failed)

        self._age_timer = QTimer(self)
        self._age_timer.setInterval(500)
        self._age_timer.timeout.connect(self._refresh_age)

        self._build()
        self.refresh_detector_status()
        self._age_timer.start()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(widgets.SectionTitle("Tello Flight"))

        note = QLabel(
            "Live video from the aircraft, with YOLO marking every recognized object "
            "and naming its class. This view sends only the camera stream commands, "
            "never a flight command; detections are display-only and nothing is "
            "recorded. The Computer Vision Lab cannot use the camera while this tab "
            "is streaming."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5b6470;")
        layout.addWidget(note)

        status_row = QHBoxLayout()
        self._status_pill = widgets.StatusPill("No camera")
        self._source_label = QLabel("Tello camera — not started")
        self._source_label.setStyleSheet("color: #5b6470;")
        status_row.addWidget(self._status_pill)
        status_row.addWidget(self._source_label, 1)
        layout.addLayout(status_row)

        self._preview = VideoView("Start the Tello camera to see live video")
        layout.addWidget(self._preview, 1)

        controls = QHBoxLayout()
        self._start_button = QPushButton("Start Tello camera")
        self._start_button.clicked.connect(self.start_camera)
        self._stop_button = QPushButton("Stop camera")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self.stop_camera)
        self._settings_button = QPushButton("YOLO settings…")
        self._settings_button.setToolTip(
            "Choose local weights. Tello Flight draws every class the model knows."
        )
        self._settings_button.clicked.connect(self._open_settings)
        controls.addWidget(self._start_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._settings_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._detect_check = QCheckBox("Mark recognized objects (YOLO)")
        self._detect_check.setChecked(True)
        self._detect_check.setToolTip(
            "Display-only overlay. A detection never arms, moves, takes off or lands "
            "the aircraft."
        )
        layout.addWidget(self._detect_check)

        self._yolo_label = QLabel()
        self._yolo_label.setWordWrap(True)
        self._yolo_label.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._yolo_label)

        self._summary_label = QLabel("No camera. Start the Tello camera to analyze frames.")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._age_label = QLabel("No detection yet")
        self._age_label.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._age_label)

        safety = QLabel(
            "Safety: this tab does not take off, land, move or record. Stop camera "
            "sends streamoff; it does not land. Emergency Land stays in the top bar."
        )
        safety.setWordWrap(True)
        safety.setStyleSheet("color: #5b6470;")
        layout.addWidget(safety)

        self._update_controls()

    # -- camera lifecycle ----------------------------------------------------

    def start_camera(self) -> bool:
        """Ask the aircraft for its stream, then open the receiver.

        Nothing starts automatically: this runs only from the operator's click.
        The sequence is streamon first, then the local UDP receiver, because the
        stream exists only after the aircraft acknowledges the command.
        """
        return self._session.start("tello")

    def _on_session_starting(self, kind: str) -> None:
        self._status_pill.set_status(
            "Starting…", "warn", "Sending streamon; the camera opens after the acknowledgement."
        )
        self._update_controls()

    def _on_session_failed(self, title: str, message: str) -> None:
        self._status_pill.set_status("No camera", "idle")
        self._update_controls()
        widgets.show_error(self, title, message)

    def _on_source_opened(self, source: VideoSource, kind: str) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._last_frame = None
        self._last_result = None
        self._age_label.setText("No detection yet")
        self._summary_label.setText("Waiting for a frame to analyze…")
        self._source_label.setText(source.description)
        self._status_pill.set_status("Waiting for video", "warn", source.description)
        self._update_controls()

    def _on_source_closed(self) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._preview.clear()
        self._last_frame = None
        self._last_result = None
        self._status_pill.set_status("No camera", "idle")
        self._source_label.setText("Tello camera — not started")
        self._summary_label.setText("No camera. Start the Tello camera to analyze frames.")
        self._age_label.setText("No detection yet")
        self._update_controls()

    def stop_camera(self, *, stop_stream: bool = True) -> None:
        """Close the receiver and, when connected, ask the aircraft to stop.

        Stopping the camera never lands or moves the aircraft. ``streamoff`` is
        best effort and runs off the GUI thread.
        """
        self._session.stop(stop_stream=stop_stream)

    def shutdown(self) -> None:
        """Called by the main window before the application exits."""
        self._age_timer.stop()
        self._session.shutdown()

    # -- pump signals --------------------------------------------------------

    def _is_current(self, seq: int | None) -> bool:
        return self._session.is_current(seq)

    def _on_frame(self, frame: Frame, seq: int | None = None) -> None:
        if not self._is_current(seq) or not isinstance(frame, Frame):
            return
        self._last_frame = frame
        self._source_label.setText(
            f"{self._session.source_description or 'Tello camera'} "
            f"— frame {frame.index}, {frame.width}×{frame.height}"
        )

        detector = self._object_detector()
        if detector is None or not self._detect_check.isChecked():
            # No model or the operator turned the overlay off: show live video.
            self._preview.show_frame(frame)
            return
        if self._last_result is None:
            self._preview.show_frame(frame)
        if self._analysis_runner.busy:
            # Drop this frame rather than queueing a backlog behind slow inference.
            return
        # ``seq=None`` means the call did not come from the pump (tests and
        # direct calls); tag it with the live generation so the answer is kept.
        self._pending_seq = self._session.source_seq if seq is None else seq
        self._pending_frame = frame
        if not self._analysis_runner.submit(partial(self._analyze, detector, frame)):
            self._pending_seq = None
            self._pending_frame = None

    @staticmethod
    def _analyze(detector: ObjectDetector, frame: Frame) -> DetectionResult:
        """Worker-thread inference; never touches widgets or the aircraft."""
        return detector.detect_all_classes(frame)

    def _on_status(self, status: VideoSourceStatus, seq: int | None = None) -> None:
        if not self._is_current(seq):
            return
        text, level = _STATUS_MAP.get(status, ("Unknown", "idle"))
        self._status_pill.set_status(text, level, self._session.source_description)

    def _on_pump_failed(self, message: str, seq: int | None = None) -> None:
        if not self._is_current(seq):
            return
        widgets.show_error(self, "Tello camera failed", message)
        self.stop_camera()

    # -- detection -----------------------------------------------------------

    def _on_analysis_finished(self, result: object) -> None:
        seq, frame = self._pending_seq, self._pending_frame
        self._pending_seq = None
        self._pending_frame = None
        if seq is None or frame is None or not self._is_current(seq):
            # The camera stopped while inference was running; the answer belongs
            # to a source that no longer exists.
            return
        if not isinstance(result, DetectionResult):
            return
        self._last_result = result
        self._render_result(frame, result)

    def _on_analysis_failed(self, message: str) -> None:
        seq, frame = self._pending_seq, self._pending_frame
        self._pending_seq = None
        self._pending_frame = None
        if seq is None or frame is None or not self._is_current(seq):
            return
        self._summary_label.setText(f"Detection failed — {message}")

    def _render_result(self, frame: Frame, result: DetectionResult) -> None:
        self._preview.show_image(render_frame(frame, {DetectorKind.YOLO: result}))
        self._summary_label.setText(_summarize(result))
        if result.failed:
            _log.warning(
                "Tello Flight detection failed",
                extra={"context": {"error": result.error}},
            )

    def _refresh_age(self) -> None:
        result = self._last_result
        if result is None:
            return
        age = max(0.0, time.monotonic() - result.processed_at)
        self._age_label.setText(f"Last detection {age:.1f} s ago")

    def _object_detector(self) -> ObjectDetector | None:
        detector = self._services.detectors.get(DetectorKind.YOLO)
        if detector is None or not getattr(detector, "ready", False):
            return None
        if not isinstance(detector, ObjectDetector):
            return None
        return detector

    def refresh_detector_status(self) -> None:
        """Re-read the YOLO slot after settings or a profile load."""
        detector = self._object_detector()
        if detector is None:
            self._yolo_label.setText(
                "YOLO: no model loaded. Open YOLO settings to choose local weights; "
                "without one, live video is shown without boxes."
            )
            self._detect_check.setEnabled(False)
        else:
            classes = getattr(detector, "available_classes", ())
            count = len(classes)
            detail = f"{count} classes" if count else "class list not reported"
            self._yolo_label.setText(
                f"YOLO: {detector.name} — {detail}. Every recognized class is drawn; "
                "the Vision Lab target-class setting does not limit this view."
            )
            self._detect_check.setEnabled(True)
        self._update_controls()

    def _open_settings(self) -> None:
        dialog = YoloSettingsDialog(self._services, self._last_frame, self)
        dialog.exec()
        self.refresh_detector_status()

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        if self._session.active and not snapshot.drone_connected:
            self.stop_camera(stop_stream=False)
            self._status_pill.set_status("Tello disconnected — camera stopped", "error")
            self._source_label.setText("Tello camera — not started")
            self._summary_label.setText(
                "The connection to the aircraft was lost, so live video stopped. "
                "Reconnect before starting the camera again."
            )
        self._update_controls()

    def _update_controls(self) -> None:
        running = self._session.active
        starting = self._session.busy
        self._start_button.setEnabled(not running and not starting)
        self._stop_button.setEnabled(running or starting)
        if self._services.drone_mode != "tello":
            self._start_button.setToolTip(
                "Available only in hardware mode. Start the application with --tello."
            )
        else:
            self._start_button.setToolTip(
                "Send streamon and open the Tello camera. Sends no flight command."
            )

    # -- accessors used by tests --------------------------------------------

    @property
    def source(self) -> VideoSource | None:
        return self._session.source

    @property
    def session(self) -> VideoSession:
        return self._session

    @property
    def camera_busy(self) -> bool:
        return self._session.busy

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def last_result(self) -> DetectionResult | None:
        return self._last_result

    @property
    def start_button(self) -> QPushButton:
        return self._start_button

    @property
    def stop_button(self) -> QPushButton:
        return self._stop_button

    @property
    def settings_button(self) -> QPushButton:
        return self._settings_button

    @property
    def detect_check(self) -> QCheckBox:
        return self._detect_check

    @property
    def status_label(self) -> QLabel:
        return self._summary_label

    @property
    def summary_label(self) -> QLabel:
        return self._summary_label

    @property
    def age_label(self) -> QLabel:
        return self._age_label

    @property
    def yolo_label(self) -> QLabel:
        return self._yolo_label

    @property
    def preview(self) -> VideoView:
        return self._preview

    @property
    def status_pill(self) -> widgets.StatusPill:
        return self._status_pill


def _summarize(result: DetectionResult) -> str:
    """One honest line: failure, or every class with its own confidence."""
    latency = (
        f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "time not reported"
    )
    if result.failed:
        return f"Detection failed — {result.error}"
    if not result.detections:
        return f"No objects recognized — {latency}"

    ordered = sorted(
        result.detections,
        key=lambda detection: (
            detection.confidence if detection.confidence is not None else -1.0
        ),
        reverse=True,
    )
    shown = []
    for detection in ordered[:_DETECTION_LINE_LIMIT]:
        score = f" ({detection.confidence:.2f})" if detection.confidence is not None else ""
        shown.append(f"{detection.label}{score}")
    remaining = len(ordered) - _DETECTION_LINE_LIMIT
    more = f", +{remaining} more" if remaining > 0 else ""
    return f"{len(result.detections)} object(s) — {latency} — " + ", ".join(shown) + more
