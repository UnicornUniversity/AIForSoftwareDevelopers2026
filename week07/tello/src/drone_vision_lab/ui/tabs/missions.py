"""Flight Missions tab.

The six-segment loop is editable within conservative limits, validated on every
change, previewable without sending anything, and executed only after an
explicit operator confirmation. Execution runs on a background worker so the
window never waits on the aircraft.

**Stop Mission** stops issuing new segments and does not itself land; the
command already in flight finishes. **Emergency Land** stays a separate top-bar
action. A standard Tello has no reliable indoor global position, so the loop is
described as approximate — never as a return to the exact start point.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import CONSERVATIVE_LIMITS, SafetyLimits
from ...container import AppServices
from ...domain import CommandStatus
from ...mission import (
    MissionIssue,
    MissionOutcome,
    MissionPlan,
    MissionResult,
    MissionRunner,
    MissionSegment,
    SegmentAction,
    default_mission,
    estimated_duration_s,
    validate_mission,
)
from ...state import AppStateSnapshot, SafetyState
from ...workers import CallableRunner
from .. import widgets

__all__ = ["MissionsTab"]

_log = logging.getLogger(__name__)

_ACTIONS = (
    SegmentAction.TAKEOFF,
    SegmentAction.LEFT,
    SegmentAction.FORWARD,
    SegmentAction.RIGHT,
    SegmentAction.BACK,
    SegmentAction.LAND,
)
_LABELS = {
    SegmentAction.TAKEOFF: "Take off",
    SegmentAction.LEFT: "Move left",
    SegmentAction.FORWARD: "Move forward",
    SegmentAction.RIGHT: "Move right",
    SegmentAction.BACK: "Move backward",
    SegmentAction.LAND: "Land",
}
_MAX_PAUSE_S = 10.0
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


class MissionsTab(QWidget):
    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
        *,
        limits: SafetyLimits = CONSERVATIVE_LIMITS,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._limits = limits
        self._plan = default_mission(limits)
        self._runner: MissionRunner | None = None
        self._running = False
        self._pre_mission_state: SafetyState | None = None
        self._mission_runner = CallableRunner(self)
        self._mission_runner.finished.connect(self._on_mission_finished)
        self._mission_runner.failed.connect(self._on_mission_failed)
        self._build()
        self._load_plan(self._plan)
        self._sync_plan_from_widgets()
        self._refresh_validation()
        self.apply_state(services.state.snapshot())

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(widgets.SectionTitle("Flight Missions"))
        intro = QLabel(
            "A rectangular loop flown in six ordered segments. Distances, speed and "
            "pauses are checked against conservative limits before anything is sent. "
            "Each real flight needs an explicit operator confirmation."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5b6470;")
        layout.addWidget(intro)

        layout.addWidget(self._build_editor(), 1)

        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        layout.addWidget(self._validation_label)

        self._status_label = QLabel("No mission has run in this session.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        buttons = QHBoxLayout()
        self._preview_button = QPushButton("Preview")
        self._preview_button.setToolTip(
            "Show the plan and its conservative time estimate. Sends no command."
        )
        self._preview_button.clicked.connect(self._show_preview)
        self._execute_button = QPushButton("Execute mission")
        self._execute_button.setToolTip(
            "Fly the plan after an explicit confirmation. The aircraft takes off."
        )
        self._execute_button.clicked.connect(self._execute_mission)
        self._stop_button = QPushButton("Stop mission")
        self._stop_button.setToolTip(
            "Stop issuing new segments. This does not land the aircraft and does not "
            "send anything; the command already in flight finishes."
        )
        self._stop_button.clicked.connect(self._stop_mission)
        buttons.addWidget(self._preview_button)
        buttons.addWidget(self._execute_button)
        buttons.addWidget(self._stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(self._build_limits_note())

    def _build_editor(self) -> QWidget:
        group = QGroupBox("Mission plan")
        layout = QVBoxLayout(group)
        self._table = QTableWidget(len(_ACTIONS), 5, self)
        self._table.setHorizontalHeaderLabels(
            ["Segment", "Action", "Distance / climb", "Speed", "Pause"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.resizeRowsToContents()

        self._distance_spins: dict[int, QSpinBox] = {}
        self._speed_spins: dict[int, QSpinBox] = {}
        self._pause_spins: dict[int, QDoubleSpinBox] = {}

        for index, action in enumerate(_ACTIONS):
            self._table.setItem(index, 0, QTableWidgetItem(str(index + 1)))
            self._table.setItem(index, 1, QTableWidgetItem(_LABELS[action]))

            distance = QSpinBox()
            distance.setSuffix(" cm")
            if action is SegmentAction.TAKEOFF:
                distance.setRange(0, self._limits.max_altitude_cm)
                distance.setSingleStep(20)
                distance.setSpecialValueText("Take off to hover height")
                distance.setToolTip(
                    "Climb after takeoff. 0 keeps the takeoff hover height; "
                    f"the maximum is the {self._limits.max_altitude_cm} cm altitude limit."
                )
            else:
                distance.setRange(0, self._limits.max_segment_distance_cm)
                distance.setSingleStep(10)
                distance.setToolTip(
                    f"Distance for this leg, up to {self._limits.max_segment_distance_cm} cm."
                )
            distance.valueChanged.connect(self._on_plan_edited)
            self._table.setCellWidget(index, 2, distance)
            self._distance_spins[index] = distance

            speed = QSpinBox()
            speed.setRange(0, self._limits.max_speed_cm_s)
            speed.setSingleStep(5)
            speed.setSuffix(" cm/s")
            speed.setToolTip(
                f"Speed for this leg, up to {self._limits.max_speed_cm_s} cm/s."
            )
            speed.valueChanged.connect(self._on_plan_edited)
            self._table.setCellWidget(index, 3, speed)
            self._speed_spins[index] = speed
            if action in (SegmentAction.TAKEOFF, SegmentAction.LAND):
                speed.setEnabled(False)
                speed.setSpecialValueText("not used")

            pause = QDoubleSpinBox()
            pause.setRange(0.0, _MAX_PAUSE_S)
            pause.setSingleStep(0.5)
            pause.setDecimals(1)
            pause.setSuffix(" s")
            pause.setToolTip("Wait before this segment, up to 10 s.")
            pause.valueChanged.connect(self._on_plan_edited)
            self._table.setCellWidget(index, 4, pause)
            self._pause_spins[index] = pause

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
            "A standard Tello has no reliable indoor global position estimate. "
            "A loop of six moves will not return the aircraft to its exact start "
            "point; treat return-to-origin as approximate at best."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5b6470;")
        return note

    # -- plan editing --------------------------------------------------------

    def _load_plan(self, plan: MissionPlan) -> None:
        """Show an existing plan in the editors without rebuilding the plan."""
        for index, segment in enumerate(plan.segments):
            distance = self._distance_spins[index]
            speed = self._speed_spins[index]
            pause = self._pause_spins[index]
            for widget in (distance, speed, pause):
                widget.blockSignals(True)
            distance.setValue(
                min(segment.distance_cm, distance.maximum())
            )
            speed.setValue(segment.speed_cm_s or 0)
            pause.setValue(segment.pause_s)
            for widget in (distance, speed, pause):
                widget.blockSignals(False)

    def _on_plan_edited(self) -> None:
        self._sync_plan_from_widgets()
        self._refresh_validation()
        self.apply_state(self._services.state.snapshot())

    def _sync_plan_from_widgets(self) -> None:
        segments: list[MissionSegment] = []
        for index, action in enumerate(_ACTIONS):
            distance = self._distance_spins[index].value()
            speed = (
                self._speed_spins[index].value()
                if action not in (SegmentAction.TAKEOFF, SegmentAction.LAND)
                else None
            )
            pause = self._pause_spins[index].value()
            segments.append(
                MissionSegment(
                    action,
                    distance_cm=0 if action is SegmentAction.LAND else distance,
                    speed_cm_s=speed,
                    pause_s=round(pause, 1),
                )
            )
        self._plan = MissionPlan(segments=tuple(segments))
        self._preview_button.setEnabled(True)

    def _refresh_validation(self) -> None:
        issues = validate_mission(self._plan, self._limits)
        if issues:
            self._validation_label.setText(
                "The plan is not flyable:\n" + "\n".join(issue.describe() for issue in issues)
            )
            self._validation_label.setStyleSheet("color: #b42318;")
        else:
            self._validation_label.setText(
                f"Plan is within limits. Conservative estimate: "
                f"{estimated_duration_s(self._plan):.1f} s — not a promise of flight time. "
                "A standard Tello does not return to its exact start point."
            )
            self._validation_label.setStyleSheet("color: #1a7f37;")
        self._issues = issues

    # -- preview -------------------------------------------------------------

    def _plan_lines(self) -> str:
        lines = []
        for index, segment in enumerate(self._plan.segments, start=1):
            if segment.is_takeoff:
                detail = (
                    f"climb {segment.distance_cm} cm" if segment.distance_cm else "hover"
                )
            elif segment.is_landing:
                detail = "standard landing command"
            else:
                detail = (
                    f"{segment.distance_cm} cm at {segment.speed_cm_s} cm/s"
                )
            pause = f", pause {segment.pause_s:g} s before" if segment.pause_s else ""
            lines.append(f"{index}. {_LABELS[segment.action]}: {detail}{pause}")
        return "\n".join(lines)

    def _show_preview(self) -> None:
        self._refresh_validation()
        issues = validate_mission(self._plan, self._limits)
        problem = (
            "\n\nBlocking issues:\n"
            + "\n".join(issue.describe() for issue in issues)
            if issues
            else ""
        )
        QMessageBox.information(
            self,
            "Mission preview",
            f"{self._plan_lines()}\n\n"
            f"Conservative estimate: {estimated_duration_s(self._plan):.1f} s.\n"
            "The loop is approximate: a standard Tello has no reliable indoor global "
            "position, so it will not return to its exact start point."
            f"{problem}\n\nPreview sends no command.",
        )

    # -- execution -----------------------------------------------------------

    def _execute_mission(self) -> None:
        if self._running:
            return
        self._refresh_validation()
        if self._issues:
            widgets.show_error(
                self,
                "Mission not started",
                "The plan is outside the safety limits:\n"
                + "\n".join(issue.describe() for issue in self._issues),
            )
            return
        snapshot = self._services.state.snapshot()
        if not snapshot.drone_connected:
            widgets.show_error(self, "Mission not started", "Connect to the aircraft first.")
            return
        if snapshot.safety_state.in_flight:
            widgets.show_error(
                self,
                "Mission not started",
                "The aircraft is already airborne. Land it before starting a mission.",
            )
            return
        if snapshot.safety_state not in _GROUNDED_STATES:
            # "Not in flight" is not the same as "known to be on the ground":
            # FAULT follows a program whose landing was not confirmed.
            widgets.show_error(
                self,
                "Mission not started",
                f"The aircraft's last safety state is "
                f"'{snapshot.safety_state.display_name}'. An earlier program did not "
                "finish cleanly, so the aircraft may still be airborne. Reconnect "
                "and confirm it is on the ground before starting a mission; use "
                "Emergency Land if it is still flying.",
            )
            return

        if not self._confirm_execution():
            return

        self._runner = MissionRunner(
            self._services.drone,
            self._plan,
            limits=self._limits,
            telemetry=self._services.drone.telemetry,
            telemetry_max_age_s=getattr(
                self._services.drone, "telemetry_max_age_s", None
            ),
        )
        self._pre_mission_state = snapshot.safety_state
        self._running = True
        # Reserve the aircraft for the mission so manual input cannot also send
        # commands while the runner is active.
        self._services.state.update(safety_state=SafetyState.FLYING_MISSION, last_error=None)
        self._status_label.setText(
            "Mission running. Stop Mission stops new segments; it does not land the "
            "aircraft by itself."
        )
        self.apply_state(self._services.state.snapshot())
        runner = self._runner
        if not self._mission_runner.submit(
            lambda: runner.run(operator_confirmed=True)
        ):
            self._running = False
            self._runner = None
            self._restore_grounded_state()
            self._status_label.setText("Another background job is still running.")

    def _confirm_execution(self) -> bool:
        flight_note = (
            "The propellers will spin and the aircraft will fly the plan below."
            if self._services.drone_mode == "tello"
            else "This is the simulated aircraft; the plan is simulated and no "
            "propellers will spin."
        )
        answer = QMessageBox.warning(
            self,
            "Execute mission",
            f"{flight_note}\n\n{self._plan_lines()}\n\n"
            f"Conservative estimate: {estimated_duration_s(self._plan):.1f} s.\n"
            "The aircraft does not return to its exact start point. Keep it in sight, "
            "keep the area clear, and confirm the phone app is not controlling.\n\n"
            "Start the mission now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return widgets.is_yes(answer)

    def _stop_mission(self) -> None:
        if self._runner is None or not self._running:
            return
        self._stop_button.setEnabled(False)
        self._runner.cancel("Stopped by the operator.")
        self._status_label.setText(
            "Stop requested. No new segments will be sent and no landing command is "
            "issued by Stop Mission; the command already in flight finishes. The "
            "aircraft may still be airborne — use Emergency Land if needed."
        )

    def _on_mission_finished(self, result: object) -> None:
        if not isinstance(result, MissionResult):
            return
        self._running = False
        self._runner = None
        self._apply_outcome(result)
        self.apply_state(self._services.state.snapshot())

    def _on_mission_failed(self, message: str) -> None:
        self._running = False
        self._runner = None
        self._services.state.update(
            safety_state=SafetyState.FAULT,
            last_error=message,
        )
        self._status_label.setText(
            f"The mission worker failed: {message}. The aircraft may still be airborne; "
            "use Emergency Land if needed."
        )
        widgets.show_error(self, "Mission failed", message)
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

        if result.outcome is MissionOutcome.COMPLETED:
            # An acknowledgement is not evidence of landing, but the adapter
            # reports CONFIRMED only when telemetry received *after* the
            # acknowledgement reported height 0. An acknowledged-only landing
            # stays LANDING_REQUESTED until that evidence exists.
            landing_confirmed = any(
                command.command == "land" and command.status is CommandStatus.CONFIRMED
                for command in result.commands
            )
            self._services.state.update(
                safety_state=SafetyState.LANDING_REQUESTED,
                last_error=None,
            )
            if landing_confirmed:
                self._services.state.update(safety_state=SafetyState.LANDED_CONFIRMED)
                self._status_label.setText(
                    detail
                    + " Landing was confirmed by telemetry received after the "
                    "acknowledgement. The loop is approximate."
                )
            else:
                self._status_label.setText(
                    detail
                    + " Landing still needs visual confirmation; the loop is approximate."
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
            self._status_label.setText(detail)
        else:  # REJECTED
            self._restore_grounded_state()
            self._status_label.setText(detail)
            widgets.show_error(self, "Mission not started", result.reason)

    def _restore_grounded_state(self) -> None:
        restore = self._pre_mission_state or SafetyState.CONNECTED_GROUNDED
        if restore not in _GROUNDED_STATES:
            restore = SafetyState.CONNECTED_GROUNDED
        self._services.state.update(safety_state=restore)

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        connected = snapshot.drone_connected
        in_flight = snapshot.safety_state.in_flight
        grounded = snapshot.safety_state in _GROUNDED_STATES
        issues = getattr(self, "_issues", ())
        self._execute_button.setEnabled(
            connected and grounded and not self._running and not issues
        )
        if not connected:
            tooltip = "Connect to the aircraft before executing a mission."
        elif in_flight:
            tooltip = "The aircraft is already airborne. Land it before starting a mission."
        elif not grounded:
            tooltip = (
                "The aircraft's last state is not a confirmed grounded state. "
                "Reconnect and confirm it is on the ground before starting a mission."
            )
        elif issues:
            tooltip = "Fix the blocking validation issues first."
        elif self._running:
            tooltip = "A mission is already running."
        else:
            tooltip = (
                "Fly the plan after an explicit confirmation. The aircraft takes off."
            )
        self._execute_button.setToolTip(tooltip)
        self._stop_button.setEnabled(self._running)
        self._preview_button.setEnabled(not self._running)
        for spin in (
            *self._distance_spins.values(),
            *self._speed_spins.values(),
            *self._pause_spins.values(),
        ):
            spin.setEnabled(not self._running)
        for index, action in enumerate(_ACTIONS):
            if action in (SegmentAction.TAKEOFF, SegmentAction.LAND):
                self._speed_spins[index].setEnabled(False)

    def shutdown(self) -> None:
        if self._runner is not None:
            self._runner.cancel("The application is closing.")

    # -- test hooks ----------------------------------------------------------

    @property
    def table(self) -> QTableWidget:
        return self._table

    @property
    def plan(self) -> MissionPlan:
        return self._plan

    @property
    def validation_label_text(self) -> str:
        return self._validation_label.text()

    @property
    def status_text(self) -> str:
        return self._status_label.text()

    @property
    def issues(self) -> tuple[MissionIssue, ...]:
        return getattr(self, "_issues", ())

    @property
    def execute_button(self) -> QPushButton:
        return self._execute_button

    @property
    def stop_button(self) -> QPushButton:
        return self._stop_button
