"""Manual control from the keyboard and the on-screen buttons.

The panel is deliberately explicit about authority:

* **Take control** declares this desktop as the controller and warns that the
  phone app must not be controlling at the same time.
* Every movement is one bounded step; there is no continuous stick feed.
* Takeoff and landing are never bound to a shortcut without an explicit
  confirmation dialog.

Commands are bounded steps submitted one at a time on a background worker; the
GUI thread only renders the latest result.

Gamepad support is not wired into this build. The Qt-free mapping and adapter
modules remain on disk for a future lesson, but this panel exposes no gamepad
controls and reads no controller input.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..container import AppServices
from ..domain import CommandResult, CommandStatus
from ..manual_control import ManualAction, ManualCommand, ManualController
from ..state import AppStateSnapshot, ControlAuthority, SafetyState
from ..workers import CallableRunner
from . import widgets

__all__ = ["ManualControlPanel"]

_log = logging.getLogger(__name__)

_KEY_ACTIONS = {
    "W": ManualAction.FORWARD,
    "S": ManualAction.BACK,
    "A": ManualAction.LEFT,
    "D": ManualAction.RIGHT,
    "E": ManualAction.YAW_CW,
    "Q": ManualAction.YAW_CCW,
    "R": ManualAction.UP,
    "F": ManualAction.DOWN,
}

class ManualControlPanel(QWidget):
    def __init__(
        self,
        services: AppServices,
        *,
        manual_activity: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._manual_activity = manual_activity
        self._controller = ManualController(
            services.drone,
            telemetry_max_age_s=getattr(services.drone, "telemetry_max_age_s", None),
        )
        self._command_runner = CallableRunner(self)
        self._command_runner.finished.connect(self._on_command_finished)
        self._build()
        self._install_keyboard()
        self._refresh_controls(services.state.snapshot())

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_manual_group())

    def _build_manual_group(self) -> QWidget:
        group = QGroupBox("Manual control (bounded steps)")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self._take_control_button = QPushButton("Take control")
        self._take_control_button.setToolTip(
            "Declare this application as the controller. Close the phone app's "
            "control session first: a standard Tello does not arbitrate."
        )
        self._take_control_button.clicked.connect(self._take_control)
        self._release_button = QPushButton("Release control")
        self._release_button.clicked.connect(self._release_control)
        self._manual_status = QLabel(
            "Manual control released. Take control before sending commands."
        )
        self._manual_status.setWordWrap(True)
        row.addWidget(self._take_control_button)
        row.addWidget(self._release_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self._manual_status)

        hint = QLabel(
            "Each input sends one short bounded step at a conservative speed; it is "
            "not a continuous stick feed. Click this panel, then use W/S/A/D to move, "
            "Q/E to yaw and R/F for up/down, or press the on-screen buttons. "
            f"Step: {self._controller.step_cm} cm, "
            f"yaw: {self._controller.yaw_degrees}°, minimum gap 0.5 s."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5b6470;")
        layout.addWidget(hint)

        grid = QGridLayout()
        self._action_buttons: dict[ManualAction, QPushButton] = {}
        placements = {
            ManualAction.YAW_CCW: (0, 0),
            ManualAction.UP: (0, 1),
            ManualAction.YAW_CW: (0, 2),
            ManualAction.LEFT: (1, 0),
            ManualAction.FORWARD: (1, 1),
            ManualAction.RIGHT: (1, 2),
            ManualAction.BACK: (2, 1),
            ManualAction.DOWN: (2, 2),
        }
        labels = {
            ManualAction.YAW_CCW: "Yaw left",
            ManualAction.UP: "Up",
            ManualAction.YAW_CW: "Yaw right",
            ManualAction.LEFT: "Left",
            ManualAction.FORWARD: "Forward",
            ManualAction.RIGHT: "Right",
            ManualAction.BACK: "Back",
            ManualAction.DOWN: "Down",
        }
        for action, (row_index, column) in placements.items():
            button = QPushButton(labels[action])
            button.clicked.connect(
                lambda _checked=False, action=action: self._request_action(action)
            )
            grid.addWidget(button, row_index, column)
            self._action_buttons[action] = button
        layout.addLayout(grid)

        takeoff_row = QHBoxLayout()
        self._takeoff_button = QPushButton("Take off")
        self._takeoff_button.clicked.connect(lambda: self._request_action(ManualAction.TAKEOFF))
        self._land_button = QPushButton("Land")
        self._land_button.clicked.connect(lambda: self._request_action(ManualAction.LAND))
        takeoff_row.addWidget(self._takeoff_button)
        takeoff_row.addWidget(self._land_button)
        takeoff_row.addStretch(1)
        layout.addLayout(takeoff_row)
        return group

    def _install_keyboard(self) -> None:
        for key, action in _KEY_ACTIONS.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda action=action: self._request_action(action)
            )

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        if not snapshot.drone_connected and self._controller.engaged:
            self._controller.disengage("Disconnected; manual control released.")
            self._manual_status.setText(self._controller.blocked_reason)
        self._refresh_controls(snapshot)
        if self._controller.engaged and snapshot.safety_state is SafetyState.FLYING_MISSION:
            self._controller.disengage("A mission now owns the aircraft.")
            self._manual_status.setText("Mission running — manual control released.")

    @property
    def controller(self) -> ManualController:
        return self._controller

    @property
    def takeoff_button(self) -> QPushButton:
        return self._takeoff_button

    # -- manual control ------------------------------------------------------

    def _take_control(self) -> None:
        snapshot = self._services.state.snapshot()
        answer = QMessageBox.warning(
            self,
            "Take manual control",
            "This application will declare itself the controller.\n\n"
            "A standard Tello does not arbitrate: if the DJI phone app is still "
            "flying, both controllers' commands take effect. Close the phone app's "
            "control session and keep the aircraft in sight.\n\n"
            "Manual commands are bounded steps, not autonomous flight.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if not widgets.is_yes(answer):
            return
        reason = self._controller.engage(snapshot)
        if reason:
            self._manual_status.setText(reason)
            return
        self._services.state.update(control_authority=ControlAuthority.DESKTOP)
        self._manual_status.setText(
            "Manual control engaged. Every key or button press sends one bounded step."
        )
        self._refresh_controls(self._services.state.snapshot())

    def _release_control(self) -> None:
        self._controller.disengage()
        self._services.state.update(control_authority=ControlAuthority.NONE)
        self._manual_status.setText("Manual control released. No further commands are sent.")
        self._refresh_controls(self._services.state.snapshot())

    def _request_action(self, action: ManualAction) -> None:
        if not self._controller.engaged:
            self._manual_status.setText("Take manual control first.")
            return
        # Any manual input is an override: stop autonomous corrections before
        # this step is considered. The callback moves the safety state back to
        # manual flight, so the snapshot below already reflects it.
        if self._manual_activity is not None:
            self._manual_activity()
        if self._command_runner.busy:
            self._manual_status.setText("Waiting for the previous command to finish.")
            return
        snapshot = self._services.state.snapshot()
        telemetry = self._services.drone.telemetry()
        if action is ManualAction.TAKEOFF:
            if not self._confirm_takeoff():
                return
            command = self._controller.takeoff(snapshot, telemetry)
        elif action is ManualAction.LAND:
            command = self._controller.land(snapshot, telemetry)
        else:
            command = self._controller.from_keyboard(action, snapshot, telemetry)
        if command is None:
            self._manual_status.setText(self._controller.blocked_reason)
            return
        self._submit(command)

    def _confirm_takeoff(self) -> bool:
        flight_note = (
            "The propellers will spin and the aircraft will climb about one metre."
            if self._services.drone_mode == "tello"
            else "This is the simulated aircraft; no propellers will spin."
        )
        answer = QMessageBox.question(
            self,
            "Take off",
            f"{flight_note}\n\nKeep the area clear, keep the aircraft in sight and "
            "confirm the phone app is not controlling.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return widgets.is_yes(answer)

    def _submit(self, command: ManualCommand) -> None:
        self._manual_status.setText(f"Sending {command.describe()}…")
        if not self._command_runner.submit(lambda: self._controller.execute(command)):
            self._manual_status.setText("Waiting for the previous command to finish.")

    def _on_command_finished(self, result: object) -> None:
        if not isinstance(result, CommandResult):
            return
        snapshot = self._services.state.snapshot()
        if result.status is CommandStatus.CONFIRMED:
            self._manual_status.setText(f"{result.command}: confirmed")
        elif result.status.acknowledged:
            self._manual_status.setText(f"{result.command}: sent — not confirmed")
        elif result.status is CommandStatus.TIMEOUT:
            self._manual_status.setText(f"{result.command}: timed out — outcome unknown")
        else:
            self._manual_status.setText(f"{result.command}: could not be sent")
            widgets.show_error(self, "Manual command failed", result.detail)

        if result.command == "takeoff" and result.ok:
            self._services.state.update(
                safety_state=SafetyState.FLYING_MANUAL,
                last_error=None,
            )
        elif result.command == "land" and result.status.acknowledged:
            self._services.state.update(
                safety_state=SafetyState.LANDED_CONFIRMED
                if result.status is CommandStatus.CONFIRMED
                else SafetyState.LANDING_REQUESTED,
            )
        elif (
            result.status in (CommandStatus.FAILED, CommandStatus.TIMEOUT)
            and snapshot.safety_state.in_flight
        ):
            self._services.state.update(
                safety_state=SafetyState.FAULT,
                last_error=result.detail,
            )
            self._controller.disengage("A command failed; manual control released.")
        self._refresh_controls(self._services.state.snapshot())

    def _refresh_controls(self, snapshot: AppStateSnapshot) -> None:
        engaged = self._controller.engaged
        flying = snapshot.safety_state.in_flight
        can_take_control = (
            snapshot.drone_connected
            and not engaged
            and snapshot.control_authority is not ControlAuthority.EXTERNAL_APP
            and snapshot.safety_state
            not in (
                SafetyState.FLYING_MISSION,
                SafetyState.FLYING_TRACKING,
                SafetyState.LANDING_REQUESTED,
                SafetyState.COMMUNICATION_LOST,
                SafetyState.FAULT,
            )
        )
        self._take_control_button.setEnabled(can_take_control)
        self._release_button.setEnabled(engaged)
        locked = snapshot.safety_state in (
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        )
        self._takeoff_button.setEnabled(engaged and not flying and not locked)
        self._land_button.setEnabled(
            engaged
            and snapshot.safety_state
            in (SafetyState.FLYING_MANUAL, SafetyState.FLYING_TRACKING)
        )
        if not engaged:
            takeoff_tip = "Take control, then take off with an explicit confirmation."
        elif flying:
            takeoff_tip = "The aircraft is already airborne. Use Land."
        elif locked:
            takeoff_tip = "The safety state blocks takeoff; recover with Emergency Land."
        else:
            takeoff_tip = "Send the takeoff command after a confirmation dialog."
        self._takeoff_button.setToolTip(takeoff_tip)
        self._land_button.setToolTip(
            "Send the standard landing command."
            if self._land_button.isEnabled()
            else "Landing is available while the aircraft is under manual control."
        )
        for action, button in self._action_buttons.items():
            button.setEnabled(
                engaged
                and snapshot.safety_state
                in (SafetyState.FLYING_MANUAL, SafetyState.FLYING_TRACKING)
            )
            if not flying:
                tip = "Take off before using movement controls."
            elif locked:
                tip = "The safety state blocks manual movement; use Emergency Land."
            elif snapshot.safety_state is SafetyState.FLYING_TRACKING:
                tip = (
                    f"Stop tracking, then send one bounded {action.value} step."
                )
            else:
                tip = f"Send one bounded {action.value} step."
            button.setToolTip(tip)

    @property
    def manual_status_text(self) -> str:
        return self._manual_status.text()
