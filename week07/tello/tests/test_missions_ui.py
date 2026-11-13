"""Mission editor, validation, confirmation and cancellation in the window."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import QMessageBox

from drone_vision_lab.config import CONSERVATIVE_LIMITS
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.state import SafetyState


def pump(qapp, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def confirm(monkeypatch, answer=QMessageBox.StandardButton.Yes) -> None:
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kwargs: answer)
    )


def sent(drone) -> tuple[str, ...]:
    return tuple(command for command in drone.commands if command != "connect")


def connect(window) -> None:
    window.drone_tab.connect_button.click()


def test_the_default_plan_is_editable_and_within_limits(window):
    tab = window.missions_tab

    assert tab.plan.segments[1].distance_cm == 100
    assert "within limits" in tab.validation_label_text
    assert tab.execute_button.isEnabled() is False  # not connected yet
    assert "Connect" in tab.execute_button.toolTip()


def test_an_out_of_limit_edit_blocks_execution(window, services):
    tab = window.missions_tab
    connect(window)

    tab._distance_spins[1].setValue(0)

    assert tab.issues
    assert "not flyable" in tab.validation_label_text
    assert tab.execute_button.isEnabled() is False
    assert "validation" in tab.execute_button.toolTip()

    tab._distance_spins[1].setValue(100)

    assert tab.issues == ()
    assert tab.execute_button.isEnabled() is True


def test_preview_sends_nothing(window, monkeypatch):
    tab = window.missions_tab
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, text: seen.append(text)),
    )

    tab._show_preview()

    assert "Preview sends no command" in seen[0]
    assert "Conservative estimate" in seen[0]
    assert "1. Take off" in seen[0]


def test_execute_requires_confirmation_and_sends_nothing_on_no(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch, QMessageBox.StandardButton.No)
    connect(window)
    tab = window.missions_tab

    tab.execute_button.click()
    time.sleep(0.1)
    qapp.processEvents()

    assert sent(services.drone) == ()
    assert services.state.snapshot().safety_state is SafetyState.CONNECTED_GROUNDED
    assert "No mission has run" in tab.status_text


def test_a_confirmed_mission_runs_in_order_and_never_confirms_landing(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch)
    connect(window)
    tab = window.missions_tab
    # The takeoff settle is covered by the unit tests; a zero settle keeps this
    # UI-ordering test fast without changing any validation limit.
    tab._limits = replace(CONSERVATIVE_LIMITS, takeoff_settle_s=0.0)  # noqa: SLF001

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert sent(services.drone) == (
        "takeoff",
        "left 100 30",
        "forward 100 30",
        "right 100 30",
        "back 100 30",
        "land",
    )
    assert services.state.snapshot().safety_state is SafetyState.LANDING_REQUESTED
    assert "needs visual confirmation" in tab.status_text
    assert "Landing confirmed" not in tab.status_text
    assert "acknowledged" in tab.status_text  # command acknowledgements only


def test_a_landing_observed_in_telemetry_returns_the_tab_to_grounded(
    window, services, monkeypatch, qapp
):
    confirm(monkeypatch)
    connect(window)
    services.drone._confirm_landing = True  # noqa: SLF001 - test double switch
    tab = window.missions_tab
    tab._limits = replace(CONSERVATIVE_LIMITS, takeoff_settle_s=0.0)  # noqa: SLF001

    tab.execute_button.click()

    assert pump(qapp, lambda: not tab._running)
    assert services.state.snapshot().safety_state is SafetyState.LANDED_CONFIRMED
    assert "confirmed by telemetry" in tab.status_text
    assert tab.execute_button.isEnabled() is True


def test_a_mission_cannot_start_from_an_unconfirmed_state(
    window, services, monkeypatch, qapp
):
    connect(window)
    tab = window.missions_tab
    errors: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.missions.widgets.show_error",
        lambda _parent, _title, message: errors.append(str(message)),
    )
    services.state.update(safety_state=SafetyState.FAULT)
    tab.apply_state(services.state.snapshot())

    assert tab.execute_button.isEnabled() is False

    tab._execute_mission()  # noqa: SLF001 - the runtime guard is the subject
    assert sent(services.drone) == ()
    assert errors and "may still be airborne" in errors[0]


def test_stop_mission_cancels_without_landing(window, services, monkeypatch, qapp):
    slow = FakeDroneAdapter(command_delay=0.08)
    services.drone = slow
    confirm(monkeypatch)
    connect(window)
    tab = window.missions_tab

    tab.execute_button.click()
    assert pump(qapp, lambda: "takeoff" in slow.commands)
    tab.stop_button.click()
    assert pump(qapp, lambda: not tab._running)

    assert "land" not in sent(slow)
    assert "No landing command was issued" in tab.status_text
    assert services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL


def test_emergency_land_stays_reachable_while_a_mission_runs(
    window, services, monkeypatch, qapp
):
    slow = FakeDroneAdapter(command_delay=0.08)
    services.drone = slow
    confirm(monkeypatch)
    connect(window)
    tab = window.missions_tab

    tab.execute_button.click()
    assert pump(qapp, lambda: "takeoff" in slow.commands)
    assert window.emergency_button.isEnabled() is True

    window.emergency_button.click()
    tab.stop_button.click()
    assert pump(qapp, lambda: not tab._running)

    assert "land" in sent(slow)
    assert window.emergency_status_text == "Landing command sent — not confirmed"
