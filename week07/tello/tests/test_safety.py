"""Legal safety-state transitions and the guarded state machine."""

from __future__ import annotations

import pytest

from drone_vision_lab.safety import (
    LEGAL_TRANSITIONS,
    InvalidTransition,
    SafetyStateMachine,
    can_transition,
)
from drone_vision_lab.state import AppStateStore, SafetyState


def test_every_state_has_a_transition_entry():
    assert set(LEGAL_TRANSITIONS) == set(SafetyState)


def test_grounded_workflow_is_ordered():
    assert can_transition(SafetyState.DISCONNECTED, SafetyState.CONNECTED_GROUNDED)
    assert can_transition(SafetyState.CONNECTED_GROUNDED, SafetyState.CAMERA_READY)
    assert can_transition(SafetyState.CAMERA_READY, SafetyState.CALIBRATED)
    assert can_transition(SafetyState.CALIBRATED, SafetyState.DRY_RUN_PASSED)
    assert can_transition(SafetyState.DRY_RUN_PASSED, SafetyState.ARMED)
    assert not can_transition(SafetyState.CONNECTED_GROUNDED, SafetyState.ARMED)
    assert not can_transition(SafetyState.CALIBRATED, SafetyState.FLYING_MANUAL)


def test_arming_stays_grounded_until_an_explicit_takeoff():
    assert SafetyState.ARMED in LEGAL_TRANSITIONS[SafetyState.DRY_RUN_PASSED]
    assert SafetyState.FLYING_TRACKING not in LEGAL_TRANSITIONS[SafetyState.ARMED]
    assert SafetyState.LANDING_REQUESTED not in LEGAL_TRANSITIONS[SafetyState.ARMED]


def test_tracking_can_be_started_only_from_manual_flight():
    assert can_transition(SafetyState.FLYING_MANUAL, SafetyState.FLYING_TRACKING)
    assert not can_transition(SafetyState.ARMED, SafetyState.FLYING_TRACKING)
    assert not can_transition(SafetyState.DRY_RUN_PASSED, SafetyState.FLYING_TRACKING)


def test_tracking_loss_returns_to_operator_attention():
    assert can_transition(SafetyState.FLYING_TRACKING, SafetyState.FLYING_MANUAL)
    assert can_transition(SafetyState.FLYING_TRACKING, SafetyState.LANDING_REQUESTED)
    assert can_transition(SafetyState.FLYING_TRACKING, SafetyState.COMMUNICATION_LOST)


def test_landing_request_is_not_reversible_without_evidence():
    assert can_transition(SafetyState.LANDING_REQUESTED, SafetyState.LANDED_CONFIRMED)
    assert not can_transition(SafetyState.LANDING_REQUESTED, SafetyState.FLYING_MANUAL)
    assert not can_transition(SafetyState.LANDED_CONFIRMED, SafetyState.FLYING_MANUAL)


def test_communication_loss_never_claims_a_landing():
    assert not can_transition(
        SafetyState.COMMUNICATION_LOST, SafetyState.LANDED_CONFIRMED
    )
    assert not can_transition(SafetyState.COMMUNICATION_LOST, SafetyState.FLYING_MANUAL)


@pytest.mark.parametrize(
    "state",
    [
        SafetyState.FLYING_MANUAL,
        SafetyState.FLYING_MISSION,
        SafetyState.FLYING_TRACKING,
    ],
)
def test_emergency_land_transition_is_legal_while_flying(state):
    assert can_transition(state, SafetyState.LANDING_REQUESTED)


def test_state_machine_applies_a_legal_move_and_records_the_reason():
    store = AppStateStore()
    machine = SafetyStateMachine(store)
    machine.move(SafetyState.CONNECTED_GROUNDED)

    snapshot = machine.move(
        SafetyState.COMMUNICATION_LOST, reason="Command channel stopped answering."
    )

    assert snapshot.safety_state is SafetyState.COMMUNICATION_LOST
    assert snapshot.last_error == "Command channel stopped answering."
    assert snapshot.sequence == 2


def test_state_machine_refuses_an_illegal_move_without_changing_the_store():
    store = AppStateStore()
    machine = SafetyStateMachine(store)
    machine.move(SafetyState.CONNECTED_GROUNDED)

    with pytest.raises(InvalidTransition, match="connected_grounded"):
        machine.move(SafetyState.FLYING_TRACKING)

    assert store.snapshot().safety_state is SafetyState.CONNECTED_GROUNDED


def test_moving_to_the_current_state_is_a_no_op():
    store = AppStateStore()
    machine = SafetyStateMachine(store)

    snapshot = machine.move(SafetyState.DISCONNECTED)

    assert snapshot.sequence == 0
