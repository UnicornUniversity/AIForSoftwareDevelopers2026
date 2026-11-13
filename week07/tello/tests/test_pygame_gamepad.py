"""Pygame gamepad adapter: generic names, missing hardware is not fatal."""

from __future__ import annotations

from types import SimpleNamespace

from drone_vision_lab.adapters.gamepad import PygameGamepad
from drone_vision_lab.errors import HardwareUnavailableError


class FakeJoystick:
    def __init__(
        self,
        name: str = "Test Controller",
        axes: tuple[float, ...] = (0.5, -1.0, -2.0, 0.0),
        buttons: tuple[bool, ...] = (False, True),
    ) -> None:
        self.name = name
        self._axes = axes
        self._buttons = buttons
        self.initialized = False
        self.quit_called = False

    def init(self) -> None:
        self.initialized = True

    def get_name(self) -> str:
        return self.name

    def get_numaxes(self) -> int:
        return len(self._axes)

    def get_axis(self, index: int) -> float:
        return self._axes[index]

    def get_numbuttons(self) -> int:
        return len(self._buttons)

    def get_button(self, index: int) -> bool:
        return self._buttons[index]

    def quit(self) -> None:
        self.quit_called = True


class FakePygame:
    def __init__(self, joystick: FakeJoystick | None) -> None:
        self._joystick = joystick
        self.joystick = SimpleNamespace(
            init=self._init,
            quit=self._quit,
            get_count=self._count,
            Joystick=lambda _index: joystick,
        )
        self.event = SimpleNamespace(pump=self._pump)
        self.count = 1 if joystick is not None else 0
        self.error = RuntimeError
        self.pumped = 0

    def _init(self) -> None:
        pass

    def _quit(self) -> None:
        pass

    def _count(self) -> int:
        return self.count

    def _pump(self) -> None:
        self.pumped += 1


def test_a_missing_controller_is_a_reason_not_an_exception():
    adapter = PygameGamepad(FakePygame(None))

    adapter.open()

    assert adapter.opened is True
    assert adapter.connected is False
    assert "No controller detected" in adapter.reason
    assert adapter.poll().connected is False


def test_missing_pygame_is_reported_without_crashing_the_app():
    def loader():
        raise HardwareUnavailableError(
            "pygame is not installed",
            user_message="Gamepad support needs pygame.",
        )

    adapter = PygameGamepad(loader=loader)

    adapter.open()

    assert adapter.opened is True
    assert adapter.connected is False
    assert adapter.reason == "Gamepad support needs pygame."


def test_axes_and_buttons_use_generic_names_and_stay_in_range():
    joystick = FakeJoystick()
    adapter = PygameGamepad(FakePygame(joystick))
    adapter.open()
    try:
        state = adapter.poll()
    finally:
        adapter.close()

    assert state.connected is True
    assert state.device_name == "Test Controller"
    assert state.axes["axis_0"] == 0.5
    assert state.axes["axis_1"] == -1.0
    assert state.axes["axis_2"] == -1.0  # clamped from -2.0
    assert state.buttons == frozenset({"button_1"})
    assert adapter.reason == ""
    assert joystick.quit_called is True


def test_a_controller_that_disappears_reports_disconnection():
    joystick = FakeJoystick()
    pygame = FakePygame(joystick)
    adapter = PygameGamepad(pygame)
    adapter.open()
    assert adapter.poll().connected is True

    pygame.count = 0
    state = adapter.poll()

    assert state.connected is False
    assert adapter.connected is False
    assert "disconnected" in adapter.reason.lower()


def test_a_driver_error_during_poll_disconnects_instead_of_raising():
    class BrokenJoystick(FakeJoystick):
        def get_axis(self, index: int) -> float:
            raise OSError("device lost")

    adapter = PygameGamepad(FakePygame(BrokenJoystick()))
    adapter.open()

    state = adapter.poll()

    assert state.connected is False
    assert adapter.connected is False
    assert "stopped responding" in adapter.reason


def test_poll_before_open_is_disconnected():
    adapter = PygameGamepad(FakePygame(FakeJoystick()))

    assert adapter.poll().connected is False
    assert adapter.opened is False
