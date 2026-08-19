"""PRD-05 section B: EvasiveThiefBrain's structural guarantees — a legal
move every turn, deterministic given a seed, and trail-breaking actually
breaks a streak instead of only claiming to."""

from __future__ import annotations

import random

from uoh_mh01.domain.belief import initial_belief
from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.rules import is_move_legal
from uoh_mh01.domain.state import MatchState, Side
from uoh_mh01.domain.thief_brain import EvasiveThiefBrain


def test_always_returns_a_legal_move(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(6, 6))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    brain = EvasiveThiefBrain(random.Random(1))
    brain.belief = initial_belief(state.board)
    action = brain(state, Side.THIEF)
    assert is_move_legal(state.board, state.thief_pos, action.direction, config.movement)


def test_deterministic_given_the_same_seed(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(6, 6))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    belief = initial_belief(state.board)
    a = EvasiveThiefBrain(random.Random(7))
    b = EvasiveThiefBrain(random.Random(7))
    a.belief = belief
    b.belief = belief
    assert a(state, Side.THIEF) == b(state, Side.THIEF)


def test_forces_a_direction_change_after_the_streak_limit(config_factory):
    # A large open board with no threat nearby: nothing but the streak
    # limit should stop the brain picking the same direction forever.
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(3, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    brain = EvasiveThiefBrain(random.Random(3))
    brain.belief = initial_belief(state.board)  # uniform: no threat signal at all
    brain._last_direction = Direction.E
    brain._streak = 3  # already at the break limit
    action = brain(state, Side.THIEF)
    assert action.direction is not Direction.E


def test_evades_when_under_threat(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(3, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    brain = EvasiveThiefBrain(random.Random(1))
    belief = dict.fromkeys(initial_belief(state.board), 0.0)
    belief[Position(3, 4)] = 1.0  # threat immediately adjacent
    brain.belief = belief
    action = brain(state, Side.THIEF)
    # Moving toward (3,4) would be foolish; W or N/S (away) should be picked
    # far more often than E across several draws — check it is not E here.
    assert action.direction.value != "E"


def test_generates_a_hint_every_turn(config_factory):
    config = config_factory(grid_size=7, cop_start=(0, 0), thief_start=(3, 3))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    brain = EvasiveThiefBrain(random.Random(1))
    brain.belief = initial_belief(state.board)
    brain(state, Side.THIEF)
    text, is_true = brain.last_hint
    assert text
    assert is_true in (True, False)
