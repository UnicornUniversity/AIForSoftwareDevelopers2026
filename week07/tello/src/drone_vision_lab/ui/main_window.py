"""Main application window.

One window, six tabs and a hidden-by-default Experiment Results dock, reachable
from **View → Experiment Results**. The top safety bar is never hidden or
disabled: Emergency Land must be reachable at all times, and it must say what it
actually did.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..adapters.drone import format_diagnostic_report, run_tello_diagnostics
from ..container import AppServices
from ..domain import CommandResult, CommandStatus, DetectorKind
from ..state import AppStateSnapshot, ControlAuthority, SafetyState
from ..workers import CallableRunner
from . import widgets
from .results_panel import ResultsPanel
from .state_bridge import StateBridge
from .tabs import (
    DroneControlTab,
    MissionsTab,
    ObjectFeedbackTab,
    PresetMissionsTab,
    TelloFlightTab,
    VisionLabTab,
)

__all__ = ["MainWindow"]

_log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.setWindowTitle("Drone Vision Lab")
        self.setMinimumSize(760, 480)
        widgets.fit_initial_size(self, 1180, 780)

        self._bridge = StateBridge(services.state, self)

        self._emergency_runner = CallableRunner(self)
        self._emergency_runner.finished.connect(self._on_emergency_finished)
        self._emergency_runner.failed.connect(self._on_emergency_failed)
        self._diagnostics_runner = CallableRunner(self)
        self._diagnostics_runner.finished.connect(self._on_diagnostics_finished)
        # A runner that raises emits only ``failed``. Without this connection the
        # menu item did nothing at all and the operator had no way to tell a
        # failed check from a hang.
        self._diagnostics_runner.failed.connect(self._on_diagnostics_failed)

        self._results_panel = ResultsPanel(services, self)

        self._tabs = QTabWidget(self)
        self._drone_tab = DroneControlTab(
            services,
            self._tabs,
            manual_override_requested=self._on_manual_activity,
        )
        self._missions_tab = MissionsTab(services, self._tabs)
        self._preset_missions_tab = PresetMissionsTab(services, self._tabs)
        self._vision_tab = VisionLabTab(services, self._tabs)
        self._tello_flight_tab = TelloFlightTab(services, self._tabs)
        self._object_feedback_tab = ObjectFeedbackTab(services, self._tabs)
        self._tabs.addTab(self._make_scrollable(self._vision_tab), "Computer Vision Lab")
        self._tabs.addTab(self._make_scrollable(self._tello_flight_tab), "Tello Flight")
        self._tabs.addTab(
            self._make_scrollable(self._object_feedback_tab),
            "Object detection && feedback",
        )
        self._tabs.addTab(self._make_scrollable(self._drone_tab), "Drone Control")
        self._tabs.addTab(self._make_scrollable(self._missions_tab), "Flight Missions")
        self._tabs.addTab(
            self._make_scrollable(self._preset_missions_tab), "Preset Flight Missions"
        )

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_safety_bar())
        central_layout.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

        self._results_dock = QDockWidget("Experiment Results", self)
        self._results_dock.setObjectName("results_dock")
        self._results_dock.setWidget(self._results_panel)
        self._results_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._results_dock)
        # Hidden by default so the tabs get the whole workspace. The panel keeps
        # recording and exporting; View → Experiment Results shows it again.
        self._results_dock.hide()

        self._build_menus()
        self._build_status_bar()

        self._bridge.changed.connect(self._on_state_changed)
        # A settings dialog (YOLO/VLM) or a profile load can replace a detector
        # from any tab. Every tab that reads the slot re-reads it here, so a
        # gate such as the apple preset's Execute button cannot stay stale.
        self._unsubscribe_detectors = services.detector_events.subscribe(
            self._on_detectors_changed
        )
        self._on_state_changed(services.state.snapshot())

    def _make_scrollable(self, page: QWidget) -> QScrollArea:
        """Let a tab scroll instead of forcing the whole window to stay large.

        Several tabs need more height than a scaled laptop display offers. A
        scroll area keeps every control reachable while allowing the window to
        shrink to a useful size.
        """
        area = QScrollArea(self._tabs)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(page)
        return area

    def _on_manual_activity(self) -> None:
        """Manual input overrides autonomous tracking.

        The manual panel calls this before evaluating the command; when a
        tracking session is active, the Vision Lab stops it and returns the
        safety state to manual flight first.
        """
        vision = getattr(self, "_vision_tab", None)
        if vision is not None:
            vision.on_manual_override()

    # -- safety bar ----------------------------------------------------------

    def _build_safety_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setStyleSheet("QWidget#safety_bar { background-color: #1b1f24; }")
        bar.setObjectName("safety_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)

        self._safety_label = QLabel("Disconnected — no aircraft connected")
        self._safety_label.setStyleSheet("color: #e6e9ef; font-weight: 600;")

        self._emergency_button = QPushButton("EMERGENCY LAND")
        self._emergency_button.setMinimumHeight(38)
        self._emergency_button.setStyleSheet(
            "QPushButton { background-color: #b42318; color: white; font-weight: 700;"
            " border: none; border-radius: 6px; padding: 6px 18px; }"
            "QPushButton:disabled { background-color: #4a3033; color: #9aa4b2; }"
        )
        self._emergency_button.clicked.connect(self._on_emergency_land)

        self._emergency_status = QLabel("")
        self._emergency_status.setStyleSheet("color: #e6e9ef;")

        layout.addWidget(self._safety_label)
        layout.addStretch(1)
        layout.addWidget(self._emergency_status)
        layout.addWidget(self._emergency_button)
        return bar

    def _on_emergency_land(self) -> None:
        if self._services.drone_mode == "tello":
            # A real UDP command can wait for a reply; never freeze the window.
            self._emergency_button.setEnabled(False)
            self._emergency_status.setText("Sending landing command…")
            if not self._emergency_runner.submit(self._services.drone.emergency_land):
                self._emergency_status.setText("Another command is pending")
                self._emergency_button.setEnabled(True)
            return
        self._complete_emergency(self._services.drone.emergency_land())

    def _on_emergency_finished(self, result: object) -> None:
        if isinstance(result, CommandResult):
            self._complete_emergency(result)

    def _on_emergency_failed(self, message: str) -> None:
        self._emergency_status.setText("Landing command could not be sent")
        self._emergency_button.setEnabled(self._services.drone.connected)
        widgets.show_error(
            self,
            "Emergency land failed",
            message
            or "The landing command could not be sent. Use the phone app or the "
            "aircraft's documented behaviour to recover.",
        )

    def _complete_emergency(self, result: CommandResult) -> None:
        self._services.state.update(
            safety_state=SafetyState.LANDING_REQUESTED
            if result.status.acknowledged
            else SafetyState.FAULT,
            last_error=None if result.status.acknowledged else result.detail,
        )
        if not self._services.drone.connected:
            # The command channel itself is gone. Say so; never imply the
            # landing was received.
            self._services.state.update(
                drone_connected=False,
                control_authority=ControlAuthority.NONE,
                battery_percent=None,
                video_active=False,
                video_source_type=None,
                video_owner=None,
            )
        _log.warning(
            "Emergency land requested",
            extra={"context": {"status": result.status.value, "command": result.command}},
        )

        if result.status is CommandStatus.CONFIRMED:
            self._emergency_status.setText("Landing confirmed")
        elif result.status.acknowledged:
            self._emergency_status.setText("Landing command sent — not confirmed")
        elif result.status is CommandStatus.TIMEOUT:
            self._emergency_status.setText("Landing command timed out — outcome unknown")
        else:
            self._emergency_status.setText("Landing command could not be sent")
            widgets.show_error(
                self,
                "Emergency land failed",
                result.detail
                or "The landing command could not be sent. Use the phone app or the "
                "aircraft's documented behaviour to recover.",
            )
        self._emergency_button.setEnabled(self._services.drone.connected)

    # -- menus ---------------------------------------------------------------

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        profiles_action = QAction("Experiment &Profiles…", self)
        profiles_action.triggered.connect(self._open_profiles)
        file_menu.addAction(profiles_action)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menubar.addMenu("&View")
        results_action = self._results_dock.toggleViewAction()
        results_action.setText("Experiment Results")
        view_menu.addAction(results_action)

        help_menu = menubar.addMenu("&Help")
        check_action = QAction("Tello connection check…", self)
        check_action.triggered.connect(self._run_tello_check)
        help_menu.addAction(check_action)
        logs_action = QAction("Open log folder", self)
        logs_action.triggered.connect(self._open_log_folder)
        help_menu.addAction(logs_action)

        about_action = QAction("About Drone Vision Lab", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _open_profiles(self) -> None:
        from .profiles_dialog import ProfilesDialog

        dialog = ProfilesDialog(self._services, self)
        dialog.exec()
        # A profile load may have replaced detectors; let both video tabs re-read
        # them. The dialog also publishes each detector it applies, but a profile
        # with no detector sections publishes nothing. No source is started and
        # no command is sent either way.
        self._refresh_detector_views()

    def _on_detectors_changed(self, _kind: DetectorKind) -> None:
        """Re-read the detector slots after a dialog or profile replaced one."""
        _log.info("Detector slot changed", extra={"context": {"kind": str(_kind)}})
        self._refresh_detector_views()

    def _refresh_detector_views(self) -> None:
        """Refresh every tab that displays or gates on a detector.

        Label and gate updates only: no video source, no model load, no command.
        """
        self._vision_tab.refresh_detectors()
        self._tello_flight_tab.refresh_detector_status()
        self._object_feedback_tab.refresh_detector_status()
        self._preset_missions_tab.refresh_detector_status()

    def _run_tello_check(self) -> None:
        if self._diagnostics_runner.busy:
            return
        snapshot = self._services.state.snapshot()
        self._diagnostics_runner.submit(
            lambda: run_tello_diagnostics(
                app_connected=snapshot.drone_connected,
                video_active=snapshot.video_active,
            )
        )

    def _on_diagnostics_finished(self, checks: object) -> None:
        if not isinstance(checks, tuple):
            # The worker reported success but handed back no report. Say so
            # rather than leaving the operator waiting for a dialog.
            widgets.show_error(
                self,
                "Tello connection check",
                "The check finished without a report. See the log file for details.",
            )
            return
        QMessageBox.information(
            self,
            "Tello connection check",
            format_diagnostic_report(checks),
        )

    def _on_diagnostics_failed(self, message: str) -> None:
        widgets.show_error(
            self,
            "Tello connection check failed",
            message
            or "The check did not finish. These checks send no command to the aircraft.",
        )

    def _open_log_folder(self) -> None:
        from ..logging_setup import get_log_file

        path: Path = get_log_file().parent
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_about(self) -> None:
        if self._services.drone_mode == "tello":
            mode_note = (
                "<b>Hardware mode is active.</b> Connect uses the standard Tello "
                "command channel; connecting sends no takeoff. Manual control is "
                "bounded steps after an explicit Take control. Missions run only "
                "after an explicit confirmation. The vision-language model only "
                "describes frames and has no path to flight control."
            )
        else:
            mode_note = (
                "<b>This build is running the simulated aircraft.</b> It opens no "
                "drone socket and sends no flight command. Set "
                "<code>DRONE_VISION_LAB_DRONE=tello</code> for hardware mode. The "
                "vision-language model only describes frames and has no path to "
                "flight control."
            )
        QMessageBox.about(
            self,
            "About Drone Vision Lab",
            f"<b>Drone Vision Lab</b> {__version__}<br><br>"
            "Classroom comparison of classical computer vision, object detection and "
            "vision-language models on DJI Tello video.<br><br>"
            f"{mode_note}",
        )

    # -- status bar ----------------------------------------------------------

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self._status_state = QLabel()
        self._status_authority = QLabel()
        self._status_battery = QLabel()
        bar.addPermanentWidget(self._status_state)
        bar.addPermanentWidget(self._status_authority)
        bar.addPermanentWidget(self._status_battery)

    # -- state ---------------------------------------------------------------

    def _on_state_changed(self, snapshot: AppStateSnapshot) -> None:
        state = snapshot.safety_state
        self._safety_label.setText(f"{state.display_name} — {self._connection_summary(snapshot)}")
        self._emergency_button.setEnabled(snapshot.drone_connected)
        self._emergency_button.setToolTip(
            "Send the standard landing command now"
            if snapshot.drone_connected
            else "No command channel: connect to the aircraft first"
        )

        self._status_state.setText(f"State: {state.display_name}")
        self._status_authority.setText(
            f"Authority: {snapshot.control_authority.value.replace('_', ' ').title()}"
        )
        battery = snapshot.battery_percent
        battery_text = (
            f"Battery: {battery} %" if battery is not None else "Battery: not reported"
        )
        if snapshot.drone_connected and snapshot.telemetry_stale:
            battery_text += " (stale)"
        self._status_battery.setText(battery_text)

        self._drone_tab.apply_state(snapshot)
        self._missions_tab.apply_state(snapshot)
        self._preset_missions_tab.apply_state(snapshot)
        self._tello_flight_tab.apply_state(snapshot)
        self._object_feedback_tab.apply_state(snapshot)
        self._vision_tab.apply_state(snapshot)
        self._results_panel.apply_state(snapshot)

    @staticmethod
    def _connection_summary(snapshot: AppStateSnapshot) -> str:
        if not snapshot.drone_connected:
            return "no aircraft connected"
        if snapshot.telemetry_stale:
            # The aircraft may still be reachable, but the application has no
            # current state from it; never describe that as an ordinary link.
            return "aircraft connected, telemetry lost — values are stale"
        if snapshot.video_active:
            return "aircraft connected, camera active"
        return "aircraft connected, camera stopped"

    # -- lifecycle -----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Stop hearing about detector changes before the tabs are torn down.
        self._unsubscribe_detectors()
        self._tello_flight_tab.shutdown()
        self._object_feedback_tab.shutdown()
        self._vision_tab.shutdown()
        self._drone_tab.shutdown()
        self._missions_tab.shutdown()
        self._preset_missions_tab.shutdown()
        self._results_panel.shutdown()
        # Release the command, telemetry and video sockets deterministically.
        # Closing sends no takeoff, landing or motor-stop command: an aircraft
        # that is still airborne stays airborne.
        self._services.drone.disconnect()
        self._bridge.close()
        super().closeEvent(event)

    # -- accessors used by tests --------------------------------------------

    @property
    def tabs(self) -> QTabWidget:
        return self._tabs

    @property
    def drone_tab(self) -> DroneControlTab:
        return self._drone_tab

    @property
    def missions_tab(self) -> MissionsTab:
        return self._missions_tab

    @property
    def preset_missions_tab(self) -> PresetMissionsTab:
        return self._preset_missions_tab

    @property
    def vision_tab(self) -> VisionLabTab:
        return self._vision_tab

    @property
    def tello_flight_tab(self) -> TelloFlightTab:
        return self._tello_flight_tab

    @property
    def object_feedback_tab(self) -> ObjectFeedbackTab:
        return self._object_feedback_tab

    @property
    def results_dock(self) -> QDockWidget:
        return self._results_dock

    @property
    def results_panel(self) -> ResultsPanel:
        return self._results_panel

    @property
    def emergency_button(self) -> QPushButton:
        return self._emergency_button

    @property
    def emergency_status_text(self) -> str:
        return self._emergency_status.text()

    @property
    def safety_label_text(self) -> str:
        return self._safety_label.text()
