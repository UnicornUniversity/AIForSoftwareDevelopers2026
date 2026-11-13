"""Legal safety-state transitions.

The state enum lives in :mod:`drone_vision_lab.state`; this module owns the
question "may the application move from here to there?". It is deliberately
Qt-free so the same rules can be tested without a window and reused by the
tracking controller.

The table is conservative rather than convenient:

* Grounded states climb the workflow in order. Arming is only reachable from a
  successful dry run, and nothing in this module takes off or arms by itself.
* A landing request is never followed by a return to manual control on the
  strength of an acknowledgement. Only independently observed evidence moves
  the state to :attr:`SafetyState.LANDED_CONFIRMED`.
* A command-channel loss goes to :attr:`SafetyState.COMMUNICATION_LOST`, never
  to a state that implies the aircraft landed.
* Fault and communication-loss states can only be left by reconnecting or by
  disconnecting; they cannot silently resume flight.
"""

from __future__ import annotations

from collections.abc import Mapping

from .state import AppStateSnapshot, AppStateStore, SafetyState

__all__ = [
    "LEGAL_TRANSITIONS",
    "InvalidTransition",
    "SafetyStateMachine",
    "can_transition",
]

LEGAL_TRANSITIONS: Mapping[SafetyState, frozenset[SafetyState]] = {
    SafetyState.DISCONNECTED: frozenset(
        {SafetyState.CONNECTED_GROUNDED, SafetyState.FAULT}
    ),
    SafetyState.CONNECTED_GROUNDED: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CAMERA_READY,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.CAMERA_READY: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.CALIBRATED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.CALIBRATED: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.CAMERA_READY,
            SafetyState.DRY_RUN_PASSED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.DRY_RUN_PASSED: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.CAMERA_READY,
            SafetyState.CALIBRATED,
            SafetyState.ARMED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.ARMED: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.DRY_RUN_PASSED,
            SafetyState.FLYING_MANUAL,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.FLYING_MANUAL: frozenset(
        {
            SafetyState.FLYING_TRACKING,
            SafetyState.FLYING_MISSION,
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.FLYING_MISSION: frozenset(
        {
            SafetyState.FLYING_MANUAL,
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.FLYING_TRACKING: frozenset(
        {
            SafetyState.FLYING_MANUAL,
            SafetyState.LANDING_REQUESTED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    # A landing request is a one-way door until evidence arrives. A failed
    # landing goes to FAULT, not back to a flying state.
    SafetyState.LANDING_REQUESTED: frozenset(
        {
            SafetyState.LANDED_CONFIRMED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.LANDED_CONFIRMED: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.COMMUNICATION_LOST,
            SafetyState.FAULT,
        }
    ),
    SafetyState.COMMUNICATION_LOST: frozenset(
        {
            SafetyState.DISCONNECTED,
            SafetyState.CONNECTED_GROUNDED,
            SafetyState.FAULT,
        }
    ),
    SafetyState.FAULT: frozenset(
        {SafetyState.DISCONNECTED, SafetyState.CONNECTED_GROUNDED}
    ),
}


def can_transition(current: SafetyState, target: SafetyState) -> bool:
    """True when ``current → target`` is legal (or a no-op)."""
    if current is target:
        return True
    return target in LEGAL_TRANSITIONS.get(current, frozenset())


class InvalidTransition(RuntimeError):
    """Raised when code attempts a transition the safety model forbids."""

    def __init__(self, current: SafetyState, target: SafetyState) -> None:
        super().__init__(
            f"Illegal safety-state transition: {current.value} → {target.value}"
        )
        self.current = current
        self.target = target


class SafetyStateMachine:
    """Applies legal transitions to the shared store.

    The store remains the single source of truth. Listeners see each change and
    every UI panel refreshes from the new snapshot.
    """

    def __init__(self, store: AppStateStore) -> None:
        self._store = store

    @property
    def state(self) -> SafetyState:
        return self._store.snapshot().safety_state

    def can_move(self, target: SafetyState) -> bool:
        return can_transition(self.state, target)

    def move(self, target: SafetyState, *, reason: str | None = None) -> AppStateSnapshot:
        """Move to ``target`` and optionally record ``reason`` as ``last_error``.

        Raises :class:`InvalidTransition` without touching the store when the
        move is not in the table.
        """
        current = self._store.snapshot()
        if not can_transition(current.safety_state, target):
            raise InvalidTransition(current.safety_state, target)
        if current.safety_state is target:
            if reason is None or reason == current.last_error:
                return current
            return self._store.update(last_error=reason)
        changes: dict[str, object] = {"safety_state": target}
        if reason is not None:
            changes["last_error"] = reason
        return self._store.update(**changes)
