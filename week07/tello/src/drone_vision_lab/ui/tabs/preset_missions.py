"""Preset Flight Missions tab.

Preset programs are fixed, multistep sequences: a takeoff, any number of holds,
turns and translations, and a landing. The operator chooses a program, reads
every step before anything is sent, and executes it only after an explicit
confirmation.

Like the editable mission, the program runs on a background worker and every
command is gated by the same conservative limits and telemetry checks. **Stop
Program** stops issuing new steps and does not land the aircraft; the command
already in flight finishes. **Emergency Land** stays a separate top-bar action.

A program with an **observation** step additionally owns the Tello camera. The
camera starts before takeoff and must be live first; YOLO runs on the decoded
frames and the configured target class is drawn in a green box. The observation
sends no flight command; the runner's every-5-s ``command`` keepalive only stops
the Tello landing itself after 15 s without a command. The camera is
display-only: the boxes never arm, steer or land anything, and the only camera
commands are ``streamon``/``streamoff``. When the operator lands with Emergency
Land, the safety-state change stops the program before its own landing step, so
no second ``land`` is sent; the local camera receiver is closed without sending
``streamoff`` into the landing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import CONSERVATIVE_LIMITS, SafetyLimits
from ...container import AppServices
from ...domain import CommandStatus, DetectionResult, DetectorKind, Frame
from ...interfaces import ObjectDetector, VideoSource, VideoSourceStatus
from ...mission import MissionOutcome, MissionResult
from ...preset_missions import (
    PRESET_PROGRAMS,
    PresetIssue,
    PresetProgram,
    PresetRunner,
    estimated_preset_duration_s,
    validate_preset,
)
from ...state import AppStateSnapshot, SafetyState
from ...workers import CallableRunner
from .. import widgets
from ..guidance_overlay import render_target_overlay
from ..video_session import VideoSession
from ..video_view import VideoView
from ..yolo_settings_dialog import YoloSettingsDialog

__all__ = ["PresetMissionsTab"]

_log = logging.getLogger(__name__)

_VIDEO_OWNER = "preset_missions"
_MUTED = "color: #5b6470;"
_RECONNECT_HINT = (
    "Execute stays disabled until the safety state is cleared: once you have "
    "confirmed the aircraft is on the ground, press Reconnect on the Drone "
    "Control tab."
)
_CAMERA_STATUS_MAP = {
    VideoSourceStatus.OFFLINE: ("Camera idle", "idle"),
    VideoSourceStatus.LIVE: ("Live", "ok"),
    VideoSourceStatus.STALE: ("Stale", "warn"),
    VideoSourceStatus.ENDED: ("Ended", "warn"),
    VideoSourceStatus.ERROR: ("Camera error", "error"),
}

_GROUNDED_STATES = frozenset(
    {
        SafetyState.CONNECTED_GROUNDED,
        SafetyState.CAMERA_READY,
        SafetyState.CALIBRATED,
        SafetyState.DRY_RUN_PASSED,
        SafetyState.ARMED,
        SafetyState.LANDED_CONFIRMED,
    }
)


class PresetMissionsTab(QWidget):
    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
        *,
        limits: SafetyLimits = CONSERVATIVE_LIMITS,
        programs: tuple[PresetProgram, ...] = PRESET_PROGRAMS,
        source_factory: Callable[[str, str | None], VideoSource] | None = None,
    ) -> None:
        super().__init__(parent)
        if not programs:
            raise ValueError("At least one preset program is required")
        self._services = services
        self._limits = limits
        self._programs = programs
        self._program = programs[0]
        self._issues: tuple[PresetIssue, ...] = ()
        self._runner: PresetRunner | None = None
        self._running = False
        self._pre_program_state: SafetyState | None = None
        self._pending_start: AppStateSnapshot | None = None
        self._external_stop_reason: str | None = None
        self._last_frame: Frame | None = None
        self._last_result: DetectionResult | None = None
        self._pending_seq: int | None = None
        self._pending_frame: Frame | None = None
        self._execute_reason: str | None = None
        """Last Execute-button tooltip, so a change of gate is logged once."""

        self._program_runner = CallableRunner(self)
        self._program_runner.finished.connect(self._on_program_finished)
        self._program_runner.failed.connect(self._on_program_failed)

        self._session = VideoSession(
            services,
            owner=_VIDEO_OWNER,
            source_factory=source_factory,
            parent=self,
        )
        self._session.starting.connect(self._on_camera_starting)
        self._session.opened.connect(self._on_camera_opened)
        self._session.closed.connect(self._on_camera_closed)
        self._session.failed.connect(self._on_camera_failed)
        self._session.frame_ready.connect(self._on_frame)
        self._session.status_changed.connect(self._on_camera_status)
        self._session.pump_failed.connect(self._on_pump_failed)

        self._analysis_runner = CallableRunner(self)
        self._analysis_runner.finished.connect(self._on_analysis_finished)
        self._analysis_runner.failed.connect(self._on_analysis_failed)

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(500)
        self._health_timer.timeout.connect(self._refresh_health)

        self._build()
        self._select_program(0)
        self.refresh_detector_status()
        self._health_timer.start()
        self.apply_state(services.state.snapshot())

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(widgets.SectionTitle("Preset Flight Missions"))
        intro = QLabel(
            "A fixed, multistep program. Choose one, read every step, then execute "
            "it only after an explicit confirmation. Preset programs are read-only; "
            "use Flight Missions to edit a six-segment loop."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5b6470;")
        layout.addWidget(intro)

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Program:"))
        self._program_combo = QComboBox()
        for program in self._programs:
            self._program_combo.addItem(program.title)
        self._program_combo.setToolTip("Choose the preset program to preview or fly.")
        self._program_combo.currentIndexChanged.connect(self._on_program_changed)
        chooser.addWidget(self._program_combo, 1)
        layout.addLayout(chooser)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        layout.addWidget(self._build_steps_table(), 1)

        self._note_label = QLabel("")
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet("color: #b54708;")
        layout.addWidget(self._note_label)

        self._camera_group = self._build_camera_group()
        self._camera_group.setVisible(False)
        layout.addWidget(self._camera_group)

        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        layout.addWidget(self._validation_label)

        self._status_label = QLabel("No preset program has run in this session.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        buttons = QHBoxLayout()
        self._preview_button = QPushButton("Preview")
        self._preview_button.setToolTip(
            "Show every step and the time estimate. Sends no command."
        )
        self._preview_button.clicked.connect(self._show_preview)
        self._execute_button = QPushButton("Execute program")
        self._execute_button.setToolTip(
            "Fly the selected program after an explicit confirmation. "
            "The aircraft takes off."
        )
        self._execute_button.clicked.connect(self._execute_program)
        self._stop_button = QPushButton("Stop program")
        self._stop_button.setToolTip(
            "Stop issuing new steps. This does not land the aircraft and does not "
            "send anything; the command already in flight finishes."
        )
        self._stop_button.clicked.connect(self._stop_program)
        buttons.addWidget(self._preview_button)
        buttons.addWidget(self._execute_button)
        buttons.addWidget(self._stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(self._build_limits_note())

    def _build_camera_group(self) -> QWidget:
        group = QGroupBox("Camera and YOLO target box")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self._camera_pill = widgets.StatusPill("Camera idle")
        self._camera_label = QLabel(
            "The camera starts with the program, before takeoff."
        )
        self._camera_label.setWordWrap(True)
        self._camera_label.setStyleSheet(_MUTED)
        self._settings_button = QPushButton("YOLO settings…")
        self._settings_button.setToolTip(
            "Choose local weights and the target class. The program will not take "
            "off without a loaded YOLO model."
        )
        self._settings_button.clicked.connect(self._open_settings)
        row.addWidget(self._camera_pill)
        row.addWidget(self._camera_label, 1)
        row.addWidget(self._settings_button)
        layout.addLayout(row)

        self._preview = VideoView("The camera starts before takeoff")
        self._preview.setMaximumHeight(280)
        layout.addWidget(self._preview)

        self._target_label = QLabel("Target class: apple (default)")
        self._target_label.setWordWrap(True)
        self._target_label.setStyleSheet(_MUTED)
        layout.addWidget(self._target_label)

        self._detection_label = QLabel("No detection yet")
        self._detection_label.setWordWrap(True)
        self._detection_label.setStyleSheet(_MUTED)
        layout.addWidget(self._detection_label)

        self._age_label = QLabel("")
        self._age_label.setStyleSheet(_MUTED)
        layout.addWidget(self._age_label)

        notice = QLabel(
            "Display only. The green box marks the configured YOLO class on the "
            "aircraft camera; it never arms, steers or lands anything. The camera "
            "is exclusive: stop the Computer Vision Lab, Tello Flight or Object "
            "detection source first. Only streamon/streamoff are sent."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(_MUTED)
        layout.addWidget(notice)
        return group

    def _build_steps_table(self) -> QWidget:
        group = QGroupBox("Program steps")
        layout = QVBoxLayout(group)
        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Step", "Action", "SDK command"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)
        return group

    def _build_limits_note(self) -> QWidget:
        limits = self._limits
        note = QLabel(
            "Conservative limits: "
            f"altitude ≤ {limits.max_altitude_cm} cm, "
            f"segment distance ≤ {limits.max_segment_distance_cm} cm, "
            f"speed ≤ {limits.max_speed_cm_s} cm/s, "
            f"duration ≤ {limits.max_mission_duration_s} s, "
            f"takeoff battery ≥ {limits.min_battery_percent_for_takeoff} %.\n\n"
            "The Tello SDK accepts movement from 20 cm to 500 cm. A shorter leg "
            "cannot be sent; a preset that asks for less is rejected during "
            "validation. A standard Tello has no reliable indoor global position "
            "estimate; a preset does not return the aircraft to its exact start "
            "point."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5b6470;")
        return note

    # -- program selection ---------------------------------------------------

    def _on_program_changed(self, index: int) -> None:
        if 0 <= index < len(self._programs):
            self._select_program(index)

    def _select_program(self, index: int) -> None:
        self._program = self._programs[index]
        self._summary_label.setText(self._program.summary)
        self._note_label.setText(self._program.note)
        self._note_label.setVisible(bool(self._program.note))
        self._camera_group.setVisible(self._program.has_observation)
        if not self._session.active and self._pending_start is None:
            self._reset_detection()
        self._fill_steps()
        self._refresh_validation()

    def _fill_steps(self) -> None:
        steps = self._program.steps
        self._table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            command = step.sdk_command
            self._table.setItem(row, 0, QTableWidgetItem(f"{row + 1}. {step.detail}"))
            self._table.setItem(row, 1, QTableWidgetItem(step.action.label))
            self._table.setItem(
                row,
                2,
                QTableWidgetItem("— (wait; keepalive only)" if command is None else command),
            )
        self._table.resizeRowsToContents()

    def _program_lines(self) -> str:
        lines = []
        for index, step in enumerate(self._program.steps, start=1):
            command = step.sdk_command
            command_note = (
                "keepalive only, no flight command"
                if command is None
                else f"command: {command}"
            )
            lines.append(f"{index}. {step.action.label}: {step.detail} ({command_note})")
        return "\n".join(lines)

    # -- validation ----------------------------------------------------------

    def _refresh_validation(self) -> None:
        self._issues = validate_preset(self._program, self._limits)
        if self._issues:
            self._validation_label.setText(
                "The program is not flyable:\n"
                + "\n".join(issue.describe() for issue in self._issues)
            )
            self._validation_label.setStyleSheet("color: #b42318;")
        else:
            self._validation_label.setText(
                "Program is within limits. Rough estimate: "
                f"{estimated_preset_duration_s(self._program, self._limits):.1f} s "
                "— not a promise of flight time."
            )
            self._validation_label.setStyleSheet("color: #1a7f37;")
        self.apply_state(self._services.state.snapshot())

    # -- preview -------------------------------------------------------------

    def _show_preview(self) -> None:
        self._refresh_validation()
        problem = (
            "\n\nBlocking issues:\n"
            + "\n".join(issue.describe() for issue in self._issues)
            if self._issues
            else ""
        )
        note = f"\n\n{self._program.note}" if self._program.note else ""
        QMessageBox.information(
            self,
            "Preset program preview",
            f"{self._program.title}\n\n{self._program_lines()}\n\n"
            f"Rough estimate: "
            f"{estimated_preset_duration_s(self._program, self._limits):.1f} s."
            f"{note}{problem}\n\nPreview sends no command.",
        )

    # -- execution -----------------------------------------------------------

    def _execute_program(self) -> None:
        if self._running:
            return
        _log.info(
            "Preset execute requested",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "steps": len(self._program.steps),
                }
            },
        )
        self._refresh_validation()
        if self._issues:
            reason = "The preset is outside the safety limits:\n" + "\n".join(
                issue.describe() for issue in self._issues
            )
            _log.warning(
                "Preset not started: validation failed",
                extra={"context": {"program": self._program.program_id}},
            )
            widgets.show_error(self, "Program not started", reason)
            return
        snapshot = self._services.state.snapshot()
        if not snapshot.drone_connected:
            _log.warning(
                "Preset not started: no aircraft connection",
                extra={"context": {"program": self._program.program_id}},
            )
            widgets.show_error(self, "Program not started", "Connect to the aircraft first.")
            return
        if snapshot.safety_state is SafetyState.LANDING_REQUESTED:
            # A landing was sent but telemetry never confirmed touchdown. The
            # aircraft may be on the ground or still descending; "already
            # airborne" would overstate what the app knows.
            _log.warning(
                "Preset not started: a landing request is not confirmed",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "safety_state": snapshot.safety_state.value,
                    }
                },
            )
            widgets.show_error(
                self,
                "Program not started",
                "A landing was requested but has not been confirmed, so the aircraft "
                "may still be airborne. Reconnect and confirm it is on the ground "
                "before starting a program; use Emergency Land if it is still flying.",
            )
            return
        if snapshot.safety_state.in_flight:
            _log.warning(
                "Preset not started: the aircraft is already airborne",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "safety_state": snapshot.safety_state.value,
                    }
                },
            )
            widgets.show_error(
                self,
                "Program not started",
                "The aircraft is already airborne. Land it before starting a program.",
            )
            return
        if snapshot.safety_state not in _GROUNDED_STATES:
            # FAULT is reachable after a program whose landing was not
            # confirmed. "Not in flight" is not the same as "known to be on
            # the ground", and a takeoff from an unknown state could collide
            # with an aircraft that is still in the air.
            _log.warning(
                "Preset not started: the aircraft is not in a grounded state",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "safety_state": snapshot.safety_state.value,
                    }
                },
            )
            widgets.show_error(
                self,
                "Program not started",
                f"The aircraft's last safety state is "
                f"'{snapshot.safety_state.display_name}'. An earlier program did not "
                "finish cleanly, so the aircraft may still be airborne. Reconnect "
                "and confirm it is on the ground before starting a program; use "
                "Emergency Land if it is still flying.",
            )
            return

        observation_problem = (
            self._observation_problem() if self._program.has_observation else None
        )
        if observation_problem is not None:
            _log.warning(
                "Preset not started: the camera or detector is not ready",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "reason": observation_problem,
                    }
                },
            )
            widgets.show_error(self, "Program not started", observation_problem)
            return

        confirmed = self._confirm_execution()
        _log.info(
            "Preset confirmation answered",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "confirmed": confirmed,
                }
            },
        )
        if not confirmed:
            return

        if self._program.has_observation:
            self._start_camera_then_program(snapshot)
        else:
            self._begin_run(snapshot)

    def _start_camera_then_program(self, snapshot: AppStateSnapshot) -> None:
        """Open the Tello camera first; the takeoff waits for a live source.

        The camera is what the observation is for. Starting it before takeoff
        means a broken camera or a busy UDP port stops the program on the
        ground, with no takeoff command sent.
        """
        self._pending_start = snapshot
        self._external_stop_reason = None
        self._reset_detection()
        self._status_label.setText(
            "Starting the Tello camera before takeoff. The program starts only "
            "after the camera is live; if it fails, no takeoff command is sent."
        )
        _log.info(
            "Preset observation camera starting",
            extra={"context": {"program": self._program.program_id}},
        )
        self.apply_state(self._services.state.snapshot())
        if self._session.start("tello"):
            return
        if self._pending_start is not None:
            # A refusal that did not emit ``failed``; never start on silence.
            self._pending_start = None
            _log.warning(
                "Preset observation camera did not start; no takeoff was sent",
                extra={"context": {"program": self._program.program_id}},
            )
            self._status_label.setText(
                "The camera could not be started, so the program was not started "
                "and no takeoff command was sent."
            )
            self.apply_state(self._services.state.snapshot())

    def _begin_run(self, snapshot: AppStateSnapshot) -> None:
        self._runner = PresetRunner(
            self._services.drone,
            self._program,
            limits=self._limits,
            telemetry=self._services.drone.telemetry,
            telemetry_max_age_s=getattr(
                self._services.drone, "telemetry_max_age_s", None
            ),
        )
        self._pre_program_state = snapshot.safety_state
        self._running = True
        self._external_stop_reason = None
        # Reserve the aircraft for the program so manual input cannot also send
        # commands while the runner is active.
        self._services.state.update(safety_state=SafetyState.FLYING_MISSION, last_error=None)
        self._status_label.setText(
            "Preset program running. Stop Program stops new steps; it does not land "
            "the aircraft by itself."
        )
        self.apply_state(self._services.state.snapshot())
        _log.info(
            "Preset program started",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "previous_state": (
                        self._pre_program_state.value
                        if self._pre_program_state is not None
                        else None
                    ),
                }
            },
        )
        runner = self._runner
        if not self._program_runner.submit(
            lambda: runner.run(operator_confirmed=True)
        ):
            _log.warning("Preset not started: another background job is still running")
            self._running = False
            self._runner = None
            self._stop_camera_after_run(None)
            self._restore_grounded_state()
            self._status_label.setText("Another background job is still running.")

    def _confirm_execution(self) -> bool:
        flight_note = (
            "The propellers will spin and the aircraft will fly the program below."
            if self._services.drone_mode == "tello"
            else "This is the simulated aircraft; the program is simulated and no "
            "propellers will spin."
        )
        note = f"\n\n{self._program.note}" if self._program.note else ""
        answer = QMessageBox.warning(
            self,
            "Execute preset program",
            f"{flight_note}\n\n{self._program.title}\n\n{self._program_lines()}\n\n"
            f"Rough estimate: "
            f"{estimated_preset_duration_s(self._program, self._limits):.1f} s."
            f"{note}\n\n"
            "The aircraft does not return to its exact start point. Keep it in sight, "
            "keep the area clear, and confirm the phone app is not controlling.\n\n"
            "Start the program now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return widgets.is_yes(answer)

    def _stop_program(self) -> None:
        if self._pending_start is not None:
            # The camera is still starting and no takeoff has been sent.
            self._pending_start = None
            self._stop_button.setEnabled(False)
            self._session.stop(stop_stream=False)
            self._status_label.setText(
                "Camera start cancelled before takeoff; no takeoff command was sent."
            )
            self.apply_state(self._services.state.snapshot())
            return
        if self._runner is None or not self._running:
            return
        self._stop_button.setEnabled(False)
        _log.warning(
            "Preset stop requested; no landing command is issued by the stop",
            extra={"context": {"program": self._program.program_id}},
        )
        self._runner.cancel("Stopped by the operator.")
        self._status_label.setText(
            "Stop requested. No new steps will be sent and no landing command is "
            "issued by Stop Program; the command already in flight finishes. The "
            "aircraft may still be airborne — use Emergency Land if needed."
        )

    def _on_program_finished(self, result: object) -> None:
        if not isinstance(result, MissionResult):
            return
        self._running = False
        self._runner = None
        self._stop_camera_after_run(result)
        self._apply_outcome(result)
        self.apply_state(self._services.state.snapshot())

    def _on_program_failed(self, message: str) -> None:
        _log.error(
            "Preset worker failed",
            extra={"context": {"program": self._program.program_id, "error": message}},
        )
        self._running = False
        self._runner = None
        self._external_stop_reason = None
        self._stop_camera_after_run(None)
        self._services.state.update(
            safety_state=SafetyState.FAULT,
            last_error=message,
        )
        self._status_label.setText(
            f"The preset worker failed: {message}. The aircraft may still be "
            "airborne; use Emergency Land if needed."
        )
        widgets.show_error(self, "Preset program failed", message)
        self.apply_state(self._services.state.snapshot())

    def _apply_outcome(self, result: MissionResult) -> None:
        sent = len(result.commands)
        acknowledged = sum(
            1 for command in result.commands if command.status is CommandStatus.CONFIRMED
        )
        sent_acknowledged = sum(1 for command in result.commands if command.status.acknowledged)
        detail = (
            f"{result.reason} Commands: {sent} attempted, {sent_acknowledged} acknowledged"
        )
        if acknowledged:
            detail += f", {acknowledged} independently confirmed"
        detail += "."
        # An acknowledgement is not evidence of landing, but the adapter
        # reports CONFIRMED only when telemetry received *after* the
        # acknowledgement reported height 0. That is the independent
        # evidence the landing contract requires, so it may leave
        # LANDING_REQUESTED; an acknowledged-only landing may not.
        landing_confirmed = any(
            command.command == "land" and command.status is CommandStatus.CONFIRMED
            for command in result.commands
        )
        _log.log(
            logging.INFO
            if result.outcome is MissionOutcome.COMPLETED
            else logging.WARNING,
            "Preset outcome applied",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "outcome": result.outcome.value,
                    "commands_attempted": sent,
                    "commands_acknowledged": sent_acknowledged,
                    "landing_confirmed": landing_confirmed,
                }
            },
        )

        if self._external_stop_reason is not None:
            # Emergency Land, Land, a disconnect or a fault stopped the program.
            # That event owns the safety state; writing CANCELLED bookkeeping here
            # would downgrade it (for example LANDING_REQUESTED back to manual
            # flight) and imply a landing state the app cannot prove.
            self._status_label.setText(
                f"{self._external_stop_reason} The program's own landing step was "
                "not sent after that."
            )
            self._external_stop_reason = None
            return

        if result.outcome is MissionOutcome.COMPLETED:
            self._services.state.update(
                safety_state=SafetyState.LANDING_REQUESTED,
                last_error=None,
            )
            if landing_confirmed:
                self._services.state.update(safety_state=SafetyState.LANDED_CONFIRMED)
                # The reason already says the landing was confirmed by telemetry;
                # repeating that sentence here read as two separate claims.
                self._status_label.setText(detail + " The program is approximate.")
            else:
                self._status_label.setText(
                    detail
                    + " Landing still needs visual confirmation; the program is approximate. "
                    + _RECONNECT_HINT
                )
        elif result.outcome is MissionOutcome.CANCELLED:
            if any(command.command == "takeoff" and command.ok for command in result.commands):
                self._services.state.update(safety_state=SafetyState.FLYING_MANUAL)
            else:
                self._restore_grounded_state()
            self._status_label.setText(detail + " No landing command was issued by the stop.")
        elif result.outcome is MissionOutcome.ABORTED:
            self._services.state.update(
                safety_state=SafetyState.FAULT,
                last_error=result.reason,
            )
            self._status_label.setText(detail + " " + _RECONNECT_HINT)
        else:  # REJECTED
            self._restore_grounded_state()
            self._status_label.setText(detail)
            widgets.show_error(self, "Program not started", result.reason)

    def _restore_grounded_state(self) -> None:
        restore = self._pre_program_state or SafetyState.CONNECTED_GROUNDED
        if restore not in _GROUNDED_STATES:
            restore = SafetyState.CONNECTED_GROUNDED
        self._services.state.update(safety_state=restore)

    # -- camera and target detection -----------------------------------------

    def _observation_problem(
        self, snapshot: AppStateSnapshot | None = None
    ) -> str | None:
        """Why the observation cannot start, or ``None`` when everything is ready."""
        if self._services.drone_mode != "tello":
            return (
                "This program needs the live Tello camera and a YOLO model, so it "
                "runs in hardware mode only. Start the application with --tello on "
                "the aircraft's Wi-Fi network."
            )
        if self._object_detector() is None:
            return (
                "Load local YOLO weights through YOLO settings before starting this "
                "program. It will not take off without target detection."
            )
        snapshot = snapshot or self._services.state.snapshot()
        if snapshot.video_active and snapshot.video_owner != _VIDEO_OWNER:
            return (
                "Another tab is using the camera. Stop its source before starting "
                "this program; two sockets cannot bind the Tello video port."
            )
        return None

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
            self._target_label.setText(
                "YOLO: no model loaded. Open YOLO settings to choose local weights; "
                "this program will not take off without target detection. Target "
                "class: apple (default)."
            )
        else:
            label = self._configured_label(detector)
            note = "" if label == "apple" else " — this program's summary says apple"
            self._target_label.setText(
                f"YOLO: {detector.name}. Target class: {label}{note}."
            )
        self.apply_state(self._services.state.snapshot())

    def _open_settings(self) -> None:
        dialog = YoloSettingsDialog(self._services, self._last_frame, self)
        dialog.exec()
        self.refresh_detector_status()

    def _on_camera_starting(self, kind: str) -> None:
        self._camera_pill.set_status("Starting camera…", "warn")
        self._camera_label.setText("Starting the Tello camera; takeoff has not been sent.")
        self.apply_state(self._services.state.snapshot())

    def _on_camera_opened(self, source: VideoSource, kind: str) -> None:
        if self._pending_start is None:
            # The start was cancelled by the operator or a safety change while
            # streamon was in flight. Release the receiver without a flight
            # command; do not take off.
            if self._session.active:
                self._session.stop(stop_stream=False)
            return
        snapshot = self._pending_start
        self._pending_start = None
        self._camera_pill.set_status("Live", "ok", source.description)
        self._camera_label.setText(source.description)
        self._begin_run(snapshot)

    def _on_camera_closed(self) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._preview.clear()
        self._camera_pill.set_status("Camera idle", "idle")
        self._camera_label.setText("The camera is not running.")

    def _on_camera_failed(self, title: str, message: str) -> None:
        self._camera_pill.set_status("Camera error", "error")
        if self._pending_start is not None:
            self._pending_start = None
            _log.warning(
                "Preset observation camera failed before takeoff",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "error": message,
                    }
                },
            )
            self._status_label.setText(
                "The camera failed to start, so the program was not started and no "
                "takeoff command was sent."
            )
            self.apply_state(self._services.state.snapshot())
        widgets.show_error(self, title, message)

    def _on_camera_status(
        self, status: VideoSourceStatus, seq: int | None = None
    ) -> None:
        if not self._session.is_current(seq):
            return
        text, level = _CAMERA_STATUS_MAP.get(status, ("Camera", "idle"))
        self._camera_pill.set_status(text, level, self._session.source_description)

    def _on_pump_failed(self, message: str, seq: int | None = None) -> None:
        if not self._session.is_current(seq):
            return
        # The video pipeline died. Keep the program and its fallback landing:
        # cancelling now would leave the aircraft hovering with no landing step.
        self._session.stop(stop_stream=False)
        self._camera_pill.set_status("Video lost", "error")
        self._camera_label.setText("The camera video stopped.")
        self._status_label.setText(
            "The camera video failed. The program continues and sends its landing "
            "at the end of the observation; press EMERGENCY LAND to bring the "
            "aircraft down now. No landing is confirmed by this."
        )
        widgets.show_error(
            self,
            "Camera failed",
            f"{message}\n\nThe aircraft is not steered by the camera. The program "
            "keeps running and lands at the end of the observation unless you press "
            "EMERGENCY LAND.",
        )

    # -- frames --------------------------------------------------------------

    def _on_frame(self, frame: Frame, seq: int | None = None) -> None:
        if not self._session.is_current(seq) or not isinstance(frame, Frame):
            return
        self._last_frame = frame
        detector = self._object_detector()
        if detector is None or not self._program.has_observation:
            self._preview.show_frame(frame)
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
        self._preview.show_image(render_target_overlay(frame, result))
        self._update_detection_label(result)
        if result.failed:
            _log.warning(
                "Preset observation detection failed",
                extra={"context": {"program": self._program.program_id,
                                   "error": result.error}},
            )

    def _on_analysis_failed(self, message: str) -> None:
        seq = self._pending_seq
        self._pending_seq = None
        self._pending_frame = None
        if seq is not None and not self._session.is_current(seq):
            return
        self._last_result = None
        self._detection_label.setText(
            f"Detection failed: {message}. No box is drawn; the aircraft is not "
            "steered by the camera."
        )

    def _update_detection_label(self, result: DetectionResult) -> None:
        if result.failed:
            self._detection_label.setText(
                f"Detection failed: {result.error}. No box is drawn; the aircraft "
                "is not steered by the camera."
            )
            return
        if not result.detections:
            self._detection_label.setText(
                f"No {self._target_label_name()} detected. Hold it in view of the "
                "camera; the aircraft hovers on its own and may drift."
            )
            return
        best = max(
            result.detections, key=lambda detection: detection.confidence or 0.0
        )
        confidence = (
            f" — confidence {best.confidence:.2f}"
            if best.confidence is not None
            else ""
        )
        self._detection_label.setText(
            f"{best.label} recognized in {len(result.detections)} box(es)"
            f"{confidence}. The green box is display only."
        )

    def _target_label_name(self) -> str:
        detector = self._object_detector()
        return self._configured_label(detector) if detector is not None else "apple"

    def _refresh_health(self) -> None:
        if not self._camera_group.isVisible():
            return
        result = self._last_result
        if result is None:
            return
        age = max(0.0, time.monotonic() - result.processed_at)
        self._age_label.setText(
            f"Last inference {age:.1f} s ago; boxes are display only."
        )

    def _reset_detection(self) -> None:
        self._pending_seq = None
        self._pending_frame = None
        self._last_frame = None
        self._last_result = None
        self._preview.clear()
        self._camera_pill.set_status("Camera idle", "idle")
        self._camera_label.setText("The camera is not running.")
        self._detection_label.setText("No detection yet")
        self._age_label.setText("")

    def _stop_camera_after_run(self, result: MissionResult | None) -> None:
        """Close the camera without racing a landing with ``streamoff``.

        Once a takeoff command may have been sent, the aircraft can be airborne
        or landing; the local receiver is closed and ``streamoff`` is left out.
        """
        if not (self._session.active or self._session.busy):
            return
        attempted_takeoff = result is not None and any(
            command.command == "takeoff" for command in result.commands
        )
        self._session.stop(stop_stream=not attempted_takeoff)

    # -- safety-state driven cancellation ------------------------------------

    def _handle_state_change(self, snapshot: AppStateSnapshot) -> None:
        state = snapshot.safety_state
        if self._pending_start is not None and (
            not snapshot.drone_connected or state not in _GROUNDED_STATES
        ):
            self._pending_start = None
            reason = self._safety_change_text(state, snapshot)
            _log.warning(
                "Preset start cancelled by a safety change before takeoff",
                extra={"context": {"program": self._program.program_id,
                                   "safety_state": state.value}},
            )
            self._session.stop(stop_stream=not state.in_flight)
            self._status_label.setText(
                f"{reason} The camera was stopped and no takeoff command was sent."
            )
        if (
            self._running
            and state is not SafetyState.FLYING_MISSION
            and self._external_stop_reason is None
        ):
            self._cancel_for_safety(state, snapshot)

    def _cancel_for_safety(
        self, state: SafetyState, snapshot: AppStateSnapshot
    ) -> None:
        runner = self._runner
        if runner is None:
            self._running = False
            return
        reason = self._safety_change_text(state, snapshot)
        self._external_stop_reason = reason
        _log.warning(
            "Preset program stopped by a safety change",
            extra={
                "context": {
                    "program": self._program.program_id,
                    "safety_state": state.value,
                }
            },
        )
        runner.cancel(reason)
        self._status_label.setText(reason)
        if self._session.active or self._session.busy:
            # The aircraft may be landing: close the local receiver and do not
            # send streamoff while the landing is in progress.
            self._session.stop(stop_stream=False)

    @staticmethod
    def _safety_change_text(
        state: SafetyState, snapshot: AppStateSnapshot
    ) -> str:
        if not snapshot.drone_connected or state is SafetyState.COMMUNICATION_LOST:
            return (
                "Communication with the aircraft was lost, so the program was "
                "stopped. The laptop cannot send a landing command."
            )
        if state is SafetyState.LANDING_REQUESTED:
            return (
                "A landing was requested (Emergency Land or Land), so the program "
                "was stopped before its own landing step."
            )
        if state is SafetyState.LANDED_CONFIRMED:
            return (
                "Telemetry reported the aircraft on the ground, so the program was "
                "stopped."
            )
        if state is SafetyState.FAULT:
            return (
                "The safety state became FAULT, so the program was stopped. The "
                "aircraft may still be airborne — use Emergency Land or the phone "
                "app."
            )
        return (
            f"The safety state changed to '{state.display_name}', so the program was "
            "stopped."
        )

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        self._handle_state_change(snapshot)
        connected = snapshot.drone_connected
        in_flight = snapshot.safety_state.in_flight
        grounded = snapshot.safety_state in _GROUNDED_STATES
        issues = self._issues
        busy = self._running or self._pending_start is not None
        observation_problem = (
            self._observation_problem(snapshot)
            if self._program.has_observation
            else None
        )
        enabled = (
            connected
            and grounded
            and not busy
            and not issues
            and observation_problem is None
        )
        self._execute_button.setEnabled(enabled)
        if not connected:
            tooltip = "Connect to the aircraft before executing a preset program."
        elif snapshot.safety_state is SafetyState.LANDING_REQUESTED:
            # In flight by the state machine, but "already airborne" is not
            # what the app knows: the landing was requested and unconfirmed.
            tooltip = (
                "A landing was requested but is not confirmed, so the aircraft may "
                "still be airborne. Reconnect and confirm it is on the ground."
            )
        elif in_flight:
            tooltip = "The aircraft is already airborne. Land it before starting a program."
        elif not grounded:
            tooltip = (
                "The aircraft's last state is not a confirmed grounded state. "
                "Reconnect and confirm it is on the ground before starting a program."
            )
        elif issues:
            tooltip = "Fix the blocking validation issues first."
        elif self._running:
            tooltip = "A preset program is already running."
        elif self._pending_start is not None:
            tooltip = "The camera is starting; the program starts after it is live."
        elif observation_problem is not None:
            tooltip = observation_problem
        else:
            tooltip = (
                "Fly the selected program after an explicit confirmation. "
                "The aircraft takes off."
            )
        self._execute_button.setToolTip(tooltip)
        if tooltip != self._execute_reason:
            # Log only a change of gate: apply_state also runs on every
            # telemetry update, and the disabled button cannot be clicked to
            # leave a trail of its own.
            self._execute_reason = tooltip
            _log.info(
                "Preset execute availability changed",
                extra={
                    "context": {
                        "program": self._program.program_id,
                        "execute_enabled": enabled,
                        "gate": None if enabled else tooltip,
                    }
                },
            )
        self._stop_button.setEnabled(busy)
        self._preview_button.setEnabled(not busy)
        self._program_combo.setEnabled(not busy)

    def shutdown(self) -> None:
        self._health_timer.stop()
        if self._runner is not None:
            self._runner.cancel("The application is closing.")
        self._pending_start = None
        self._session.shutdown()

    # -- test hooks ----------------------------------------------------------

    @property
    def program(self) -> PresetProgram:
        return self._program

    @property
    def program_combo(self) -> QComboBox:
        return self._program_combo

    @property
    def steps_table(self) -> QTableWidget:
        return self._table

    @property
    def validation_label_text(self) -> str:
        return self._validation_label.text()

    @property
    def status_text(self) -> str:
        return self._status_label.text()

    @property
    def note_text(self) -> str:
        return self._note_label.text()

    @property
    def issues(self) -> tuple[PresetIssue, ...]:
        return self._issues

    @property
    def execute_button(self) -> QPushButton:
        return self._execute_button

    @property
    def stop_button(self) -> QPushButton:
        return self._stop_button

    @property
    def session(self) -> VideoSession:
        return self._session

    @property
    def camera_group(self) -> QWidget:
        return self._camera_group

    @property
    def preview(self) -> VideoView:
        return self._preview

    @property
    def settings_button(self) -> QPushButton:
        return self._settings_button

    @property
    def target_label(self) -> QLabel:
        return self._target_label

    @property
    def detection_label(self) -> QLabel:
        return self._detection_label

    @property
    def last_frame(self) -> Frame | None:
        return self._last_frame

    @property
    def last_result(self) -> DetectionResult | None:
        return self._last_result
