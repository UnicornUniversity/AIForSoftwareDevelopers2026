"""Pygame-based gamepad adapter.

The adapter never assumes a controller brand or a fixed layout. It reports
``axis_0 .. axis_N`` and ``button_0 .. button_N`` exactly as the driver exposes
them; :mod:`drone_vision_lab.gamepad` maps those names onto flight roles.

This adapter is retained for a future lesson and is not constructed by the
current application. The UI reads no controller input.

``open()`` treats a missing controller (or a missing pygame) as an ordinary
condition and records a reason for the caller — it does not raise, because the
rest of the application must keep working without a gamepad. ``poll()`` is cheap
and non-blocking; it never waits for input.
"""

from __future__ import annotations

import contextlib
import threading
from types import ModuleType
from typing import Any

from ...errors import HardwareUnavailableError
from ...interfaces.gamepad import GamepadState
from ..optional import require_pygame

__all__ = ["PygameGamepad"]

_NO_CONTROLLER = (
    "No controller detected. Pair a Bluetooth gamepad in Windows Settings. "
    "Gamepad input is not wired into this build."
)


class PygameGamepad:
    """One controller; missing hardware or pygame is reported, not raised."""

    def __init__(
        self,
        pygame_module: ModuleType | None = None,
        *,
        loader=require_pygame,
    ) -> None:
        self._pygame = pygame_module
        self._loader = loader
        self._lock = threading.Lock()
        self._joystick: Any = None
        self._device_name: str | None = None
        self._reason = ""
        self._opened = False

    # -- inspection ----------------------------------------------------------

    @property
    def opened(self) -> bool:
        with self._lock:
            return self._opened

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._joystick is not None

    @property
    def device_name(self) -> str | None:
        with self._lock:
            return self._device_name

    @property
    def reason(self) -> str:
        """Why no controller is available, or ``""`` when one is open."""
        with self._lock:
            return self._reason

    # -- GamepadAdapter ------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._joystick is not None:
                return
            if self._pygame is None:
                try:
                    self._pygame = self._loader()
                except HardwareUnavailableError as exc:
                    self._reason = exc.user_message
                    self._opened = True
                    return
            pygame = self._pygame
            try:
                pygame.joystick.init()
                if pygame.joystick.get_count() == 0:
                    self._reason = _NO_CONTROLLER
                    self._opened = True
                    return
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                self._joystick = joystick
                self._device_name = str(joystick.get_name())
                self._reason = ""
                self._opened = True
            except Exception as exc:  # noqa: BLE001 - pygame raises several types
                self._joystick = None
                self._device_name = None
                self._reason = f"Pygame could not open a controller: {exc}"
                self._opened = True

    def close(self) -> None:
        with self._lock:
            joystick = self._joystick
            pygame = self._pygame
            self._joystick = None
            self._device_name = None
            self._opened = False
        if joystick is not None:
            with contextlib.suppress(Exception):
                joystick.quit()
        if pygame is not None:
            with contextlib.suppress(Exception):
                pygame.joystick.quit()

    def poll(self) -> GamepadState:
        with self._lock:
            joystick = self._joystick
            pygame = self._pygame
            name = self._device_name
        if joystick is None or pygame is None:
            return GamepadState(connected=False)

        try:
            pygame.event.pump()
            if pygame.joystick.get_count() == 0:
                self._mark_disconnected("The controller disconnected.")
                return GamepadState(connected=False)
            axes = {
                f"axis_{index}": _clamp(float(joystick.get_axis(index)))
                for index in range(int(joystick.get_numaxes()))
            }
            buttons = frozenset(
                f"button_{index}"
                for index in range(int(joystick.get_numbuttons()))
                if joystick.get_button(index)
            )
        except Exception as exc:  # noqa: BLE001 - a lost controller is ordinary
            self._mark_disconnected(f"The controller stopped responding: {exc}")
            return GamepadState(connected=False)

        return GamepadState(
            connected=True,
            axes=axes,
            buttons=buttons,
            device_name=name,
        )

    # -- internals -----------------------------------------------------------

    def _mark_disconnected(self, reason: str) -> None:
        with self._lock:
            self._joystick = None
            self._device_name = None
            self._reason = reason


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
