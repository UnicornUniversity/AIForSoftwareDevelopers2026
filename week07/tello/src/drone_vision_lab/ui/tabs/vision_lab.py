"""Computer Vision Lab tab.

One frame source feeds three detectors. OpenCV and YOLO run on the same frame
in one background job, so a comparison is a comparison and not two moments
stuck together; the VLM runs periodically on its own timer and its result is
labelled with its age.

The guided workflow is source → configuration/calibration → dry run → ready.
Only a successful dry run of OpenCV or YOLO can unlock autonomous tracking
(phase 10); the VLM is advisory and never unlocks anything.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...adapters.vision import OpenCvTargetDetector, YoloDetector
from ...adapters.vlm import OllamaVlmDetector
from ...config import CONSERVATIVE_LIMITS, videos_dir
from ...container import AppServices
from ...domain import CommandResult, CommandStatus, DetectionResult, DetectorKind, Frame
from ...interfaces import VideoSource, VideoSourceState, VideoSourceStatus
from ...safety import InvalidTransition, SafetyStateMachine
from ...state import AppStateSnapshot, SafetyState
from ...tracking import (
    TrackingCommand,
    TrackingController,
    TrackingSettings,
    TrackingUpdate,
)
from ...workers import FramePump, VlmPoller
from ...workers.runner import CallableRunner
from .. import widgets
from ..calibration_dialog import CalibrationDialog
from ..detection_overlay import DISPLAY_NAMES, confidence_text, render_frame
from ..profile_store import store_profile_section_if_active, utc_timestamp
from ..video_view import VideoView
from ..vlm_settings_dialog import VlmSettingsDialog
from ..yolo_settings_dialog import YoloSettingsDialog

__all__ = ["VisionLabTab"]

_log = logging.getLogger(__name__)

_MODE_LABELS = (
    (DetectorKind.OPENCV, "OpenCV"),
    (DetectorKind.YOLO, "YOLO"),
    (DetectorKind.VLM, "VLM"),
    ("comparison", "Comparison"),
)
_RESULT_KINDS = (DetectorKind.OPENCV, DetectorKind.YOLO, DetectorKind.VLM)
_FRAME_KINDS = (DetectorKind.OPENCV, DetectorKind.YOLO)

_STATUS_MAP = {
    VideoSourceStatus.OFFLINE: ("No source", "idle"),
    VideoSourceStatus.LIVE: ("Live", "ok"),
    VideoSourceStatus.STALE: ("Paused", "warn"),
    VideoSourceStatus.ENDED: ("Ended", "warn"),
    VideoSourceStatus.ERROR: ("Error", "error"),
}

_ROW_HEADERS = ("Algorithm", "Status", "Latency", "Confidence", "Result age", "Detail")
_MUTED = "color: #5b6470;"
_VIDEO_OWNER = "vision_lab"
_TRACKING_SETTINGS = TrackingSettings(
    session_limit_s=CONSERVATIVE_LIMITS.max_tracking_session_s
)


class _ResultRow:
    """Labels for one algorithm in the results table."""

    def __init__(self, grid: QGridLayout, row: int, kind: DetectorKind) -> None:
        self.kind = kind
        self.algorithm = QLabel(DISPLAY_NAMES[kind])
        self.algorithm.setStyleSheet(f"font-weight: 600; {_MUTED}")
        self.status = QLabel("Idle")
        self.latency = QLabel("—")
        self.confidence = QLabel("—")
        self.age = QLabel("—")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        for column, label in enumerate(
            (self.algorithm, self.status, self.latency, self.confidence, self.age, self.detail)
        ):
            grid.addWidget(label, row, column)
        grid.setColumnStretch(5, 1)

    def set_status(self, text: str, level: str) -> None:
        colors = {"ok": "#2f6f44", "warn": "#b26a00", "error": "#a12a2a", "idle": "#5b6470"}
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colors.get(level, '#5b6470')}; font-weight: 600;")

    def clear_values(self) -> None:
        self.latency.setText("—")
        self.confidence.setText("—")
        self.age.setText("—")
        self.detail.setText("")


class VisionLabTab(QWidget):
    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._source: VideoSource | None = None
        self._pump: FramePump | None = None
        # Bumped whenever the source is replaced. Signals and worker results
        # carry the generation they belong to, so a frame queued just before a
        # stop cannot repaint the preview of the next (or no) source.
        self._source_seq = 0
        self._analysis_seq = 0
        self._dry_run_seq = 0
        self._last_path: str | None = None
        self._current_kind: str | None = None
        self._updating_source = False
        self._last_frame: Frame | None = None
        self._mode: DetectorKind | str = DetectorKind.OPENCV
        self._results: dict[DetectorKind, DetectionResult] = {}
        self._dropped_frames = 0
        self._vlm_poller: VlmPoller | None = None
        self._vlm_poller_detector: OllamaVlmDetector | None = None
        self._safety = SafetyStateMachine(services.state)
        self._tracking: TrackingController | None = None
        self._tracking_alert = ""
        self._last_tracking_refresh = 0.0

        self._hardware = services.drone_mode == "tello"
        self._analysis_runner = CallableRunner(self)
        self._analysis_runner.finished.connect(self._on_analysis_finished)
        self._analysis_runner.failed.connect(self._on_analysis_failed)
        self._camera_runner = CallableRunner(self)
        self._camera_runner.finished.connect(self._on_camera_command_finished)
        self._camera_runner.failed.connect(self._on_camera_command_failed)
        # A ``streamon`` is in flight off the GUI thread. Bump the token when the
        # operator stops the source, so a late acknowledgement cannot open a
        # camera the operator has already dismissed.
        self._camera_token = 0
        self._submitted_camera_token = 0
        self._tracking_runner = CallableRunner(self)
        self._tracking_runner.finished.connect(self._on_tracking_command_finished)
        self._tracking_runner.failed.connect(self._on_tracking_command_failed)
        self._land_runner = CallableRunner(self)
        self._land_runner.finished.connect(self._on_tracking_land_finished)
        self._land_runner.failed.connect(self._on_tracking_land_failed)
        self._tracking_timer = QTimer(self)
        self._tracking_timer.setInterval(200)
        self._tracking_timer.timeout.connect(self._on_tracking_tick)
        self._stream_stop_thread: threading.Thread | None = None
        self._dry_runner = CallableRunner(self)
        self._dry_runner.finished.connect(self._on_dry_run_finished)
        self._dry_runner.failed.connect(self._on_dry_run_failed)
        self._dry_run_pending = False

        self._build()
        self._refresh_yolo_status()
        self._refresh_vlm_status()
        self.apply_state(services.state.snapshot())

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(widgets.SectionTitle("Computer Vision Lab"))
        intro = QLabel(
            "Compare classic colour thresholding, object detection and a vision-language "
            "model on exactly the same frames. VLM output is advisory and never controls "
            "the aircraft."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(_MUTED)
        layout.addWidget(intro)

        layout.addWidget(self._build_source_group())
        layout.addWidget(self._build_preview(), 1)
        layout.addWidget(self._build_transport_row())
        layout.addWidget(self._build_mode_group())
        layout.addWidget(self._build_results_group())
        layout.addWidget(self._build_workflow_row())
        layout.addWidget(self._build_tracking_group())

    def _build_source_group(self) -> QWidget:
        group = QGroupBox("Source")
        row = QHBoxLayout(group)

        self._source_combo = QComboBox()
        # A real placeholder, not a pre-selected first item: Qt selects the first
        # item automatically, and re-selecting it emits no change, so the source
        # would never start and Dry run would stay disabled on first use.
        self._source_combo.addItem("Select a source…", userData=None)
        self._source_combo.addItem("Simulated camera (synthetic)", userData="synthetic")
        self._source_combo.addItem("Simulation video file", userData="file")
        self._source_combo.addItem(
            "Tello camera"
            if self._hardware
            else "Tello camera (start with DRONE_VISION_LAB_DRONE=tello)",
            userData="tello",
        )
        index = self._source_combo.findData("tello")
        model = self._source_combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(index)
            if item is not None:
                item.setEnabled(self._hardware)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)

        self._load_button = QPushButton("Load video…")
        self._load_button.clicked.connect(self._on_load_video)

        row.addWidget(QLabel("Input"))
        row.addWidget(self._source_combo, 1)
        row.addWidget(self._load_button)
        return group

    def _build_preview(self) -> QWidget:
        self._preview = VideoView("No video source loaded")
        return self._preview

    def _build_transport_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self._play_button = QPushButton("Pause")
        self._play_button.setEnabled(False)
        self._play_button.clicked.connect(self._toggle_pause)

        self._stop_button = QPushButton("Stop")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self.stop_source)

        self._loop_check = QCheckBox("Loop")
        self._loop_check.toggled.connect(self._on_loop_toggled)

        self._status_pill = widgets.StatusPill("No source")
        self._frame_label = QLabel("")
        self._frame_label.setStyleSheet(_MUTED)

        layout.addWidget(self._play_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._loop_check)
        layout.addWidget(self._status_pill)
        layout.addWidget(self._frame_label)
        layout.addStretch(1)
        return row

    def _build_mode_group(self) -> QWidget:
        group = QGroupBox("Vision mode")
        row = QHBoxLayout(group)
        self._mode_group = QButtonGroup(self)
        self._mode_radios: dict[object, QRadioButton] = {}
        for mode, label in _MODE_LABELS:
            radio = QRadioButton(label)
            radio.setToolTip(_mode_tooltip(mode))
            radio.toggled.connect(
                lambda checked, value=mode: self._on_mode_changed(value) if checked else None
            )
            self._mode_group.addButton(radio)
            self._mode_radios[mode] = radio
            row.addWidget(radio)
        self._mode_radios[DetectorKind.OPENCV].setChecked(True)
        row.addStretch(1)
        return group

    def _build_results_group(self) -> QWidget:
        group = QGroupBox("Detector results")
        grid = QGridLayout(group)
        for column, header in enumerate(_ROW_HEADERS):
            label = QLabel(header)
            label.setStyleSheet(f"font-weight: 600; {_MUTED}")
            grid.addWidget(label, 0, column)
        self._result_rows = {
            kind: _ResultRow(grid, index + 1, kind) for index, kind in enumerate(_RESULT_KINDS)
        }
        return group

    def _build_workflow_row(self) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        buttons = QHBoxLayout()
        self._workflow_pill = widgets.StatusPill("No source")
        self._calibrate_button = QPushButton("Calibrate")
        self._calibrate_button.setEnabled(False)
        self._calibrate_button.setToolTip("Start a video source first.")
        self._calibrate_button.clicked.connect(self._on_calibrate)
        self._yolo_button = QPushButton("YOLO settings…")
        self._yolo_button.setEnabled(False)
        self._yolo_button.setToolTip("Start a video source first.")
        self._yolo_button.clicked.connect(self._on_yolo_settings)
        self._vlm_button = QPushButton("VLM settings…")
        self._vlm_button.setEnabled(False)
        self._vlm_button.setToolTip("Start a video source first.")
        self._vlm_button.clicked.connect(self._on_vlm_settings)
        self._dry_run_button = QPushButton("Dry run")
        self._dry_run_button.setEnabled(False)
        self._dry_run_button.setToolTip("Start a video source first.")
        self._dry_run_button.clicked.connect(self._on_dry_run)

        buttons.addWidget(self._workflow_pill)
        buttons.addWidget(self._calibrate_button)
        buttons.addWidget(self._yolo_button)
        buttons.addWidget(self._vlm_button)
        buttons.addWidget(self._dry_run_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        summary = QHBoxLayout()
        self._yolo_label = QLabel("")
        self._yolo_label.setStyleSheet(_MUTED)
        self._vlm_label = QLabel("")
        self._vlm_label.setStyleSheet(_MUTED)
        summary.addWidget(self._yolo_label)
        summary.addWidget(self._vlm_label)
        summary.addStretch(1)
        layout.addLayout(summary)

        self._workflow_detail = QLabel("")
        self._workflow_detail.setWordWrap(True)
        self._workflow_detail.setStyleSheet(_MUTED)
        layout.addWidget(self._workflow_detail)
        return row

    def _build_tracking_group(self) -> QWidget:
        group = QGroupBox("Autonomous yaw tracking (OpenCV / YOLO only)")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        warning = QLabel(
            "Target tracking yaws only. It does NOT detect obstacles, does not "
            "guarantee clearance and does not move toward or away from the target. "
            "Keep the aircraft in sight, keep the area clear, and be ready to press "
            "Stop Tracking or Emergency Land."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #b54708; font-weight: 600;")
        layout.addWidget(warning)

        controls = QHBoxLayout()
        self._tracking_target_label = QLabel("Tracking detector: OpenCV")
        self._tracking_target_label.setStyleSheet(_MUTED)
        self._arm_button = QPushButton("Arm autonomy")
        self._arm_button.setToolTip(
            "Explicitly permit a future Start Tracking. Arming sends no command and "
            "does not take off."
        )
        self._arm_button.clicked.connect(self._on_arm)
        self._start_tracking_button = QPushButton("Start Tracking")
        self._start_tracking_button.setToolTip(
            "Start yaw-only tracking. Requires arming, a successful dry run and "
            "flight under manual control."
        )
        self._start_tracking_button.clicked.connect(self._on_start_tracking)
        self._stop_tracking_button = QPushButton("Stop Tracking")
        self._stop_tracking_button.setToolTip(
            "Stop issuing yaw corrections. This does not land the aircraft."
        )
        self._stop_tracking_button.clicked.connect(self._on_stop_tracking)
        self._tracking_land_button = QPushButton("Land")
        self._tracking_land_button.setToolTip(
            "Send the standard landing command. It is distinct from Stop Tracking "
            "and from Emergency Land."
        )
        self._tracking_land_button.clicked.connect(self._on_tracking_land)

        controls.addWidget(self._tracking_target_label, 1)
        controls.addWidget(self._arm_button)
        controls.addWidget(self._start_tracking_button)
        controls.addWidget(self._stop_tracking_button)
        controls.addWidget(self._tracking_land_button)
        layout.addLayout(controls)

        self._tracking_status = QLabel(
            "Autonomy disarmed. A successful dry run and an explicit Arm are required."
        )
        self._tracking_status.setWordWrap(True)
        self._tracking_detail = QLabel("")
        self._tracking_detail.setWordWrap(True)
        self._tracking_detail.setStyleSheet(_MUTED)
        self._tracking_session = QLabel("")
        self._tracking_session.setStyleSheet(_MUTED)
        layout.addWidget(self._tracking_status)
        layout.addWidget(self._tracking_detail)
        layout.addWidget(self._tracking_session)
        return group

    # -- source lifecycle ----------------------------------------------------

    def _on_source_changed(self, _index: int) -> None:
        if self._updating_source:
            return
        kind = self._source_combo.currentData()
        if kind is None:
            return
        if kind == "file":
            if not self._prompt_for_file():
                self._restore_combo()
            return
        if kind == "synthetic":
            self._start_source("synthetic", None)
            return
        if kind == "tello":
            self.start_tello_camera()

    def start_tello_camera(self) -> None:
        """Ask the aircraft for its stream, then open the camera source.

        The command runs on a worker: ``streamon`` waits for a UDP reply, and
        the GUI thread must not.
        """
        if not self._hardware:
            widgets.show_error(
                self,
                "Tello camera",
                "This build is configured for the simulated aircraft. Start the "
                "application with DRONE_VISION_LAB_DRONE=tello to use the camera.",
            )
            self._restore_combo()
            return
        if not self._services.state.snapshot().drone_connected:
            widgets.show_error(
                self,
                "Tello camera",
                "Connect to the Tello on the Drone Control tab first.",
            )
            self._restore_combo()
            return
        if self._camera_runner.busy:
            self._restore_combo()
            return
        self._status_pill.set_status("Starting Tello camera…", "warn")
        self._camera_token += 1
        self._submitted_camera_token = self._camera_token
        if not self._camera_runner.submit(self._services.drone.start_video_stream):
            self._restore_combo()

    def _on_camera_command_finished(self, result: object) -> None:
        if self._submitted_camera_token != self._camera_token:
            # The operator stopped the source while ``streamon`` was in flight.
            # Do not open the camera now; if the aircraft acknowledged anyway,
            # turn the stream back off so it is not left running.
            if isinstance(result, CommandResult) and result.ok:
                self._stop_tello_stream_async()
            self._restore_combo()
            return
        if not isinstance(result, CommandResult):
            return
        if not result.ok:
            self._status_pill.set_status("No source", "idle")
            widgets.show_error(
                self,
                "Tello camera",
                result.detail or "The aircraft did not acknowledge streamon.",
            )
            self._restore_combo()
            return
        self._start_source("tello", None)

    def _on_camera_command_failed(self, message: str) -> None:
        if self._submitted_camera_token != self._camera_token:
            # A stop already reset the UI; a late failure must not reopen a
            # dialog for a camera the operator dismissed.
            return
        self._status_pill.set_status("No source", "idle")
        widgets.show_error(self, "Tello camera", message)
        self._restore_combo()

    def _on_load_video(self) -> None:
        self._prompt_for_file()

    def _prompt_for_file(self) -> bool:
        if self._last_path:
            start_dir = self._last_path
        else:
            folder = videos_dir()
            with contextlib.suppress(OSError):
                folder.mkdir(parents=True, exist_ok=True)
            start_dir = str(folder)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a video file",
            start_dir,
            "Video files (*.mp4 *.avi *.mov *.mkv *.webm);;All files (*)",
        )
        if not path:
            return False
        self._last_path = path
        self._set_combo("file")
        self._start_source("file", path)
        return True

    def _set_combo(self, kind: str | None) -> None:
        index = self._source_combo.findData(kind)
        if index < 0:
            return
        self._updating_source = True
        try:
            self._source_combo.setCurrentIndex(index)
        finally:
            self._updating_source = False

    def _restore_combo(self) -> None:
        self._set_combo(self._current_kind)

    @staticmethod
    def _owns_video(snapshot: AppStateSnapshot) -> bool:
        """True when the active video source belongs to this tab.

        A ``None`` owner with video active predates the Tello Flight tab, so it
        is treated as this tab's video. Another owner means the Tello camera or
        a local file belongs to the other view; this tab must not use it for
        dry runs, tracking or its own workflow status.
        """
        return snapshot.video_active and snapshot.video_owner in (None, _VIDEO_OWNER)

    def _start_source(self, kind: str, path: str | None) -> None:
        snapshot = self._services.state.snapshot()
        if snapshot.video_active and snapshot.video_owner not in (None, _VIDEO_OWNER):
            widgets.show_error(
                self,
                "Video source",
                "Another tab is using the camera. Stop it there before starting a "
                "source here.",
            )
            self._restore_combo()
            return
        # Replacing a Tello camera with another source stops its stream; starting
        # the Tello source again leaves the stream running for the new socket.
        self.stop_source(stop_stream=kind != "tello")
        try:
            source = self._services.video_source_factory(kind, path)
            source.open()
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            _log.exception("Could not open video source", extra={"context": {"kind": kind}})
            if kind == "tello":
                self._stop_tello_stream_async()
            widgets.show_error(self, "Video source", exc)
            self._restore_combo()
            return

        source.set_looping(self._loop_check.isChecked())
        pump = FramePump(source, target_fps=30.0, parent=self)
        seq = self._source_seq
        pump.frame_ready.connect(partial(self._on_frame, seq=seq))
        pump.status_changed.connect(partial(self._on_status, seq=seq))
        pump.failed.connect(partial(self._on_pump_failed, seq=seq))

        self._source = source
        self._pump = pump
        self._current_kind = kind
        self._set_combo(kind)
        self._play_button.setEnabled(True)
        self._play_button.setText("Pause")
        self._play_button.setToolTip("")
        self._stop_button.setEnabled(True)
        self._frame_label.setText("")
        self._status_pill.set_status("Live", "ok", source.description)
        self._services.state.update(
            video_active=True,
            video_source_type=kind,
            video_owner=_VIDEO_OWNER,
        )
        self._store_source_setting(kind, path)
        self._prepare_detector()
        self._yolo_button.setEnabled(True)
        self._yolo_button.setToolTip("Choose weights, a class and test on the current frame.")
        self._vlm_button.setEnabled(True)
        self._vlm_button.setToolTip("Check Ollama, choose a vision model and set the interval.")
        self._dry_run_button.setEnabled(True)
        self._dry_run_button.setToolTip("Run OpenCV and YOLO on one frame.")
        self._refresh_yolo_status()
        self._refresh_vlm_status()
        self._sync_vlm_poller()
        pump.start()

    def _store_source_setting(self, kind: str, path: str | None) -> None:
        """Remember the chosen source in the active profile, if there is one.

        A profile being unwritable must never stop a video source from starting,
        so failure is logged and otherwise ignored.
        """
        try:
            store_profile_section_if_active(
                self._services, "source", {"kind": kind, "path": path}
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping only
            _log.warning("Could not record the source in the active profile: %s", exc)

    def _prepare_detector(self) -> None:
        """Load the OpenCV detector lazily and enable calibration when possible."""
        detector = self._services.detectors.get(DetectorKind.OPENCV)
        if not isinstance(detector, OpenCvTargetDetector):
            return
        try:
            detector.load()
        except Exception as exc:  # noqa: BLE001 - missing OpenCV is expected on some machines
            self._calibrate_button.setEnabled(False)
            self._calibrate_button.setToolTip(str(exc))
            _log.warning("OpenCV detector unavailable: %s", exc)
            return
        self._calibrate_button.setEnabled(True)
        self._calibrate_button.setToolTip("Sample the target colour and refine the mask.")

    def _on_calibrate(self) -> None:
        frame = self._last_frame
        if frame is None:
            widgets.show_error(
                self,
                "Calibration",
                "Wait for the video source to deliver a frame, then try again.",
            )
            return
        dialog = CalibrationDialog(self._services, frame, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self._tracking is not None and self._tracking.active:
                self._stop_tracking(
                    "The detector configuration changed; tracking stopped. "
                    "The aircraft is not landed.",
                    alert=False,
                )
            self._update_result_grid()
            self._sync_vlm_poller()

    def _on_yolo_settings(self) -> None:
        frame = self._last_frame
        if frame is None:
            widgets.show_error(
                self,
                "YOLO",
                "Wait for the video source to deliver a frame, then try again.",
            )
            return
        dialog = YoloSettingsDialog(self._services, frame, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self._tracking is not None and self._tracking.active:
                self._stop_tracking(
                    "The detector configuration changed; tracking stopped. "
                    "The aircraft is not landed.",
                    alert=False,
                )
            self._refresh_yolo_status()
            self._update_result_grid()

    def _on_vlm_settings(self) -> None:
        dialog = VlmSettingsDialog(
            self._services,
            self._last_frame,
            self,
            frame_provider=lambda: self._last_frame,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_vlm_status()
            self._sync_vlm_poller()
            self._update_result_grid()

    def _refresh_yolo_status(self) -> None:
        detector = self._services.detectors.get(DetectorKind.YOLO)
        if isinstance(detector, YoloDetector) and detector.ready:
            self._yolo_label.setText(
                f"YOLO: {detector.config.class_label} on {detector.device}"
            )
        else:
            self._yolo_label.setText("YOLO: not configured")

    def _refresh_vlm_status(self) -> None:
        detector = self._services.detectors.get(DetectorKind.VLM)
        if isinstance(detector, OllamaVlmDetector) and detector.ready:
            self._vlm_label.setText(f"VLM: {detector.config.model} (advisory)")
        else:
            self._vlm_label.setText("VLM: not configured")

    def stop_source(self, *, stop_stream: bool = True) -> None:
        # Invalidate everything already queued for the source being torn down.
        self._source_seq += 1
        # Also invalidate a ``streamon`` still in flight: its acknowledgement
        # must not reopen the camera after this stop.
        self._camera_token += 1
        self._dry_run_pending = False
        if self._tracking is not None and self._tracking.active:
            self._stop_tracking(
                "The video source was stopped; tracking stopped. The aircraft is "
                "not landed.",
                alert=False,
            )
        pump, source = self._pump, self._source
        source_kind = self._current_kind
        self._pump = None
        self._source = None
        if pump is not None:
            pump.stop()
        if source is not None:
            source.close()
        if (
            source_kind == "tello"
            and stop_stream
            and self._services.state.snapshot().drone_connected
        ):
            # Best effort, off the GUI thread: the camera is already closed, so a
            # slow streamoff cannot affect the frame pipeline.
            self._stop_tello_stream_async()
        self._stop_vlm_poller()
        self._preview.clear()
        self._frame_label.setText("")
        self._set_combo(None)
        self._current_kind = None
        self._play_button.setEnabled(False)
        self._play_button.setText("Pause")
        self._play_button.setToolTip("")
        self._stop_button.setEnabled(False)
        self._status_pill.set_status("No source", "idle")
        self._calibrate_button.setEnabled(False)
        self._calibrate_button.setToolTip("Start a video source first.")
        self._yolo_button.setEnabled(False)
        self._yolo_button.setToolTip("Start a video source first.")
        self._vlm_button.setEnabled(False)
        self._vlm_button.setToolTip("Start a video source first.")
        self._dry_run_button.setEnabled(False)
        self._dry_run_button.setToolTip("Start a video source first.")
        self._last_frame = None
        self._results.clear()
        self._update_result_grid()
        self._reset_dry_run()
        snapshot = self._services.state.snapshot()
        if snapshot.video_owner in (None, _VIDEO_OWNER):
            self._services.state.update(
                video_active=False,
                video_source_type=None,
                video_owner=None,
            )

    def shutdown(self) -> None:
        """Called by the main window before the application exits."""
        self._tracking_timer.stop()
        if self._tracking is not None and self._tracking.active:
            self._stop_tracking("The application is closing; tracking stopped.", alert=False)
        self._stop_vlm_poller()
        self.stop_source()
        # Give a pending streamoff a bounded chance to reach the aircraft, so
        # closing the window does not leave the camera streaming.
        thread = self._stream_stop_thread
        if thread is not None and thread.is_alive():
            thread.join(2.0)

    def _stop_tello_stream_async(self) -> None:
        """Send ``streamoff`` without blocking the close path."""
        drone = self._services.drone
        previous = self._stream_stop_thread
        if previous is not None and previous.is_alive():
            previous.join(0.5)

        def _run() -> None:
            try:
                drone.stop_video_stream()
            except Exception:  # noqa: BLE001 - best effort while shutting down
                _log.warning("Could not stop the Tello video stream", exc_info=True)

        thread = threading.Thread(target=_run, name="tello-streamoff", daemon=True)
        self._stream_stop_thread = thread
        thread.start()

    # -- transport -----------------------------------------------------------

    def _toggle_pause(self) -> None:
        source = self._source
        if source is None:
            return
        if source.state is VideoSourceState.ENDED:
            self._replay()
            return
        if source.state is VideoSourceState.PAUSED:
            source.resume()
            self._play_button.setText("Pause")
            self._play_button.setToolTip("")
        else:
            source.pause()
            self._play_button.setText("Play")
            self._play_button.setToolTip("Pause on this frame; calibration uses the frozen frame.")

    def _replay(self) -> None:
        """Restart a finished file from the beginning.

        A file source stops at the end of the clip and its pump thread exits.
        Replaying is the same source and the same calibration, so the dry-run
        result stays valid.
        """
        source = self._source
        pump = self._pump
        if source is None:
            return
        if pump is not None:
            pump.stop()
        if not source.seek(0.0):
            return
        source.resume()
        self._play_button.setText("Pause")
        self._play_button.setToolTip("")
        self._status_pill.set_status("Live", "ok", source.description)
        if pump is not None:
            pump.start()

    def _on_loop_toggled(self, checked: bool) -> None:
        if self._source is not None:
            self._source.set_looping(checked)

    # -- modes ---------------------------------------------------------------

    def _on_mode_changed(self, mode: DetectorKind | str) -> None:
        if mode == self._mode:
            return
        if self._tracking is not None and self._tracking.active:
            self._stop_tracking(
                "The vision mode changed; tracking stopped. The aircraft is not "
                "landed.",
                alert=False,
            )
        self._mode = mode
        self._sync_vlm_poller()
        self._update_result_grid()
        self._update_preview()
        snapshot = self._services.state.snapshot()
        self._refresh_workflow(snapshot)
        self._refresh_tracking(snapshot)

    def set_mode(self, mode: DetectorKind | str) -> None:
        """Select a mode programmatically; used by tests and phase 10."""
        radio = self._mode_radios.get(mode)
        if radio is None:
            raise ValueError(f"Unknown vision mode: {mode!r}")
        radio.setChecked(True)
        self._on_mode_changed(mode)

    def _mode_kinds(self) -> tuple[DetectorKind, ...]:
        if self._mode == "comparison":
            return _RESULT_KINDS
        if isinstance(self._mode, DetectorKind):
            return (self._mode,)
        return ()

    # -- pump signals --------------------------------------------------------

    def _is_current_source(self, seq: int | None) -> bool:
        """Whether work tagged with ``seq`` still belongs to the live source.

        ``None`` means the call did not come from a pump (tests and direct
        calls) and is accepted.
        """
        return seq is None or seq == self._source_seq

    def _on_frame(self, frame: Frame, *, seq: int | None = None) -> None:
        if not self._is_current_source(seq):
            return
        self._last_frame = frame
        self._frame_label.setText(f"Frame {frame.index} — {frame.width}×{frame.height}")
        self._update_preview()
        now = time.monotonic()
        if now - self._last_tracking_refresh >= 0.25:
            self._last_tracking_refresh = now
            self._refresh_tracking(self._services.state.snapshot())
        self._maybe_analyze(frame)

    def _on_status(self, status: VideoSourceStatus, *, seq: int | None = None) -> None:
        if not self._is_current_source(seq):
            return
        text, level = _STATUS_MAP.get(status, ("Unknown", "idle"))
        description = self._source.description if self._source is not None else ""
        self._status_pill.set_status(text, level, description)
        if status is VideoSourceStatus.ENDED:
            # A file can be played again from the start; a live camera cannot.
            if self._current_kind == "file":
                self._play_button.setEnabled(True)
                self._play_button.setText("Replay")
                self._play_button.setToolTip("Play this video again from the beginning.")
            else:
                self._play_button.setEnabled(False)
        if (
            status is not VideoSourceStatus.LIVE
            and self._tracking is not None
            and self._tracking.active
        ):
            self._stop_tracking(
                "The video source is no longer live; tracking stopped. The aircraft "
                "is not landed.",
                alert=True,
            )

    def _on_pump_failed(self, message: str, *, seq: int | None = None) -> None:
        if not self._is_current_source(seq):
            return
        if self._tracking is not None and self._tracking.active:
            self._stop_tracking(
                "Video playback failed; tracking stopped. The aircraft is not landed.",
                alert=True,
            )
        widgets.show_error(self, "Video playback failed", message)
        self.stop_source()

    # -- analysis ------------------------------------------------------------

    def _maybe_analyze(self, frame: Frame) -> None:
        kinds = tuple(
            kind
            for kind in self._mode_kinds()
            if kind in _FRAME_KINDS and self._detector_ready(kind)
        )
        if not kinds:
            return
        if self._analysis_runner.busy:
            self._dropped_frames += 1
            return
        self._analysis_seq = self._source_seq
        self._analysis_runner.submit(lambda: self._analyze(frame, kinds))

    def _analyze(
        self, frame: Frame, kinds: tuple[DetectorKind, ...]
    ) -> dict[DetectorKind, DetectionResult]:
        """Runs on a worker thread. Never raises; failures become result errors."""
        batch: dict[DetectorKind, DetectionResult] = {}
        for kind in kinds:
            detector = self._services.detectors.get(kind)
            if detector is None:
                batch[kind] = _error_result(frame, kind, "Detector is not configured")
                continue
            try:
                batch[kind] = detector.detect(frame)
            except Exception as exc:  # noqa: BLE001 - one detector must not stop the others
                _log.exception("Detector %s failed", kind)
                batch[kind] = _error_result(frame, kind, f"Detector failed: {exc}")
        return batch

    def _on_analysis_finished(self, batch: object) -> None:
        if not self._is_current_source(self._analysis_seq):
            # The source was stopped or replaced while this frame was analyzed.
            return
        if not isinstance(batch, dict):
            return
        self._results.update(batch)
        for result in batch.values():
            if isinstance(result, DetectionResult):
                self._record_experiment(result)
                self._process_tracking_result(result)
        self._update_result_grid()
        self._update_preview()

    def _record_experiment(self, result: DetectionResult) -> None:
        """Feed the running experiment, if any. A no-op otherwise."""
        observed_at = result.processed_at if result.processed_at > 0 else time.monotonic()
        self._services.experiment.observe(result, observed_at=observed_at)

    def _on_analysis_failed(self, message: str) -> None:
        if not self._is_current_source(self._analysis_seq):
            return
        self._workflow_detail.setText(f"Analysis failed: {message}")
        self._workflow_detail.setStyleSheet("color: #a12a2a;")

    # -- VLM polling ---------------------------------------------------------

    def _sync_vlm_poller(self) -> None:
        candidate = self._services.detectors.get(DetectorKind.VLM)
        detector = candidate if isinstance(candidate, OllamaVlmDetector) else None
        wanted = (
            DetectorKind.VLM in self._mode_kinds()
            and detector is not None
            and detector.ready
            and self._source is not None
        )
        if not wanted or detector is None:
            self._stop_vlm_poller()
            return

        if self._vlm_poller is not None and self._vlm_poller_detector is not detector:
            self._stop_vlm_poller()
        if self._vlm_poller is None:
            poller = VlmPoller(
                detector,
                lambda: self._last_frame,
                interval_s=detector.config.interval_s,
                parent=self,
            )
            # Tag results with their poller: an answer queued before a stop or
            # a source change must not land in the new session's table.
            poller.result_ready.connect(partial(self._on_vlm_result, poller=poller))
            poller.failed.connect(partial(self._on_vlm_failed, poller=poller))
            self._vlm_poller = poller
            self._vlm_poller_detector = detector
        self._vlm_poller.set_interval(detector.config.interval_s)
        self._vlm_poller.start()

    def _stop_vlm_poller(self) -> None:
        if self._vlm_poller is not None:
            self._vlm_poller.stop()
            self._vlm_poller.deleteLater()
        self._vlm_poller = None
        self._vlm_poller_detector = None

    def _on_vlm_result(self, result: object, *, poller: object = None) -> None:
        if poller is not None and poller is not self._vlm_poller:
            return
        if not isinstance(result, DetectionResult):
            return
        self._results[DetectorKind.VLM] = result
        self._record_experiment(result)
        self._update_result_grid()
        self._update_preview()

    def _on_vlm_failed(self, message: str, *, poller: object = None) -> None:
        if poller is not None and poller is not self._vlm_poller:
            return
        self._workflow_detail.setText(f"VLM analysis failed: {message}")
        self._workflow_detail.setStyleSheet("color: #a12a2a;")

    # -- dry run -------------------------------------------------------------

    def _on_dry_run(self) -> None:
        kinds = tuple(kind for kind in self._mode_kinds() if kind in _FRAME_KINDS)
        if not kinds:
            widgets.show_error(
                self,
                "Dry run",
                "The VLM is advisory and cannot pass a dry run. Select OpenCV, YOLO or "
                "Comparison.",
            )
            return
        frame = self._last_frame
        if frame is None:
            widgets.show_error(
                self, "Dry run", "Wait for the video source to deliver a frame first."
            )
            return
        not_ready = [kind for kind in kinds if not self._detector_ready(kind)]
        if not_ready:
            widgets.show_error(
                self,
                "Dry run",
                "Not ready: "
                + ", ".join(_not_ready_reason(self._services, kind) for kind in not_ready),
            )
            return
        self._dry_run_pending = True
        self._dry_run_seq = self._source_seq
        self._workflow_detail.setText("Running dry run on one frame…")
        self._workflow_detail.setStyleSheet(_MUTED)
        if not self._dry_runner.submit(lambda: self._analyze(frame, kinds)):
            self._dry_run_pending = False

    def _on_dry_run_finished(self, batch: object) -> None:
        if not self._is_current_source(self._dry_run_seq):
            # The source changed while the frame was analyzed, so this result
            # describes a frame that is no longer current.
            self._dry_run_pending = False
            return
        if not isinstance(batch, dict):
            return
        self._dry_run_pending = False
        self._results.update(batch)
        for result in batch.values():
            if isinstance(result, DetectionResult):
                self._record_experiment(result)
        self._update_result_grid()
        self._update_preview()

        passed = tuple(kind for kind, result in batch.items() if not result.failed and result.found)
        failed = tuple(kind for kind, result in batch.items() if result.failed)
        missing = tuple(
            kind for kind, result in batch.items() if not result.failed and not result.found
        )
        update: dict[str, object] = {
            "dry_run_passed_kinds": tuple(kind.value for kind in passed),
            "dry_run_partial": bool(passed) and bool(failed or missing),
            "last_error": None if passed else "Dry run: no detector found the target",
        }
        if passed:
            update["safety_state"] = SafetyState.DRY_RUN_PASSED
        self._services.state.update(**update)
        self._store_dry_run_summary(passed, failed, missing)

        self._workflow_detail.setText(_dry_run_summary(passed, failed, missing))
        self._workflow_detail.setStyleSheet(
            "color: #2f6f44;" if passed and not (failed or missing) else "color: #b26a00;"
        )
        _log.info(
            "Dry run finished",
            extra={
                "context": {
                    "passed": [kind.value for kind in passed],
                    "failed": [kind.value for kind in failed],
                    "not_found": [kind.value for kind in missing],
                }
            },
        )

    def _store_dry_run_summary(
        self,
        passed: tuple[DetectorKind, ...],
        failed: tuple[DetectorKind, ...],
        missing: tuple[DetectorKind, ...],
    ) -> None:
        try:
            store_profile_section_if_active(
                self._services,
                "dry_run",
                {
                    "passed": [kind.value for kind in passed],
                    "failed": [kind.value for kind in failed],
                    "not_found": [kind.value for kind in missing],
                    "at": utc_timestamp(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - bookkeeping only
            _log.warning("Could not record the dry-run summary in the active profile: %s", exc)

    def _on_dry_run_failed(self, message: str) -> None:
        self._dry_run_pending = False
        if not self._is_current_source(self._dry_run_seq):
            return
        self._workflow_detail.setText(f"Dry run failed: {message}")
        self._workflow_detail.setStyleSheet("color: #a12a2a;")

    def _reset_dry_run(self) -> None:
        snapshot = self._services.state.snapshot()
        if snapshot.safety_state.in_flight:
            return
        changes: dict[str, object] = {
            "dry_run_passed_kinds": (),
            "dry_run_partial": False,
        }
        # Clearing calibration/dry-run results revokes the autonomy that depended
        # on them, but it must never invent a disconnection: a connected aircraft
        # stays connected grounded. Only an autonomy state is downgraded.
        if snapshot.safety_state in (
            SafetyState.CALIBRATED,
            SafetyState.DRY_RUN_PASSED,
            SafetyState.ARMED,
        ):
            changes["safety_state"] = (
                SafetyState.CONNECTED_GROUNDED
                if snapshot.drone_connected
                else SafetyState.DISCONNECTED
            )
        self._services.state.update(**changes)

    def autonomous_ready(self, kind: DetectorKind) -> bool:
        """Autonomy gate for phase 10: VLM never qualifies."""
        if kind not in _FRAME_KINDS:
            return False
        snapshot = self._services.state.snapshot()
        if kind.value not in snapshot.dry_run_passed_kinds:
            return False
        return self._detector_ready(kind)

    # -- autonomous tracking ------------------------------------------------

    def _tracking_kind(self) -> DetectorKind | None:
        """The single detector a tracking session may use, if one is selected."""
        if isinstance(self._mode, DetectorKind) and self._mode in _FRAME_KINDS:
            return self._mode
        return None

    def _can_arm_reason(self, snapshot: AppStateSnapshot) -> str:
        kind = self._tracking_kind()
        if kind is None:
            return (
                "Select OpenCV or YOLO as the vision mode. Comparison and the "
                "VLM cannot arm tracking."
            )
        if not snapshot.drone_connected:
            return "Connect to the aircraft before arming autonomy."
        if snapshot.safety_state is not SafetyState.DRY_RUN_PASSED:
            return "Run a successful dry run for the selected detector first."
        if not self.autonomous_ready(kind):
            return f"{DISPLAY_NAMES[kind]} has not passed a dry run or is not ready."
        return ""

    def _can_start_reason(self, snapshot: AppStateSnapshot) -> str:
        if self._tracking is not None and self._tracking.active:
            return "Tracking is already active."
        kind = self._tracking_kind()
        if kind is None:
            return "Select OpenCV or YOLO as the vision mode before tracking."
        if not snapshot.drone_connected:
            return "Connect to the aircraft before starting tracking."
        if not snapshot.autonomy_armed:
            return "Arm autonomy after a successful dry run first."
        if snapshot.safety_state is not SafetyState.FLYING_MANUAL:
            return (
                "Take off under explicit manual control before starting tracking. "
                "Tracking never takes off by itself."
            )
        if not self.autonomous_ready(kind):
            return f"{DISPLAY_NAMES[kind]} has not passed a dry run or is not ready."
        if not self._owns_video(snapshot):
            return "Start a video source on this tab before tracking."
        frame = self._last_frame
        if (
            frame is None
            or time.monotonic() - frame.captured_at > _TRACKING_SETTINGS.stale_after_s
        ):
            return "No fresh camera frame has arrived; wait for live video."
        return ""

    def _on_arm(self) -> None:
        snapshot = self._services.state.snapshot()
        if snapshot.autonomy_armed:
            if snapshot.safety_state is not SafetyState.ARMED:
                self._tracking_status.setText(
                    "Disarming is available only while grounded and armed."
                )
                self._refresh_tracking(snapshot)
                return
            self._services.state.update(autonomy_armed=False)
            with contextlib.suppress(InvalidTransition):
                self._safety.move(SafetyState.DRY_RUN_PASSED)
            self._tracking_alert = ""
            self._tracking_status.setText(
                "Autonomy disarmed. Start Tracking is disabled; no command was sent."
            )
            self._tracking_status.setStyleSheet("color: #5b6470;")
            self._tracking_detail.setText("")
            self._refresh_tracking(self._services.state.snapshot())
            return

        reason = self._can_arm_reason(snapshot)
        if reason:
            self._tracking_status.setText(reason)
            self._tracking_status.setStyleSheet("color: #b54708;")
            return
        answer = QMessageBox.warning(
            self,
            "Arm autonomy",
            "Arming permits yaw-only target tracking. It sends no command and does "
            "NOT take off.\n\n"
            "After arming you must take off with explicit manual control, then "
            "press Start Tracking. Tracking yaws toward a detected target; it does "
            "not detect obstacles or guarantee clearance.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if not widgets.is_yes(answer):
            return
        snapshot = self._services.state.snapshot()
        reason = self._can_arm_reason(snapshot)
        if reason:
            self._tracking_status.setText(reason)
            return
        try:
            self._safety.move(SafetyState.ARMED)
        except InvalidTransition as exc:
            widgets.show_error(self, "Arm autonomy", str(exc))
            return
        # Set the permission after the state change: the state listener disarms
        # whenever an armed flag is seen outside ARMED/manual flight.
        self._services.state.update(autonomy_armed=True)
        self._tracking_alert = ""
        self._tracking_status.setText(
            "Autonomy armed while grounded. No command has been sent; take off with "
            "manual control, then press Start Tracking."
        )
        self._tracking_status.setStyleSheet("color: #b54708;")
        self._tracking_detail.setText("")
        self._refresh_tracking(self._services.state.snapshot())

    def _on_start_tracking(self) -> None:
        snapshot = self._services.state.snapshot()
        reason = self._can_start_reason(snapshot)
        if reason:
            self._tracking_status.setText(reason)
            self._tracking_status.setStyleSheet("color: #b54708;")
            return
        answer = QMessageBox.warning(
            self,
            "Start target tracking",
            "The aircraft will send small yaw steps to keep the detected target near "
            "the horizontal centre. It will not move forward, backward or change "
            "altitude.\n\n"
            "Target tracking does NOT detect obstacles and does not guarantee "
            "clearance. Keep the area clear and the aircraft in sight.\n\n"
            f"The session ends automatically after "
            f"{_TRACKING_SETTINGS.session_limit_s:.0f} s. Stop Tracking stops yaw "
            "corrections but does NOT land.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if not widgets.is_yes(answer):
            return

        snapshot = self._services.state.snapshot()
        kind = self._tracking_kind()
        reason = self._can_start_reason(snapshot)
        if reason or kind is None:
            self._tracking_status.setText(reason or "Select OpenCV or YOLO first.")
            return

        controller = TrackingController(
            self._services.drone,
            detector_kind=kind,
            settings=_TRACKING_SETTINGS,
            detector_ready=partial(self._detector_ready, kind),
            on_error=partial(self._services.experiment.observe_stability, kind),
        )
        reason = controller.start(snapshot)
        if reason:
            self._tracking_status.setText(reason)
            self._tracking_status.setStyleSheet("color: #b54708;")
            return
        self._tracking = controller
        try:
            self._safety.move(SafetyState.FLYING_TRACKING)
        except InvalidTransition as exc:
            controller.stop(str(exc))
            self._tracking = None
            widgets.show_error(self, "Start tracking", str(exc))
            return
        self._tracking_alert = ""
        self._tracking_timer.start()
        self._tracking_status.setText(
            "Tracking active — yaw corrections only. Watch for obstacles yourself: "
            "tracking does not detect them."
        )
        self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 600;")
        self._tracking_detail.setText("Waiting for a fresh detector result…")
        self._refresh_tracking(self._services.state.snapshot())

    def _on_stop_tracking(self) -> None:
        self._stop_tracking(
            "Stopped by the operator. The aircraft is still airborne.", alert=False
        )

    def _stop_tracking(self, reason: str, *, alert: bool) -> None:
        controller = self._tracking
        was_active = bool(controller is not None and controller.active)
        if controller is not None:
            controller.stop(reason)
        self._tracking_timer.stop()
        snapshot = self._services.state.snapshot()
        if snapshot.safety_state is SafetyState.FLYING_TRACKING:
            try:
                snapshot = self._safety.move(SafetyState.FLYING_MANUAL, reason=reason)
            except InvalidTransition:
                snapshot = self._services.state.update(last_error=reason)
        self._tracking_alert = reason
        self._tracking_status.setText(f"Tracking stopped: {reason}")
        self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 600;")
        self._tracking_detail.setText(
            "This stop issued no landing command. Use Land or the always-visible "
            "Emergency Land if the aircraft must come down."
        )
        if alert and was_active:
            widgets.show_error(
                self,
                "Tracking stopped",
                f"{reason}\n\nNo landing command was sent by this stop. Keep the "
                "aircraft in sight and press Land or Emergency Land if needed.",
            )
        self._refresh_tracking(snapshot)

    def _abandon_tracking(self, reason: str) -> None:
        """Stop locally when the safety state changed underneath the session."""
        controller = self._tracking
        if controller is None or not controller.active:
            return
        controller.stop(reason)
        self._tracking_timer.stop()
        self._tracking_alert = reason
        self._tracking_status.setText(f"Tracking stopped: {reason}")
        self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 600;")
        self._tracking_detail.setText(
            "No landing command was sent by this stop. Only independent evidence "
            "reports the aircraft as landed."
        )

    def on_manual_override(self) -> bool:
        """Called by manual input. Stops tracking before the manual step is sent."""
        controller = self._tracking
        if controller is None or not controller.active:
            return False
        self._stop_tracking(
            "Manual override: tracking stopped and manual control owns the aircraft.",
            alert=False,
        )
        return True

    def _process_tracking_result(self, result: DetectionResult) -> None:
        controller = self._tracking
        if controller is None or not controller.active:
            return
        if result.kind is not controller.detector_kind:
            return
        update: TrackingUpdate = controller.process(result)
        if update.stop_reason is not None:
            self._stop_tracking(update.stop_reason, alert=True)
            return
        if update.command is not None:
            self._submit_tracking_command(update.command)
            return
        if update.target_lost:
            self._tracking_detail.setText(
                "Target not found. No yaw correction is being sent; repeated loss "
                "ends the tracking session."
            )
        elif update.centered:
            self._tracking_detail.setText(
                f"Target centred within the ±{controller.settings.deadband:.2f} "
                "deadband; no yaw correction."
            )
        elif update.rate_limited:
            self._tracking_detail.setText(
                "Waiting for the minimum gap between yaw commands; no new command."
            )

    def _submit_tracking_command(self, command: TrackingCommand) -> None:
        if self._tracking_runner.busy:
            self._tracking_detail.setText("A previous yaw command is still pending.")
            return
        self._tracking_detail.setText(f"Sending {command.describe()}…")
        direction, degrees = command.direction, command.degrees
        if not self._tracking_runner.submit(
            lambda: self._services.drone.rotate(direction, degrees)
        ):
            self._tracking_detail.setText("A previous yaw command is still pending.")

    def _on_tracking_command_finished(self, result: object) -> None:
        if not isinstance(result, CommandResult):
            return
        controller = self._tracking
        if controller is None or not controller.active:
            # The session ended while this command was in flight; its stop
            # reason owns the status text.
            return
        if result.ok:
            self._tracking_detail.setText(
                f"{result.command}: sent — not confirmed. Yaw corrections only."
            )
            return
        if result.status is CommandStatus.TIMEOUT:
            reason = (
                "A yaw command timed out; its outcome is unknown. Tracking stopped "
                f"and the aircraft is still airborne. {result.detail}"
            ).strip()
        else:
            reason = (
                "A yaw command could not be sent; tracking stopped. "
                f"The aircraft is still airborne. {result.detail}"
            ).strip()
        self._fail_tracking(reason)

    def _on_tracking_command_failed(self, message: str) -> None:
        controller = self._tracking
        if controller is None or not controller.active:
            return
        self._fail_tracking(
            "A yaw command failed in the worker; tracking stopped. "
            f"The aircraft is still airborne. {message}"
        )

    def _fail_tracking(self, reason: str) -> None:
        controller = self._tracking
        if controller is not None:
            controller.stop(reason)
        self._tracking_timer.stop()
        self._services.state.update(autonomy_armed=False)
        snapshot = self._services.state.snapshot()
        if snapshot.safety_state is SafetyState.FLYING_TRACKING:
            target = (
                SafetyState.COMMUNICATION_LOST
                if not self._services.drone.connected
                else SafetyState.FAULT
            )
            try:
                snapshot = self._safety.move(target, reason=reason)
            except InvalidTransition:
                snapshot = self._services.state.update(last_error=reason)
        self._tracking_alert = reason
        self._tracking_status.setText(f"Tracking stopped: {reason}")
        self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 700;")
        self._tracking_detail.setText(
            "No landing command was sent. Use Land or Emergency Land; neither is "
            "claimed confirmed without evidence."
        )
        widgets.show_error(self, "Tracking stopped", reason)
        self._refresh_tracking(snapshot)

    def _on_tracking_tick(self) -> None:
        controller = self._tracking
        if controller is None or not controller.active:
            self._tracking_timer.stop()
            return
        update = controller.check_health()
        if update.stop_reason is not None:
            self._stop_tracking(update.stop_reason, alert=True)
            return
        elapsed = controller.elapsed_s()
        limit = controller.settings.session_limit_s
        self._tracking_session.setText(
            f"Tracking session {elapsed:.0f} / {limit:.0f} s. "
            "The session ends automatically at the limit."
        )
        self._refresh_tracking(self._services.state.snapshot())

    def _on_tracking_land(self) -> None:
        snapshot = self._services.state.snapshot()
        if snapshot.safety_state not in (
            SafetyState.FLYING_MANUAL,
            SafetyState.FLYING_TRACKING,
        ):
            self._tracking_status.setText(
                "Landing from this panel is available while the aircraft is under "
                "manual control or tracking."
            )
            return
        answer = QMessageBox.question(
            self,
            "Land",
            "Send the standard landing command now?\n\n"
            "This is the ordinary Land action, not Emergency Land. It commands a "
            "descent and is reported as sent, not confirmed, until evidence arrives.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if not widgets.is_yes(answer):
            return
        if self._tracking is not None and self._tracking.active:
            self._stop_tracking("Landing requested by the operator.", alert=False)
        snapshot = self._services.state.snapshot()
        if snapshot.safety_state is not SafetyState.FLYING_MANUAL:
            self._tracking_status.setText(
                "The safety state changed; landing was not sent from this panel."
            )
            return
        try:
            snapshot = self._safety.move(SafetyState.LANDING_REQUESTED)
        except InvalidTransition as exc:
            widgets.show_error(self, "Land", str(exc))
            return
        self._tracking_alert = ""
        self._tracking_status.setText(
            "Landing requested. Waiting for the command channel; not confirmed yet."
        )
        self._tracking_status.setStyleSheet("color: #b54708;")
        self._tracking_detail.setText(
            "A landing is reported as confirmed only when a later observation "
            "(for example telemetry height 0) supports it."
        )
        if not self._land_runner.submit(self._services.drone.land):
            reason = "The landing command could not be submitted."
            self._tracking_status.setText(f"{reason} The outcome is unknown.")
            try:
                self._safety.move(SafetyState.FAULT, reason=reason)
            except InvalidTransition:
                self._services.state.update(last_error=reason)
        self._refresh_tracking(self._services.state.snapshot())

    def _on_tracking_land_finished(self, result: object) -> None:
        if not isinstance(result, CommandResult):
            return
        self._services.state.update(autonomy_armed=False)
        if result.status is CommandStatus.CONFIRMED:
            self._tracking_status.setText("Landing confirmed by the aircraft's telemetry.")
            self._tracking_status.setStyleSheet("color: #2f6f44;")
            if self._safety.can_move(SafetyState.LANDED_CONFIRMED):
                self._safety.move(SafetyState.LANDED_CONFIRMED)
        elif result.status.acknowledged:
            self._tracking_status.setText("Landing command sent — not confirmed.")
            self._tracking_status.setStyleSheet("color: #b54708;")
        else:
            reason = (
                "The landing command timed out; the outcome is unknown."
                if result.status is CommandStatus.TIMEOUT
                else "The landing command could not be sent."
            )
            if self._safety.can_move(SafetyState.FAULT):
                self._safety.move(SafetyState.FAULT, reason=reason)
            self._tracking_status.setText(f"{reason} Use the phone app or Emergency Land.")
            self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 700;")
            widgets.show_error(self, "Land", reason)
        self._refresh_tracking(self._services.state.snapshot())

    def _on_tracking_land_failed(self, message: str) -> None:
        reason = f"The landing command failed: {message}"
        if self._safety.can_move(SafetyState.FAULT):
            self._safety.move(SafetyState.FAULT, reason=reason)
        self._tracking_status.setText(f"{reason} Use Emergency Land or the phone app.")
        self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 700;")
        widgets.show_error(self, "Land", reason)
        self._refresh_tracking(self._services.state.snapshot())

    def _disarm_for_safety(self, snapshot: AppStateSnapshot) -> None:
        """Arming does not survive landing, faults or a lost command channel."""
        if not snapshot.autonomy_armed:
            return
        if snapshot.safety_state not in (
            SafetyState.ARMED,
            SafetyState.FLYING_MANUAL,
            SafetyState.FLYING_TRACKING,
        ):
            self._services.state.update(autonomy_armed=False)

    def _refresh_tracking(self, snapshot: AppStateSnapshot) -> None:
        kind = self._tracking_kind()
        self._tracking_target_label.setText(
            f"Tracking detector: {DISPLAY_NAMES[kind]}"
            if kind is not None
            else "Tracking detector: select OpenCV or YOLO"
        )

        controller = self._tracking
        active = bool(controller is not None and controller.active)
        if snapshot.autonomy_armed and snapshot.safety_state is SafetyState.ARMED:
            self._arm_button.setText("Disarm autonomy")
            self._arm_button.setEnabled(True)
        else:
            self._arm_button.setText("Arm autonomy")
            self._arm_button.setEnabled(self._can_arm_reason(snapshot) == "")
        self._start_tracking_button.setEnabled(self._can_start_reason(snapshot) == "")
        self._stop_tracking_button.setEnabled(active)
        self._tracking_land_button.setEnabled(
            snapshot.safety_state
            in (SafetyState.FLYING_MANUAL, SafetyState.FLYING_TRACKING)
        )

        if active:
            self._tracking_status.setText(
                "Tracking active — yaw corrections only. Watch for obstacles yourself: "
                "tracking does not detect them."
            )
            self._tracking_status.setStyleSheet("color: #a12a2a; font-weight: 600;")
        elif self._tracking_alert:
            # The stop reason is set by _stop_tracking and stays visible.
            pass
        elif snapshot.safety_state in (
            SafetyState.LANDING_REQUESTED,
            SafetyState.LANDED_CONFIRMED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        ):
            # The landing/failure handler owns the status text for these states.
            pass
        elif snapshot.autonomy_armed:
            self._tracking_status.setText(
                "Autonomy armed. No command has been sent; take off with manual "
                "control, then press Start Tracking."
            )
            self._tracking_status.setStyleSheet("color: #b54708;")
        else:
            self._tracking_status.setText(
                "Autonomy disarmed. A successful dry run and an explicit Arm are required."
            )
            self._tracking_status.setStyleSheet("color: #5b6470;")

    def refresh_tracking(self) -> None:
        """Recompute the tracking controls from the current state."""
        self._refresh_tracking(self._services.state.snapshot())

    @property
    def tracking_controller(self) -> TrackingController | None:
        return self._tracking

    @property
    def arm_button(self) -> QPushButton:
        return self._arm_button

    @property
    def start_tracking_button(self) -> QPushButton:
        return self._start_tracking_button

    @property
    def stop_tracking_button(self) -> QPushButton:
        return self._stop_tracking_button

    @property
    def tracking_land_button(self) -> QPushButton:
        return self._tracking_land_button

    @property
    def tracking_status_text(self) -> str:
        return self._tracking_status.text()

    @property
    def tracking_detail_text(self) -> str:
        return self._tracking_detail.text()

    # -- rendering -----------------------------------------------------------

    def _visible_results(self) -> dict[DetectorKind, DetectionResult]:
        if self._mode == "comparison":
            return {
                kind: result
                for kind, result in self._results.items()
                if kind in _RESULT_KINDS
            }
        if isinstance(self._mode, DetectorKind) and self._mode in self._results:
            return {self._mode: self._results[self._mode]}
        return {}

    def _update_preview(self) -> None:
        frame = self._last_frame
        if frame is None:
            return
        self._preview.show_image(
            render_frame(frame, self._visible_results(), now=time.monotonic())
        )

    def _update_result_grid(self) -> None:
        for kind, row in self._result_rows.items():
            detector = self._services.detectors.get(kind)
            result = self._results.get(kind)
            if result is None:
                row.clear_values()
                row.set_status(self._idle_status(kind, detector), "idle")
                continue
            if result.failed:
                row.set_status("Error", "error")
                row.detail.setText(result.error or "")
            elif result.detections:
                row.set_status(f"{len(result.detections)} detection(s)", "ok")
                row.detail.setText(result.detections[0].label)
            else:
                row.set_status("No target", "warn")
                row.detail.setText("")
            row.latency.setText(
                f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "N/A"
            )
            row.confidence.setText(
                confidence_text(result) if not result.failed else "N/A"
            )
            row.age.setText(_age_text(self._services, kind, result))

    def _idle_status(self, kind: DetectorKind, detector: object) -> str:
        if detector is None:
            return "Not configured"
        if (
            kind is DetectorKind.OPENCV
            and isinstance(detector, OpenCvTargetDetector)
            and not detector.config.calibrated
        ):
            return "Not calibrated"
        if (
            kind in (DetectorKind.YOLO, DetectorKind.VLM)
            and isinstance(detector, (YoloDetector, OllamaVlmDetector))
            and not detector.ready
        ):
            return "No model loaded"
        return "Idle" if getattr(detector, "ready", False) else "Not loaded"

    def _detector_ready(self, kind: DetectorKind) -> bool:
        detector = self._services.detectors.get(kind)
        return bool(detector is not None and detector.ready)

    # -- workflow state ------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        self._refresh_workflow(snapshot)
        self._disarm_for_safety(snapshot)
        snapshot = self._services.state.snapshot()
        controller = self._tracking
        if controller is not None and controller.active:
            if snapshot.safety_state is not SafetyState.FLYING_TRACKING:
                self._abandon_tracking(
                    "The safety state changed; tracking stopped. The aircraft is "
                    "not landed."
                )
                snapshot = self._services.state.snapshot()
            elif not self._owns_video(snapshot):
                self._abandon_tracking(
                    "Live video is no longer active on this tab; tracking stopped. "
                    "The aircraft is not landed."
                )
                snapshot = self._services.state.snapshot()
        self._refresh_tracking(snapshot)

    def _refresh_workflow(self, snapshot: AppStateSnapshot) -> None:
        if (
            self._current_kind == "tello"
            and self._source is not None
            and not snapshot.drone_connected
        ):
            self.stop_source()
            self._status_pill.set_status("Tello disconnected — camera stopped", "error")
            self._workflow_detail.setText(
                "The connection to the aircraft was lost, so live video stopped. "
                "Reconnect before starting the camera again."
            )
        if not self._owns_video(snapshot):
            self._workflow_pill.set_status("No source", "idle")
            return
        if snapshot.dry_run_passed_kinds:
            passed = ", ".join(
                DISPLAY_NAMES.get(DetectorKind(value), value)
                for value in snapshot.dry_run_passed_kinds
            )
            self._workflow_pill.set_status(f"Ready: {passed}", "ok")
            return
        self._workflow_pill.set_status("Dry run required", "warn")

    # -- accessors used by tests --------------------------------------------

    @property
    def calibrate_button(self) -> QPushButton:
        return self._calibrate_button

    @property
    def yolo_button(self) -> QPushButton:
        return self._yolo_button

    @property
    def yolo_label(self) -> QLabel:
        return self._yolo_label

    def refresh_yolo_status(self) -> None:
        self._refresh_yolo_status()

    @property
    def vlm_button(self) -> QPushButton:
        return self._vlm_button

    @property
    def vlm_label(self) -> QLabel:
        return self._vlm_label

    def refresh_vlm_status(self) -> None:
        self._refresh_vlm_status()

    def refresh_detectors(self) -> None:
        """Re-read detector status after a profile load replaced them."""
        self._refresh_yolo_status()
        self._refresh_vlm_status()
        self._sync_vlm_poller()
        self._update_result_grid()

    @property
    def dry_run_button(self) -> QPushButton:
        return self._dry_run_button

    @property
    def workflow_detail(self) -> QLabel:
        return self._workflow_detail

    @property
    def mode_radios(self) -> dict[object, QRadioButton]:
        return dict(self._mode_radios)

    @property
    def results(self) -> dict[DetectorKind, DetectionResult]:
        return dict(self._results)

    @property
    def result_rows(self) -> dict[DetectorKind, _ResultRow]:
        return dict(self._result_rows)

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def source_combo(self) -> QComboBox:
        return self._source_combo

    @property
    def status_pill(self) -> widgets.StatusPill:
        return self._status_pill

    @property
    def preview(self) -> VideoView:
        return self._preview

    @property
    def source(self) -> VideoSource | None:
        return self._source

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame


def _error_result(frame: Frame, kind: DetectorKind, message: str) -> DetectionResult:
    return DetectionResult(
        detector_name=DISPLAY_NAMES[kind],
        kind=kind,
        frame_timestamp=frame.captured_at,
        processed_at=time.monotonic(),
        error=message,
    )


def _age_text(services: AppServices, kind: DetectorKind, result: DetectionResult) -> str:
    if kind is not DetectorKind.VLM:
        return "—"
    age = max(0.0, time.monotonic() - result.processed_at)
    detector = services.detectors.get(DetectorKind.VLM)
    interval = (
        detector.config.interval_s if isinstance(detector, OllamaVlmDetector) else 1.0
    )
    stale = " (stale)" if age > max(3.0, 3.0 * interval) else ""
    return f"{age:.1f} s old{stale}"


def _not_ready_reason(services: AppServices, kind: DetectorKind) -> str:
    detector = services.detectors.get(kind)
    if detector is None:
        return f"{DISPLAY_NAMES[kind]} is not configured"
    if (
        kind is DetectorKind.OPENCV
        and isinstance(detector, OpenCvTargetDetector)
        and not detector.config.calibrated
    ):
        return "OpenCV is not calibrated"
    if kind is DetectorKind.YOLO and isinstance(detector, YoloDetector):
        return "YOLO has no model loaded"
    return f"{DISPLAY_NAMES[kind]} is not ready"


def _dry_run_summary(
    passed: tuple[DetectorKind, ...],
    failed: tuple[DetectorKind, ...],
    missing: tuple[DetectorKind, ...],
) -> str:
    def names(kinds: tuple[DetectorKind, ...]) -> str:
        return ", ".join(DISPLAY_NAMES[kind] for kind in kinds)

    if not passed and not failed:
        return f"Dry run failed: no target found by {names(missing)}."
    parts = []
    if passed:
        parts.append(f"passed: {names(passed)}")
    if failed:
        parts.append(f"failed: {names(failed)}")
    if missing:
        parts.append(f"no target: {names(missing)}")
    prefix = "Dry run partial" if passed and (failed or missing) else "Dry run"
    return f"{prefix} — " + "; ".join(parts) + "."


def _mode_tooltip(mode: object) -> str:
    if mode == DetectorKind.VLM:
        return "Advisory analysis about once per second; never used for flight."
    if mode == "comparison":
        return "OpenCV and YOLO on the same frame, plus the latest VLM answer."
    return "Runs on every available frame in a background job."
