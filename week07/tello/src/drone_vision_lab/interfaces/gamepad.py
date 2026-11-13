"""Gamepad input interface.

Windows Bluetooth gamepads expose inconsistent names and layouts, so the
adapter reports *named* axes and buttons after applying the user's mapping.
The application layer only ever sees normalized values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["GamepadAdapter", "GamepadState"]


@dataclass(frozen=True, slots=True)
class GamepadState:
    """One poll of the controller.

    ``axes`` values are normalized to ``[-1.0, 1.0]``; ``buttons`` holds the
    names of buttons that are currently held. Both are empty when nothing is
    connected.
    """

    connected: bool = False
    axes: Mapping[str, float] = field(default_factory=dict)
    buttons: frozenset[str] = frozenset()
    device_name: str | None = None

    def axis(self, name: str, default: float = 0.0) -> float:
        return self.axes.get(name, default)

    def held(self, name: str) -> bool:
        return name in self.buttons


@runtime_checkable
class GamepadAdapter(Protocol):
    """Polling interface for one connected controller."""

    def open(self) -> None:
        """Detect and open a controller. Missing hardware is not an error."""

    def close(self) -> None:
        """Close the controller. Safe to call repeatedly."""

    def poll(self) -> GamepadState:
        """Return the current state. Called from a worker thread, never the UI thread."""
