"""Central application state model."""

from __future__ import annotations

import threading

import pytest

from drone_vision_lab.state import (
    AppStateSnapshot,
    AppStateStore,
    ControlAuthority,
    SafetyState,
)


def test_default_snapshot_is_disconnected():
    snapshot = AppStateStore().snapshot()
    assert snapshot.safety_state is SafetyState.DISCONNECTED
    assert snapshot.drone_connected is False
    assert snapshot.control_authority is ControlAuthority.NONE


def test_update_returns_new_snapshot_and_increments_sequence():
    store = AppStateStore()
    updated = store.update(drone_connected=True, safety_state=SafetyState.CONNECTED_GROUNDED)
    assert updated.sequence == 1
    assert updated.drone_connected is True
    assert store.snapshot() is updated


def test_snapshot_is_immutable():
    snapshot = AppStateStore().snapshot()
    with pytest.raises(AttributeError):
        snapshot.safety_state = SafetyState.FAULT  # type: ignore[misc]


def test_listeners_receive_updates_and_can_unsubscribe():
    store = AppStateStore()
    seen: list[AppStateSnapshot] = []
    unsubscribe = store.subscribe(seen.append)

    store.update(battery_percent=64)
    assert len(seen) == 1
    assert seen[0].battery_percent == 64

    unsubscribe()
    store.update(battery_percent=63)
    assert len(seen) == 1


def test_unsubscribe_is_idempotent():
    store = AppStateStore()
    unsubscribe = store.subscribe(lambda _: None)
    unsubscribe()
    unsubscribe()


def test_broken_listener_does_not_prevent_other_listeners():
    store = AppStateStore()
    seen: list[int] = []

    def boom(_snapshot: AppStateSnapshot) -> None:
        raise RuntimeError("listener failure")

    store.subscribe(boom)
    store.subscribe(lambda s: seen.append(s.sequence))
    store.update(battery_percent=50)
    assert seen == [1]


def test_unknown_field_raises():
    with pytest.raises(TypeError, match="Unknown"):
        AppStateStore().update(not_a_field=1)


def test_concurrent_updates_produce_unique_sequences():
    store = AppStateStore()
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        for _ in range(50):
            store.update(battery_percent=42)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert store.snapshot().sequence == 400


def test_in_flight_helper():
    assert SafetyState.FLYING_MANUAL.in_flight
    assert SafetyState.FLYING_MISSION.in_flight
    assert SafetyState.FLYING_TRACKING.in_flight
    assert not SafetyState.CONNECTED_GROUNDED.in_flight
    assert not SafetyState.LANDED_CONFIRMED.in_flight


def test_display_name_is_human_readable():
    assert SafetyState.LANDING_REQUESTED.display_name == "Landing Requested"
