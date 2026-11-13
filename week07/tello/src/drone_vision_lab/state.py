"""Central application state model.

The store is deliberately Qt-free and thread-safe so it can be updated from
worker threads (video, network, inference) and observed safely. The UI bridges
to it with a Qt signal adapter rather than polling.

Phase 1 defines the states and the store. The legal-transition table lives in
:mod:`drone_vision_lab.safety`; tracking, video loss and command failures are
reported here so every panel sees the same state.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

__all__ = [
    "AppStateSnapshot",
    "AppStateStore",
    "ControlAuthority",
    "SafetyState",
    "StateListener",
]

_log = logging.getLogger(__name__)


class SafetyState(StrEnum):
    """Where the aircraft/system is in its supervised life cycle.

    These mirror the states required by the safety state machine. A state
    implies what the operator is allowed to do next; it is not a mode the
    application may skip through automatically.
    """

    DISCONNECTED = "disconnected"
    CONNECTED_GROUNDED = "connected_grounded"
    CAMERA_READY = "camera_ready"
    CALIBRATED = "calibrated"
    DRY_RUN_PASSED = "dry_run_passed"
    ARMED = "armed"
    FLYING_MANUAL = "flying_manual"
    FLYING_MISSION = "flying_mission"
    FLYING_TRACKING = "flying_tracking"
    LANDING_REQUESTED = "landing_requested"
    LANDED_CONFIRMED = "landed_confirmed"
    COMMUNICATION_LOST = "communication_lost"
    FAULT = "fault"

    @property
    def in_flight(self) -> bool:
        return self in (
            SafetyState.FLYING_MANUAL,
            SafetyState.FLYING_MISSION,
            SafetyState.FLYING_TRACKING,
            SafetyState.LANDING_REQUESTED,
        )

    @property
    def display_name(self) -> str:
        return self.value.replace("_", " ").title()


class ControlAuthority(StrEnum):
    """Which controller is currently believed to own the aircraft.

    Standard Tello has no arbitration between the official phone app and a
    desktop client: if both send commands, both take effect. This value records
    the operator's declaration, not something the app can verify.
    """

    NONE = "none"
    DESKTOP = "desktop"
    EXTERNAL_APP = "external_app"


@dataclass(frozen=True, slots=True)
class AppStateSnapshot:
    """Immutable view of the application state at one point in time."""

    safety_state: SafetyState = SafetyState.DISCONNECTED
    control_authority: ControlAuthority = ControlAuthority.NONE
    drone_connected: bool = False
    video_active: bool = False
    video_source_type: str | None = None
    """Which input produced the frames: ``"synthetic"``, ``"file"`` or ``"tello"``.

    ``None`` while no source is running. Experiment exports record this, because
    a metric measured on synthetic frames is not comparable to one measured on
    the aircraft camera and the file must say which it was.
    """
    video_owner: str | None = None
    """Which tab owns the active video source.

    The Tello camera can have only one consumer: UDP port 11111 is exclusive.
    ``"vision_lab"``, ``"tello_flight"``, ``"object_feedback"`` and
    ``"preset_missions"`` are the current owners. A ``None`` owner with
    ``video_active`` true is legacy/test state and is treated as the Computer
    Vision Lab.
    """
    battery_percent: int | None = None
    telemetry_stale: bool = False
    """True when the displayed battery/height is older than the freshness limit.

    The UI still shows the last reported values but must mark them as stale;
    safety gates refuse to use them.
    """
    active_profile_id: str | None = None
    last_error: str | None = None
    dry_run_passed_kinds: tuple[str, ...] = ()
    """Detector kinds (``"opencv"``/``"yolo"``) that passed a dry run.

    The VLM never appears here: it is advisory and cannot gate or enable
    autonomous flight.
    """
    dry_run_partial: bool = False
    """True when some dry-run detector failed while another passed."""
    autonomy_armed: bool = False
    """Set only by an explicit operator action after a successful dry run.

    Nothing in the application arms itself. Arming alone sends no command and
    does not take off; it only permits an explicit Start Tracking once the
    aircraft is already flying under manual control.
    """
    sequence: int = 0


StateListener = Callable[[AppStateSnapshot], None]


class AppStateStore:
    """Thread-safe holder for :class:`AppStateSnapshot`.

    Listeners are invoked outside the internal lock, in subscription order, and
    a listener that raises is logged and skipped so one broken consumer cannot
    break telemetry or the UI.
    """

    def __init__(self, initial: AppStateSnapshot | None = None) -> None:
        self._lock = threading.RLock()
        self._snapshot = initial or AppStateSnapshot()
        self._listeners: list[StateListener] = []

    def snapshot(self) -> AppStateSnapshot:
        with self._lock:
            return self._snapshot

    def update(self, **changes: object) -> AppStateSnapshot:
        """Apply field changes and notify listeners.

        Unknown field names raise ``TypeError`` rather than being absorbed, so a
        typo fails in tests instead of silently doing nothing.
        """
        with self._lock:
            current = self._snapshot
            valid = {f for f in AppStateSnapshot.__slots__}
            unknown = set(changes) - valid - {"sequence"}
            if unknown:
                raise TypeError(f"Unknown AppStateSnapshot field(s): {sorted(unknown)}")
            new = replace(current, sequence=current.sequence + 1, **changes)  # type: ignore[arg-type]
            self._snapshot = new
            listeners = tuple(self._listeners)

        for listener in listeners:
            try:
                listener(new)
            except Exception:  # noqa: BLE001 - a listener must not break the store
                _log.exception("State listener %r failed", listener)
        return new

    def subscribe(self, listener: StateListener) -> Callable[[], None]:
        """Register a listener; returns a callable that removes it."""
        with self._lock:
            self._listeners.append(listener)

        def _unsubscribe() -> None:
            self.unsubscribe(listener)

        return _unsubscribe

    def unsubscribe(self, listener: StateListener) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._listeners.remove(listener)
