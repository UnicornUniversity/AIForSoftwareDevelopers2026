"""Object detection & feedback: advisory-only pursuit rehearsal.

The physical Tello used in class reports a sensor error and refuses takeoff even
from the official application. Its camera still works. This tab uses that
camera (or a local video file) to show an apple, draws a green box around it and
prints the yaw decision the yaw-only tracker *would* make as the apple moves.

It is a rehearsal, not a control surface. It sends only ``streamon`` and
``streamoff`` for the Tello camera, never a flight command, never arms or runs a
dry run, and never records. Every decision line says so.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...container import AppServices
from ...domain import DetectionResult, DetectorKind, Frame
from ...interfaces import ObjectDetector, VideoSource, VideoSourceStatus
from ...pursuit import PursuitAdvisor, PursuitDecision
from ...state import AppStateSnapshot
from ...workers import CallableRunner
from .. import widgets
from ..guidance_overlay import GuidanceRender, action_color, render_guidance
from ..video_session import VideoSession
from ..video_view import VideoView
from ..yolo_settings_dialog import YoloSettingsDialog

__all__ = ["ObjectFeedbackTab"]

_log = logging.getLogger(__name__)

_VIDEO_OWNER = "object_feedback"
_LOG_LINE_LIMIT = 200
_STATUS_MAP = {
    VideoSourceStatus.OFFLINE: ("Offline", "idle"),
    VideoSourceStatus.LIVE: ("Live", "ok"),
    VideoSourceStatus.STALE: ("Stale", "warn"),
    VideoSourceStatus.ENDED: ("Ended", "warn"),
    VideoSourceStatus.ERROR: ("Error", "error"),
}
_MUTED = "color: #5b6470;"
_BANNER_STYLE = (
    "QLabel {{ background-color: {color}; color: white; border-radius: 8px;"
    " padding: 8px 12px; font-weight: 600; }}"
)
_NEUTRAL_BANNER = "No source — choose the Tello camera or a video file."
_FILE_FILTER = "Video files (*.mp4 *.avi *.mov *.mkv *.webm);;All files (*)"


class ObjectFeedbackTab(QWidget):
    """Live video, a green target box and advisory yaw messages only."""

    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
        *,
        source_factory: Callable[[str, str | None], VideoSource] | None = None,
        advisor: PursuitAdvisor | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._advisor = advisor or PursuitAdvisor(
            detector_kind=DetectorKind.YOLO, target_label="apple"
        )
        self._last_path: str | None = None
        self._pending_seq: int | None = None
        self._pending_frame: Frame | None = None
        self._last_frame: Frame | None = None
        self._last_result: DetectionResult | None = None
        self._last_decision: PursuitDecision | None = None
        self._last_guidance: GuidanceRender | None = None
        self._last_logged_message: str | None = None

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

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(500)
        self._health_timer.timeout.connect(self._refresh_health)

        self._build()
        self.refresh_detector_status()
        self._health_timer.start()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(widgets.SectionTitle("Object detection && feedback"))

        notice = QLabel(
            "Advisory only — no command is sent; the aircraft is not flying. This "
            "tab rehearses the yaw-only tracker: show an apple, move it left and "
            "right, and read the decision the tracker would make. It never takes "
            "off, lands, moves or rotates. The only commands it sends are "
            "streamon/streamoff for the Tello camera."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(_MUTED)
        layout.addWidget(notice)

        source_row = QHBoxLayout()
        self._source_combo = QComboBox()
        self._source_combo.addItem("Tello camera", "tello")
        self._source_combo.addItem("Video file…", "file")
        self._source_combo.currentIndexChanged.connect(self._update_controls)
        self._start_button = QPushButton("Start source")
        self._start_button.clicked.connect(self.start_source)
        self._stop_button = QPushButton("Stop source")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self.stop_source)
        self._resume_button = QPushButton("Resume advisories")
        self._resume_button.setEnabled(False)
        self._resume_button.setToolTip(
            "Restart the advisory after it stopped (target lost, stale results or "
            "detector failure). Sends no command."
        )
        self._resume_button.clicked.connect(self.resume_advisories)
        self._loop_check = QCheckBox("Loop video")
        self._loop_check.setChecked(True)
        self._loop_check.setToolTip("Only video files loop; the Tello camera never does.")
        self._settings_button = QPushButton("YOLO settings…")
        self._settings_button.setToolTip(
            "Choose local weights and the target class. The rehearsal follows the "
            "configured class; apple is the default."
        )
        self._settings_button.clicked.connect(self._open_settings)
        source_row.addWidget(self._source_combo)
        source_row.addWidget(self._start_button)
        source_row.addWidget(self._stop_button)
        source_row.addWidget(self._resume_button)
        source_row.addWidget(self._loop_check)
        source_row.addWidget(self._settings_button)
        source_row.addStretch(1)
        layout.addLayout(source_row)

        status_row = QHBoxLayout()
        self._status_pill = widgets.StatusPill("No source")
        self._source_label = QLabel("No source started")
        self._source_label.setStyleSheet(_MUTED)
        status_row.addWidget(self._status_pill)
        status_row.addWidget(self._source_label, 1)
        layout.addLayout(status_row)

        self._banner = QLabel(_NEUTRAL_BANNER)
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(_BANNER_STYLE.format(color="#5b6470"))
        layout.addWidget(self._banner)

        self._preview = VideoView(
            "Start a source, then show an apple to the camera or in the video"
        )
        layout.addWidget(self._preview, 1)

        self._detect_check = QCheckBox("Detect the target class (YOLO)")
        self._detect_check.setChecked(True)
        self._detect_check.setToolTip(
            "Display-only overlay. A detection never arms, moves, takes off or "
            "lands the aircraft."
        )
        layout.addWidget(self._detect_check)

        self._yolo_label = QLabel()
        self._yolo_label.setWordWrap(True)
        self._yolo_label.setStyleSheet(_MUTED)
        layout.addWidget(self._yolo_label)

        self._target_label = QLabel("Target class: apple")
        self._target_label.setStyleSheet(_MUTED)
        layout.addWidget(self._target_label)

        self._age_label = QLabel("No detection yet")
        self._age_label.setStyleSheet(_MUTED)
        layout.addWidget(self._age_label)

        log_title = QLabel("Decision log")
        font = log_title.font()
        font.setBold(True)
        log_title.setFont(font)
        layout.addWidget(log_title)
        self._decision_log = QPlainTextEdit()
        self._decision_log.setReadOnly(True)
        self._decision_log.setMaximumBlockCount(_LOG_LINE_LIMIT)
        self._decision_log.setPlaceholderText(
            "Advisory decisions appear here. Every line says no command is sent."
        )
        self._decision_log.setMinimumHeight(110)
        layout.addWidget(self._decision_log)

        safety = QLabel(
            "Safety: Stop source sends streamoff (Tello) or closes the file; it "
            "never lands. This tab has no flight command, no arming, no dry run "
            "and no recording."
        )
        safety.setWordWrap(True)
        safety.setStyleSheet(_MUTED)
        layout.addWidget(safety)

        self._update_controls()

    # -- source lifecycle ----------------------------------------------------

    def start_source(self) -> bool:
        kind = self._source_combo.currentData()
        if kind == "file":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select a video file",
                self._last_path or "",
                _FILE_FILTER,
            )
            if not path:
                return False
            self._last_path = path
            return self._session.start(
                "file", path, looping=self._loop_check.isChecked()
            )
        return self._session.start("tello")

    def stop_source(self) -> None:
        """Close the source; never sends a flight command."""
        self._session.stop()

    def resume_advisories(self) -> bool:
        """Restart the advisory while the source keeps running.

        Used after a target-loss, stale-result or detector-failure stop. It
        clears the advisor's stop state and sends no command of any kind.
        """
        if not self._session.active or self._advisor.active:
            return False
        decision = self._advisor.start()
        self._last_decision = decision
        self._update_decision(decision)
        return True

    def _on_session_starting(self, kind: str) -> None:
        text = "Starting camera…" if kind == "tello" else "Opening source…"
        self._status_pill.set_status(text, "warn")
        self._update_controls()

    def _on_session_failed(self, title: str, message: str) -> None:
        self._status_pill.set_status("No source", "idle")
        self._update_controls()
        widgets.show_error(self, title, message)

    def _on_source_opened(self, source: VideoSource, kind: str) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._last_frame = None
        self._last_result = None
        self._last_guidance = None
        self._last_logged_message = None
        self._source_label.setText(source.description)
        self._status_pill.set_status("Waiting for video", "warn", source.description)
        self._age_label.setText("No detection yet")
        decision = self._advisor.start()
        self._last_decision = decision
        self._update_decision(decision)
        self._update_controls()

    def _on_source_closed(self) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._preview.clear()
        self._last_frame = None
        self._last_result = None
        self._last_guidance = None
        self._status_pill.set_status("No source", "idle")
        self._source_label.setText("No source started")
        self._age_label.setText("No detection yet")
        decision = self._advisor.stop("Source stopped")
        self._last_decision = decision
        self._show_neutral(_NEUTRAL_BANNER)
        self._update_controls()

    def shutdown(self) -> None:
        """Called by the main window before the application exits."""
        self._health_timer.stop()
        self._session.shutdown()

    # -- frames and detection ------------------------------------------------

    def _on_frame(self, frame: Frame, seq: int | None = None) -> None:
        if not self._session.is_current(seq) or not isinstance(frame, Frame):
            return
        self._last_frame = frame
        self._source_label.setText(
            f"{self._session.source_description or 'Source'} "
            f"— frame {frame.index}, {frame.width}×{frame.height}"
        )
        detector = self._object_detector()
        if detector is None or not self._detect_check.isChecked():
            self._preview.show_frame(frame)
            self._show_neutral(
                "No advisory — a YOLO model is not loaded." if detector is None else
                "No advisory — target detection is switched off."
            )
            return
        if self._analysis_runner.busy:
            # Drop this frame rather than queue a backlog behind slow inference.
            return
        self._pending_seq = self._session.source_seq if seq is None else seq
        self._pending_frame = frame
        if not self._analysis_runner.submit(partial(self._analyze, detector, frame)):
            self._pending_seq = None
            self._pending_frame = None

    @staticmethod
    def _analyze(detector: ObjectDetector, frame: Frame) -> DetectionResult:
        """Worker-thread inference; never touches widgets or the aircraft."""
        return detector.detect(frame)

    def _on_analysis_finished(self, result: object) -> None:
        seq, frame = self._pending_seq, self._pending_frame
        self._pending_seq = None
        self._pending_frame = None
        if seq is None or frame is None or not self._session.is_current(seq):
            return
        if not isinstance(result, DetectionResult):
            return
        self._last_result = result
        decision = self._advisor.process(result)
        self._last_decision = decision
        self._render(frame, result, decision)
        if result.failed:
            _log.warning(
                "Object feedback detection failed",
                extra={"context": {"error": result.error}},
            )

    def _on_analysis_failed(self, message: str) -> None:
        seq, frame = self._pending_seq, self._pending_frame
        self._pending_seq = None
        self._pending_frame = None
        if seq is None or frame is None or not self._session.is_current(seq):
            return
        self._show_neutral(f"Detection failed — {message}. No advisory.")

    def _render(
        self,
        frame: Frame,
        result: DetectionResult,
        decision: PursuitDecision,
    ) -> None:
        image, guidance = render_guidance(frame, result, decision)
        self._last_guidance = guidance
        self._preview.show_image(image)
        self._update_decision(decision)

    def _refresh_health(self) -> None:
        result = self._last_result
        if result is not None:
            age = max(0.0, time.monotonic() - result.processed_at)
            self._age_label.setText(f"Last detection {age:.1f} s ago")
        decision = self._advisor.check_health()
        if self._last_decision is not None and decision is self._last_decision:
            return
        self._last_decision = decision
        frame, result = self._last_frame, self._last_result
        if frame is not None and result is not None:
            self._render(frame, result, decision)
        else:
            self._update_decision(decision)

    def _update_decision(self, decision: PursuitDecision) -> None:
        color = action_color(decision.action)
        self._banner.setText(decision.banner)
        self._banner.setStyleSheet(_BANNER_STYLE.format(color=color))
        self._update_controls()
        if decision.message == self._last_logged_message:
            return
        self._last_logged_message = decision.message
        stamp = time.strftime("%H:%M:%S")
        self._decision_log.appendPlainText(f"{stamp}  {decision.banner}")

    def _show_neutral(self, message: str) -> None:
        if self._banner.text() == message:
            return
        self._banner.setText(message)
        self._banner.setStyleSheet(_BANNER_STYLE.format(color="#5b6470"))

    # -- detector ------------------------------------------------------------

    def _object_detector(self) -> ObjectDetector | None:
        detector = self._services.detectors.get(DetectorKind.YOLO)
        if detector is None or not getattr(detector, "ready", False):
            return None
        if not isinstance(detector, ObjectDetector):
            return None
        return detector

    @staticmethod
    def _configured_label(detector: ObjectDetector) -> str:
        config = getattr(detector, "config", None)
        label = getattr(config, "class_label", "apple")
        return str(label or "apple")

    def refresh_detector_status(self) -> None:
        """Re-read the YOLO slot after settings or a profile load."""
        detector = self._object_detector()
        if detector is None:
            self._yolo_label.setText(
                "YOLO: no model loaded. Open YOLO settings to choose local weights; "
                "without one, live video is shown with no advisory."
            )
            self._target_label.setText("Target class: apple (default)")
            self._detect_check.setEnabled(False)
        else:
            label = self._configured_label(detector)
            self._advisor.set_target_label(label)
            classes = getattr(detector, "available_classes", ())
            detail = f"{len(classes)} classes" if classes else "class list not reported"
            self._yolo_label.setText(f"YOLO: {detector.name} — {detail}.")
            note = (
                ""
                if label == "apple"
                else " — set 'apple' in YOLO settings for the apple rehearsal"
            )
            self._target_label.setText(f"Target class: {label}{note}")
            self._detect_check.setEnabled(True)
        self._update_controls()

    def _open_settings(self) -> None:
        dialog = YoloSettingsDialog(self._services, self._last_frame, self)
        dialog.exec()
        self.refresh_detector_status()

    # -- session signals -----------------------------------------------------

    def _on_status(self, status: VideoSourceStatus, seq: int | None = None) -> None:
        if not self._session.is_current(seq):
            return
        text, level = _STATUS_MAP.get(status, ("Unknown", "idle"))
        self._status_pill.set_status(text, level, self._session.source_description)

    def _on_pump_failed(self, message: str, seq: int | None = None) -> None:
        if not self._session.is_current(seq):
            return
        widgets.show_error(self, "Source failed", message)
        self._session.stop()

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        """Disconnect stops a Tello source; a local file keeps playing.

        The tab never writes safety state, arms anything or sends a command.
        """
        if self._session.kind != "tello" or not self._session.active:
            return
        if snapshot.drone_connected:
            return
        self._session.stop(stop_stream=False)
        self._show_neutral(
            "The aircraft disconnected — advisory stopped. Reconnect on Drone "
            "Control before starting the Tello camera again."
        )
        self._source_label.setText("No source started")

    def _update_controls(self) -> None:
        running = self._session.active
        starting = self._session.busy
        kind = self._source_combo.currentData()
        self._start_button.setEnabled(not running and not starting)
        self._stop_button.setEnabled(running or starting)
        self._resume_button.setEnabled(running and not self._advisor.active)
        self._loop_check.setEnabled(kind == "file")
        if kind == "tello" and self._services.drone_mode != "tello":
            self._start_button.setToolTip(
                "Available only in hardware mode. Start the application with --tello, "
                "or choose a video file."
            )
        else:
            self._start_button.setToolTip(
                "Open the selected source. Sends no flight command."
            )

    # -- accessors used by tests --------------------------------------------

    @property
    def advisor(self) -> PursuitAdvisor:
        return self._advisor

    @property
    def session(self) -> VideoSession:
        return self._session

    @property
    def source(self) -> VideoSource | None:
        return self._session.source

    @property
    def camera_busy(self) -> bool:
        return self._session.busy

    @property
    def analysis_busy(self) -> bool:
        return self._analysis_runner.busy

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def last_result(self) -> DetectionResult | None:
        return self._last_result

    @property
    def last_decision(self) -> PursuitDecision | None:
        return self._last_decision

    @property
    def last_guidance(self) -> GuidanceRender | None:
        return self._last_guidance

    @property
    def source_combo(self) -> QComboBox:
        return self._source_combo

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
    def resume_button(self) -> QPushButton:
        return self._resume_button

    @property
    def detect_check(self) -> QCheckBox:
        return self._detect_check

    @property
    def loop_check(self) -> QCheckBox:
        return self._loop_check

    @property
    def source_label(self) -> QLabel:
        return self._source_label

    @property
    def yolo_label(self) -> QLabel:
        return self._yolo_label

    @property
    def target_label(self) -> QLabel:
        return self._target_label

    @property
    def age_label(self) -> QLabel:
        return self._age_label

    @property
    def banner_label(self) -> QLabel:
        return self._banner

    @property
    def preview(self) -> VideoView:
        return self._preview

    @property
    def status_pill(self) -> widgets.StatusPill:
        return self._status_pill

    @property
    def decision_log(self) -> QPlainTextEdit:
        return self._decision_log
