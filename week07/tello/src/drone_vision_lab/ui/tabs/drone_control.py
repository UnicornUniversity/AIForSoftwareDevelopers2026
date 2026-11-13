"""Drone Control tab.

Connection, telemetry and bounded manual control from the keyboard and on-screen
buttons. Connecting never takes off; every manual command needs an explicit
"take control" and an explicit step. Gamepad input is not wired into this build.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import CONSERVATIVE_LIMITS
from ...container import AppServices
from ...domain import CommandResult, CommandStatus, Telemetry, telemetry_is_fresh
from ...state import AppStateSnapshot, ControlAuthority, SafetyState
from ...workers import CallableRunner
from .. import widgets
from ..manual_panel import ManualControlPanel

__all__ = ["DroneControlTab"]

_log = logging.getLogger(__name__)


class DroneControlTab(QWidget):
    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
        *,
        manual_override_requested: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._hardware = services.drone_mode == "tello"
        adapter_max_age = getattr(services.drone, "telemetry_max_age_s", None)
        self._telemetry_max_age_s = (
            CONSERVATIVE_LIMITS.telemetry_max_age_s
            if adapter_max_age is None
            else float(adapter_max_age)
        )
        self._manual_override_requested = manual_override_requested
        self._telemetry_stale_logged = False
        self._connect_runner = CallableRunner(self)
        self._connect_runner.finished.connect(self._on_connect_finished)
        self._connect_runner.failed.connect(self._on_connect_failed)
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(500)
        self._telemetry_timer.timeout.connect(self._poll_telemetry)
        self._build()
        self.apply_state(services.state.snapshot())
        self._refresh_telemetry(None)

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(widgets.SectionTitle("Drone Control"))
        intro = QLabel(
            "Supervised control of a standard DJI Tello. Commands are serialized, "
            "rate-limited and never sent on connect. Connecting never takes off."
            if self._hardware
            else "Supervised control of a standard DJI Tello. This build simulates the "
            "aircraft: no command reaches real hardware."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #5b6470;")
        layout.addWidget(intro)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_telemetry_group())
        self._manual_panel = ManualControlPanel(
            self._services,
            manual_activity=self._manual_override_requested,
            parent=self,
        )
        layout.addWidget(self._manual_panel)
        layout.addWidget(self._build_authority_note())
        layout.addStretch(1)

    def _build_connection_group(self) -> QWidget:
        group = QGroupBox("Connection")
        layout = QHBoxLayout(group)

        self._connect_button = QPushButton(
            "Connect to Tello" if self._hardware else "Connect (simulated)"
        )
        self._connect_button.setToolTip(
            "Sends the SDK command handshake to 192.168.10.1:8889. It does not take off."
            if self._hardware
            else "Connects to the in-application simulated aircraft. No network traffic is sent."
        )
        self._connect_button.clicked.connect(self._on_connect)

        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.clicked.connect(self._on_disconnect)

        self._connection_pill = widgets.StatusPill("Disconnected")

        layout.addWidget(self._connect_button)
        layout.addWidget(self._disconnect_button)
        layout.addStretch(1)
        layout.addWidget(self._connection_pill)
        return group

    def _build_telemetry_group(self) -> QWidget:
        group = QGroupBox("Telemetry")
        grid = QGridLayout(group)
        self._battery_value = QLabel("not reported")
        self._height_value = QLabel("not reported")
        self._updated_value = QLabel("never")
        self._telemetry_note = QLabel("")
        self._telemetry_note.setWordWrap(True)
        self._telemetry_note.setStyleSheet("color: #b54708;")
        self._freshness_note = QLabel("")
        self._freshness_note.setWordWrap(True)
        self._freshness_note.setStyleSheet("color: #b54708;")
        grid.addWidget(QLabel("Battery"), 0, 0)
        grid.addWidget(self._battery_value, 0, 1)
        grid.addWidget(QLabel("Height"), 1, 0)
        grid.addWidget(self._height_value, 1, 1)
        grid.addWidget(QLabel("Last update"), 2, 0)
        grid.addWidget(self._updated_value, 2, 1)
        grid.addWidget(self._telemetry_note, 3, 0, 1, 3)
        grid.addWidget(self._freshness_note, 4, 0, 1, 3)
        grid.setColumnStretch(2, 1)
        return group

    def _build_authority_note(self) -> QWidget:
        group = QGroupBox("Control authority")
        layout = QVBoxLayout(group)
        self._authority_value = QLabel("None")
        note = QLabel(
            "A standard Tello does not arbitrate between controllers. If the phone app "
            "and this desktop application send commands at the same time, both take "
            "effect. Close the phone app's control session before flying from here."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #b54708;")
        layout.addWidget(self._authority_value)
        layout.addWidget(note)
        return group

    # -- behaviour -----------------------------------------------------------

    def _on_connect(self) -> None:
        if not self._hardware:
            self._finish_connect(self._services.drone.connect())
            return
        # A real handshake can take up to the timeout; the GUI thread must not
        # wait for the network.
        self._connect_button.setEnabled(False)
        self._connection_pill.set_status("Connecting…", "warn")
        if not self._connect_runner.submit(self._services.drone.connect):
            self._connect_button.setEnabled(True)
            self._connection_pill.set_status("Busy", "warn")

    def _on_connect_finished(self, result: object) -> None:
        if isinstance(result, CommandResult):
            self._finish_connect(result)

    def _on_connect_failed(self, message: str) -> None:
        self._connection_pill.set_status("Disconnected", "idle")
        self._connect_button.setEnabled(True)
        self._services.state.update(last_error=message)
        widgets.show_error(self, "Connection failed", message)

    def _finish_connect(self, result: CommandResult) -> None:
        if not result.ok:
            _log.warning(
                "Connect failed",
                extra={"context": {"status": result.status.value, "detail": result.detail}},
            )
            widgets.show_error(self, "Connection failed", result.detail or "Cannot connect")
            self._services.state.update(last_error=result.detail)
            self._connection_pill.set_status("Disconnected", "idle")
            self._connect_button.setEnabled(True)
            return
        self._services.state.update(
            drone_connected=True,
            safety_state=SafetyState.CONNECTED_GROUNDED,
            control_authority=ControlAuthority.DESKTOP,
            autonomy_armed=False,
            last_error=None,
        )
        _log.info(
            "Connected; no takeoff was sent",
            extra={"context": {"hardware": self._hardware}},
        )
        self._telemetry_stale_logged = False
        warning = getattr(self._services.drone, "telemetry_warning", "")
        self._telemetry_note.setText(f"Telemetry unavailable: {warning}" if warning else "")
        if warning:
            _log.warning(
                "Telemetry is unavailable after connecting",
                extra={"context": {"reason": warning}},
            )
        telemetry = self._services.drone.telemetry()
        self._refresh_telemetry(telemetry, stale=self._telemetry_is_stale(telemetry))
        self._telemetry_timer.start()

    def _on_disconnect(self) -> None:
        self._telemetry_timer.stop()
        _log.info("Disconnect requested by the operator")
        self._telemetry_stale_logged = False
        self._services.drone.disconnect()
        self._telemetry_note.setText("")
        self._services.state.update(
            drone_connected=False,
            safety_state=SafetyState.DISCONNECTED,
            control_authority=ControlAuthority.NONE,
            battery_percent=None,
            telemetry_stale=False,
            video_active=False,
            video_source_type=None,
            video_owner=None,
            autonomy_armed=False,
        )
        self._refresh_telemetry(None)

    def _poll_telemetry(self) -> None:
        """Read the adapter's cached telemetry; never performs network I/O."""
        snapshot = self._services.state.snapshot()
        if not snapshot.drone_connected:
            self._telemetry_timer.stop()
            return
        if not self._services.drone.connected:
            # The command channel went away while we thought it was open. Say
            # exactly that: losing the channel never implies a landing.
            self._telemetry_timer.stop()
            reason = (
                "The command channel stopped responding. No landing command can be "
                "sent from this application; use the phone app or the aircraft's "
                "documented behaviour."
            )
            _log.warning(
                "Command channel lost while connected",
                extra={
                    "context": {
                        "safety_state": snapshot.safety_state.value,
                        "battery_percent": snapshot.battery_percent,
                    }
                },
            )
            self._telemetry_note.setText(reason)
            self._services.state.update(
                drone_connected=False,
                safety_state=SafetyState.COMMUNICATION_LOST,
                control_authority=ControlAuthority.NONE,
                battery_percent=None,
                telemetry_stale=False,
                video_active=False,
                video_source_type=None,
                video_owner=None,
                autonomy_armed=False,
                last_error=reason,
            )
            self._refresh_telemetry(None)
            return
        telemetry = self._services.drone.telemetry()
        stale = self._telemetry_is_stale(telemetry)
        self._log_link_transition(telemetry, stale, snapshot)
        changes: dict[str, object] = {}
        if telemetry.battery_percent != snapshot.battery_percent:
            changes["battery_percent"] = telemetry.battery_percent
        if stale != snapshot.telemetry_stale:
            changes["telemetry_stale"] = stale
        if changes:
            self._services.state.update(**changes)
        self._refresh_telemetry(telemetry, stale=stale)

    def _telemetry_is_stale(self, telemetry: Telemetry) -> bool:
        return not telemetry_is_fresh(
            telemetry,
            now=time.monotonic(),
            max_age_s=self._telemetry_max_age_s,
        )

    def _log_link_transition(
        self,
        telemetry: Telemetry,
        stale: bool,
        snapshot: AppStateSnapshot,
    ) -> None:
        """Log the moment the state stream goes stale, and when it returns.

        Telemetry silence is the first measurable sign of a Wi-Fi drop. The log
        records when it started, how old the last report was and whether the
        aircraft was airborne, so the event can be correlated afterwards.
        """
        if stale and not self._telemetry_stale_logged:
            self._telemetry_stale_logged = True
            age = (
                None
                if telemetry.received_at is None
                else round(max(0.0, time.monotonic() - telemetry.received_at), 2)
            )
            _log.warning(
                "Telemetry is stale while connected",
                extra={
                    "context": {
                        "last_report_age_s": age,
                        "telemetry_ever_received": telemetry.received_at is not None,
                        "max_age_s": self._telemetry_max_age_s,
                        "safety_state": snapshot.safety_state.value,
                        "in_flight": snapshot.safety_state.in_flight,
                    }
                },
            )
        elif not stale and self._telemetry_stale_logged:
            self._telemetry_stale_logged = False
            _log.info(
                "Telemetry is fresh again",
                extra={
                    "context": {
                        "battery_percent": telemetry.battery_percent,
                        "height_cm": telemetry.height_cm,
                    }
                },
            )

    def _refresh_telemetry(self, telemetry: Telemetry | None, *, stale: bool = False) -> None:
        if telemetry is None:
            self._battery_value.setText("not reported")
            self._height_value.setText("not reported")
            self._updated_value.setText("never")
            self._freshness_note.setText("")
            return
        battery = telemetry.battery_percent
        self._battery_value.setText(f"{battery} %" if battery is not None else "not reported")
        height = telemetry.height_cm
        self._height_value.setText(f"{height} cm" if height is not None else "not reported")
        stamp = telemetry.received_at
        if stamp is None:
            self._updated_value.setText("never")
            self._freshness_note.setText("")
            return
        # received_at is monotonic; show how old the report is instead of
        # stamping the poll time, which would make stale data look current.
        age = max(0.0, time.monotonic() - stamp)
        self._updated_value.setText("just now" if age < 1.0 else f"{age:.0f} s ago")
        if stale:
            self._freshness_note.setText(
                f"Telemetry is stale — the last report is {age:.0f} s old. The "
                "values above are that report, not the current state; takeoff and "
                "vertical control are blocked until a fresh report arrives."
            )
        else:
            self._freshness_note.setText("")

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        connected = snapshot.drone_connected
        self._connection_pill.set_status(
            "Connected" if connected else "Disconnected",
            "ok" if connected else "idle",
            f"Safety state: {snapshot.safety_state.display_name}",
        )
        self._connect_button.setEnabled(not connected)
        self._disconnect_button.setEnabled(connected)
        self._authority_value.setText(snapshot.control_authority.value.replace("_", " ").title())
        if connected:
            if not self._telemetry_timer.isActive():
                self._telemetry_timer.start()
        else:
            self._telemetry_timer.stop()
        self._manual_panel.apply_state(snapshot)

    def shutdown(self) -> None:
        self._telemetry_timer.stop()

    # -- test hooks ----------------------------------------------------------

    @property
    def connect_button(self) -> QPushButton:
        return self._connect_button

    @property
    def manual_panel(self) -> ManualControlPanel:
        return self._manual_panel

    @property
    def takeoff_button(self) -> QPushButton:
        return self._manual_panel.takeoff_button

    @classmethod
    def describe_command_status(cls, status: CommandStatus) -> str:
        """Human wording that never overstates what a command status proves."""
        return {
            CommandStatus.REJECTED: "Refused by the safety check",
            CommandStatus.REQUESTED: "Queued — not yet sent",
            CommandStatus.SENT: "Sent — not confirmed",
            CommandStatus.CONFIRMED: "Confirmed",
            CommandStatus.FAILED: "Failed",
            CommandStatus.TIMEOUT: "Timed out — outcome unknown",
        }[status]
