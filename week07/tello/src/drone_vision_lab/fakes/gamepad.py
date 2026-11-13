"""Scripted gamepad adapter.

Lets the retained gamepad pipeline be developed and tested on a machine with no
controller paired. The current application does not build this adapter.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..interfaces.gamepad import GamepadState

__all__ = ["FakeGamepad"]


class FakeGamepad:
    """Returns a queue of scripted states, repeating the last one forever."""

    def __init__(
        self,
        states: Iterable[GamepadState] | None = None,
        *,
        device_name: str | None = "Simulated controller",
    ) -> None:
        self._states = list(states or [])
        self._device_name = device_name
        self._index = 0
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def poll(self) -> GamepadState:
        if not self._open or not self._states:
            return GamepadState(connected=False)
        state = self._states[min(self._index, len(self._states) - 1)]
        self._index += 1
        return state

    def push(self, state: GamepadState) -> None:
        self._states.append(state)
