import pytest

from uoh_mh01.infra.state_machine import (
    TRANSITIONS,
    IllegalTransitionError,
    Phase,
    StateMachine,
)


@pytest.mark.parametrize(
    "start,target",
    [
        (Phase.WAITING_FOR_OPPONENT, Phase.COMPUTING_MOVE),
        (Phase.COMPUTING_MOVE, Phase.COMMITTING),
        (Phase.COMPUTING_MOVE, Phase.TECHNICAL_LOSS),
        (Phase.COMMITTING, Phase.AWAITING_REVEAL),
        (Phase.AWAITING_REVEAL, Phase.VERIFYING),
        (Phase.AWAITING_REVEAL, Phase.TECHNICAL_LOSS),
        (Phase.VERIFYING, Phase.WAITING_FOR_OPPONENT),
    ],
)
def test_every_legal_transition_succeeds(start, target):
    sm = StateMachine(initial=start)
    sm.transition(target)
    assert sm.phase is target
    assert sm.history == [start, target]


@pytest.mark.parametrize(
    "start,target",
    [
        (Phase.WAITING_FOR_OPPONENT, Phase.COMMITTING),
        (Phase.WAITING_FOR_OPPONENT, Phase.AWAITING_REVEAL),
        (Phase.WAITING_FOR_OPPONENT, Phase.VERIFYING),
        (Phase.WAITING_FOR_OPPONENT, Phase.TECHNICAL_LOSS),
        (Phase.COMPUTING_MOVE, Phase.WAITING_FOR_OPPONENT),
        (Phase.COMPUTING_MOVE, Phase.AWAITING_REVEAL),
        (Phase.COMPUTING_MOVE, Phase.VERIFYING),
        (Phase.COMMITTING, Phase.WAITING_FOR_OPPONENT),
        (Phase.COMMITTING, Phase.COMPUTING_MOVE),
        (Phase.COMMITTING, Phase.TECHNICAL_LOSS),
        (Phase.COMMITTING, Phase.VERIFYING),
        (Phase.AWAITING_REVEAL, Phase.WAITING_FOR_OPPONENT),
        (Phase.AWAITING_REVEAL, Phase.COMPUTING_MOVE),
        (Phase.AWAITING_REVEAL, Phase.COMMITTING),
        (Phase.VERIFYING, Phase.COMPUTING_MOVE),
        (Phase.VERIFYING, Phase.COMMITTING),
        (Phase.VERIFYING, Phase.AWAITING_REVEAL),
        (Phase.VERIFYING, Phase.TECHNICAL_LOSS),
        (Phase.TECHNICAL_LOSS, Phase.WAITING_FOR_OPPONENT),
        (Phase.TECHNICAL_LOSS, Phase.COMPUTING_MOVE),
    ],
)
def test_every_illegal_transition_raises(start, target):
    sm = StateMachine(initial=start)
    with pytest.raises(IllegalTransitionError) as excinfo:
        sm.transition(target)
    assert excinfo.value.current is start
    assert excinfo.value.attempted is target
    assert sm.phase is start  # the machine is NOT left in an undefined state


def test_illegal_transition_leaves_history_untouched():
    sm = StateMachine(initial=Phase.WAITING_FOR_OPPONENT)
    with pytest.raises(IllegalTransitionError):
        sm.transition(Phase.VERIFYING)
    assert sm.history == [Phase.WAITING_FOR_OPPONENT]


def test_technical_loss_is_terminal():
    sm = StateMachine(initial=Phase.TECHNICAL_LOSS)
    assert sm.is_terminal()
    assert TRANSITIONS[Phase.TECHNICAL_LOSS] == frozenset()


def test_full_cycle_returns_to_waiting():
    sm = StateMachine()
    assert sm.phase is Phase.WAITING_FOR_OPPONENT
    sm.transition(Phase.COMPUTING_MOVE)
    sm.transition(Phase.COMMITTING)
    sm.transition(Phase.AWAITING_REVEAL)
    sm.transition(Phase.VERIFYING)
    sm.transition(Phase.WAITING_FOR_OPPONENT)
    assert sm.phase is Phase.WAITING_FOR_OPPONENT
    assert not sm.is_terminal()


def test_all_phases_covered_by_transition_table():
    assert set(TRANSITIONS.keys()) == set(Phase)
