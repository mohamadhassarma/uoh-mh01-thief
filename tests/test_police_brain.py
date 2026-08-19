"""PRD-05 section A: ContainmentPoliceBrain's structural guarantees — a
legal move every turn, barrier quota respected, and never a barrier that
self-traps when a non-trapping legal alternative exists."""

from __future__ import annotations

import random
from dataclasses import replace

from uoh_mh01.domain.belief import initial_belief
from uoh_mh01.domain.board import Position
from uoh_mh01.domain.match import BarrierAction, MoveAction
from uoh_mh01.domain.police_brain import ContainmentPoliceBrain
from uoh_mh01.domain.rules import is_barrier_placement_legal, is_move_legal
from uoh_mh01.domain.state import MatchState, Side


def test_always_returns_a_legal_action(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(6, 6), max_barriers=14)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    brain = ContainmentPoliceBrain(random.Random(1))
    brain.belief = initial_belief(state.board)
    for turn in range(1, 11):
        state = replace(state, turn_number=turn)
        action = brain(state, Side.POLICE)
        if isinstance(action, MoveAction):
            assert is_move_legal(state.board, state.cop_pos, action.direction, config.movement)
        else:
            assert isinstance(action, BarrierAction)
            assert is_barrier_placement_legal(state.board, state.cop_pos, action.target, state.barriers_placed, config.movement)
            state = replace(state, board=state.board.with_barrier(action.target), barriers_placed=state.barriers_placed + 1)


def test_never_self_traps_when_a_safe_barrier_or_move_exists(config_factory):
    # Corner start: only 2 orthogonal neighbours exist at all, so a naive
    # "place wherever reduces area most" brain could wall itself in.
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(6, 6), max_barriers=14)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    brain = ContainmentPoliceBrain(random.Random(1))
    brain.belief = initial_belief(state.board)
    # Force containment mode (turn_number beyond half of max_moves).
    state = replace(state, turn_number=config.movement.max_moves)
    action = brain(state, Side.POLICE)
    if isinstance(action, BarrierAction):
        trial = state.board.with_barrier(action.target)
        assert any(is_move_legal(trial, state.cop_pos, d, config.movement) for d in config.movement.move_set if d != "STAY")


def test_pursuit_moves_toward_a_sharp_nearby_hotspot(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(0, 6))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    brain = ContainmentPoliceBrain(random.Random(1))
    belief = dict.fromkeys(initial_belief(state.board), 0.0)
    belief[Position(0, 3)] = 1.0
    brain.belief = belief
    action = brain(state, Side.POLICE)
    assert isinstance(action, MoveAction)
    assert action.direction.value in ("E", "S", "N")  # any move that does not increase distance from (0,3)


def test_containment_never_fires_before_the_halfway_turn(config_factory):
    config = config_factory(grid_size=7, cop_start=(2, 2), thief_start=(2, 3), max_barriers=14)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    brain = ContainmentPoliceBrain(random.Random(1))
    belief = dict.fromkeys(initial_belief(state.board), 0.0)
    belief[Position(2, 2)] = 1.0  # own cell itself is the hotspot: max possible reduction available
    brain.belief = belief
    action = brain(state, Side.POLICE)  # turn_number == 1, well before max_moves // 2
    assert isinstance(action, MoveAction)  # never a BarrierAction this early, however tempting


def test_deterministic_given_the_same_seed(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(6, 6))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    belief = initial_belief(state.board)
    a = ContainmentPoliceBrain(random.Random(42))
    b = ContainmentPoliceBrain(random.Random(42))
    a.belief = belief
    b.belief = belief
    assert a(state, Side.POLICE) == b(state, Side.POLICE)
