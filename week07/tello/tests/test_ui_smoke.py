"""Main window smoke tests. Run headless on the Qt offscreen platform."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QScrollArea

from drone_vision_lab.domain import Telemetry
from drone_vision_lab.state import SafetyState


def pump(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def test_window_has_the_six_required_tabs(window):
    tabs = window.tabs
    assert tabs.count() == 6
    assert [tabs.tabText(i) for i in range(6)] == [
        "Computer Vision Lab",
        "Tello Flight",
        "Object detection && feedback",
        "Drone Control",
        "Flight Missions",
        "Preset Flight Missions",
    ]
    assert tabs.currentIndex() == 0
    assert tabs.currentWidget() is tabs.widget(0)


def test_tabs_scroll_so_the_window_can_shrink_below_its_content(window):
    assert [type(window.tabs.widget(i)) for i in range(6)] == [QScrollArea] * 6
    assert window.minimumSize().width() <= 900
    assert window.minimumSize().height() <= 600


def test_results_panel_is_hidden_by_default_but_reachable_from_the_window(window):
    assert window.results_dock.widget() is window.results_panel
    assert window.results_dock.isHidden()
    assert window.dockWidgetArea(window.results_dock) != Qt.DockWidgetArea.NoDockWidgetArea

    # View → Experiment Results still toggles the dock back into the window.
    window.results_dock.toggleViewAction().trigger()
    assert not window.results_dock.isHidden()


def test_phase_one_controls_are_disabled(window):
    assert window.drone_tab.takeoff_button.isEnabled() is False
    assert window.drone_tab.connect_button.isEnabled() is True


def test_emergency_land_is_present_but_inactive_without_a_connection(window):
    assert window.emergency_button.isEnabled() is False
    assert "no aircraft connected" in window.safety_label_text


def test_simulated_connect_moves_the_state_and_arms_emergency_land(window, services):
    window.drone_tab.connect_button.click()

    snapshot = services.state.snapshot()
    assert snapshot.drone_connected is True
    assert snapshot.safety_state is SafetyState.CONNECTED_GROUNDED
    assert window.emergency_button.isEnabled() is True
    assert "Connected Grounded" in window.safety_label_text


def test_emergency_land_reports_sent_not_confirmed(window):
    window.drone_tab.connect_button.click()
    window.emergency_button.click()

    assert window.emergency_status_text == "Landing command sent — not confirmed"


def test_disconnect_returns_to_the_empty_state(window, services):
    window.drone_tab.connect_button.click()
    window.drone_tab._on_disconnect()  # noqa: SLF001 - exercising the UI action directly

    snapshot = services.state.snapshot()
    assert snapshot.drone_connected is False
    assert snapshot.safety_state is SafetyState.DISCONNECTED
    assert window.emergency_button.isEnabled() is False


def test_closing_the_window_releases_the_connection_without_flying(window, services):
    window.drone_tab.connect_button.click()
    assert services.drone.connected is True

    window.close()

    assert services.drone.connected is False
    flight_commands = {"takeoff", "land", "streamon", "streamoff"}
    assert flight_commands.isdisjoint(services.drone.commands)


def test_stale_telemetry_is_flagged_and_cleared_when_fresh_data_arrives(
    window, services, monkeypatch
):
    window.drone_tab.connect_button.click()
    stale = Telemetry(battery_percent=87, received_at=time.monotonic() - 60)
    monkeypatch.setattr(services.drone, "telemetry", lambda: stale)

    window.drone_tab._poll_telemetry()  # noqa: SLF001 - exercising the poll directly
    assert services.state.snapshot().telemetry_stale is True

    fresh = Telemetry(battery_percent=87, received_at=time.monotonic())
    monkeypatch.setattr(services.drone, "telemetry", lambda: fresh)
    window.drone_tab._poll_telemetry()  # noqa: SLF001

    assert services.state.snapshot().telemetry_stale is False


def test_lost_telemetry_is_logged_and_never_described_as_an_ordinary_link(
    window, services, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="drone_vision_lab.ui.tabs.drone_control")
    window.drone_tab.connect_button.click()
    stale = Telemetry(battery_percent=87, received_at=time.monotonic() - 60)
    monkeypatch.setattr(services.drone, "telemetry", lambda: stale)

    window.drone_tab._poll_telemetry()  # noqa: SLF001 - exercising the poll directly

    warnings = [
        record
        for record in caplog.records
        if record.getMessage() == "Telemetry is stale while connected"
    ]
    assert len(warnings) == 1
    assert warnings[0].context["telemetry_ever_received"] is True
    assert warnings[0].context["in_flight"] is False
    assert "telemetry lost" in window.safety_label_text.lower()
    assert "camera stopped" not in window.safety_label_text.lower()

    fresh = Telemetry(battery_percent=87, received_at=time.monotonic())
    monkeypatch.setattr(services.drone, "telemetry", lambda: fresh)
    window.drone_tab._poll_telemetry()  # noqa: SLF001

    assert any(
        record.getMessage() == "Telemetry is fresh again" for record in caplog.records
    )
    assert "telemetry lost" not in window.safety_label_text.lower()


def test_missions_table_lists_the_six_segments(window):
    table = window._missions_tab.table  # noqa: SLF001
    assert table.rowCount() == 6
    actions = [table.item(row, 1).text() for row in range(6)]
    assert actions[0].startswith("Take off")
    assert actions[-1] == "Land"


def test_preset_tab_shows_the_first_program_by_default(window):
    tab = window.preset_missions_tab
    assert tab.steps_table.rowCount() == 3
    assert tab.steps_table.item(0, 2).text() == "takeoff"
    assert tab.steps_table.item(2, 2).text() == "land"


def test_a_failed_connection_check_is_reported_instead_of_doing_nothing(
    qapp, window, monkeypatch
):
    """A worker exception used to emit only ``failed``, which nothing listened to."""
    import drone_vision_lab.ui.main_window as main_window

    reported: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, text: reported.append(text)),
    )

    def broken(**_kwargs):
        raise OSError("socket unavailable")

    monkeypatch.setattr(main_window, "run_tello_diagnostics", broken)

    window._run_tello_check()  # noqa: SLF001

    assert pump(qapp, lambda: bool(reported))
    assert "socket unavailable" in reported[0]


def test_a_connection_check_that_returns_no_report_says_so(qapp, window, monkeypatch):
    import drone_vision_lab.ui.main_window as main_window

    reported: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, text: reported.append(text)),
    )
    monkeypatch.setattr(main_window, "run_tello_diagnostics", lambda **_kwargs: [])

    window._run_tello_check()  # noqa: SLF001

    assert pump(qapp, lambda: bool(reported))
    assert "without a report" in reported[0]
