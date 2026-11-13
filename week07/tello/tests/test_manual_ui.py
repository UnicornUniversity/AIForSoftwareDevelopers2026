"""Manual control from the keyboard and the on-screen buttons.

The dialogs are stubbed: these tests check the gates and the command path, not
Qt's modal behaviour. No test opens a drone socket or reads a controller.

Gamepad input is deliberately not wired into this build; one test asserts the
panel exposes no gamepad controls and the service graph carries no adapter.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox, QPushButton

from drone_vision_lab.manual_control import ManualAction
from drone_vision_lab.state import ControlAuthority, SafetyState


def pump(qapp, predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def confirm_dialogs(monkeypatch, answer=QMessageBox.StandardButton.Yes) -> None:
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args, **kwargs: answer)
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *args, **kwargs: answer)
    )


def connect(window) -> None:
    window.drone_tab.connect_button.click()


def take_control(window) -> None:
    window.drone_tab.manual_panel._take_control_button.click()


def sent(drone) -> tuple[str, ...]:
    return tuple(command for command in drone.commands if command != "connect")


def test_manual_controls_start_disabled_and_gamepad_is_absent(window, services):
    panel = window.drone_tab.manual_panel

    assert panel.takeoff_button.isEnabled() is False
    assert all(
        not button.isEnabled() for button in panel._action_buttons.values()
    )
    assert "Take control" in panel.manual_status_text
    assert not any(
        "gamepad" in button.text().lower()
        for button in panel.findChildren(QPushButton)
    )
    assert not hasattr(panel, "test_mode_active")
    assert not hasattr(services, "gamepad")


def test_taking_control_is_explicit_and_requires_the_authority_warning(
    window, services, monkeypatch, qapp
):
    confirm_dialogs(monkeypatch)
    connect(window)
    panel = window.drone_tab.manual_panel

    assert panel._take_control_button.isEnabled() is True
    take_control(window)

    assert panel.controller.engaged is True
    assert services.state.snapshot().control_authority is ControlAuthority.DESKTOP
    assert panel.takeoff_button.isEnabled() is True
    assert all(
        not button.isEnabled() for button in panel._action_buttons.values()
    )

    panel.takeoff_button.click()
    assert pump(
        qapp,
        lambda: services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL,
    )
    assert "takeoff" in services.drone.commands
    assert pump(qapp, lambda: panel._action_buttons[ManualAction.FORWARD].isEnabled())


def test_a_bounded_step_reaches_the_aircraft(window, services, monkeypatch, qapp):
    confirm_dialogs(monkeypatch)
    connect(window)
    panel = window.drone_tab.manual_panel
    take_control(window)
    panel.takeoff_button.click()
    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    assert pump(
        qapp,
        lambda: services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL,
    )
    # The controller rate-limits consecutive commands; wait it out.
    time.sleep(0.55)
    qapp.processEvents()

    panel._action_buttons[ManualAction.FORWARD].click()

    assert pump(qapp, lambda: "forward 30 30" in services.drone.commands)
    assert sent(services.drone) == ("takeoff", "forward 30 30")


def test_keyboard_shortcuts_use_the_same_gate(window, services, monkeypatch, qapp):
    confirm_dialogs(monkeypatch)
    connect(window)
    panel = window.drone_tab.manual_panel
    take_control(window)
    panel.takeoff_button.click()
    assert pump(qapp, lambda: "takeoff" in services.drone.commands)
    assert pump(
        qapp,
        lambda: services.state.snapshot().safety_state is SafetyState.FLYING_MANUAL,
    )
    time.sleep(0.55)
    qapp.processEvents()

    panel._request_action(ManualAction.RIGHT)

    assert pump(qapp, lambda: "right 30 30" in services.drone.commands)


def test_disconnecting_releases_manual_control(window, monkeypatch, qapp):
    confirm_dialogs(monkeypatch)
    connect(window)
    panel = window.drone_tab.manual_panel
    take_control(window)
    panel.takeoff_button.click()
    assert pump(qapp, lambda: panel.controller.engaged and "takeoff" in panel_status(window))

    window.drone_tab._on_disconnect()  # noqa: SLF001 - the UI action itself

    assert panel.controller.engaged is False
    assert panel.takeoff_button.isEnabled() is False


def panel_status(window) -> str:
    return window.drone_tab.manual_panel.manual_status_text
