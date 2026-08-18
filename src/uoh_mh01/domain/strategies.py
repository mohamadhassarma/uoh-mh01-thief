"""Placeholder move-selection logic — NOT the strategy brain.

The real decision-making mechanism (belief map, pheromones, LLM layer) is
stage 5 (PRD-05). This module exists only so `python -m uoh_mh01 selftest`
can play a full match end-to-end today, using either the first legal action
found or a uniformly-random legal action.
"""

from __future__ import annotations

import random

from .board import Direction
from .match import Action, BarrierAction, MoveAction, Strategy
from .rules import is_barrier_placement_legal, legal_moves
from .state import MatchState, Side


def legal_actions(state: MatchState, side: Side) -> tuple[Action, ...]:
    """Every legal action available to `side` in `state`.

    For the thief this is just its legal moves. For the police it is legal
    moves PLUS legal barrier placements — move-or-barrier is a single choice
    among peers, not two separate decisions (rule: "MOVES, or forgoes
    movement to PLACE A BARRIER. Not both in the same turn").
    """
    movement = state.config.movement
    pos = state.cop_pos if side is Side.POLICE else state.thief_pos
    actions: list[Action] = [MoveAction(d) for d in legal_moves(state.board, pos, movement)]

    if side is Side.POLICE:
        candidates = (state.cop_pos, *state.board.orthogonal_neighbors(state.cop_pos))
        actions += [
            BarrierAction(target)
            for target in candidates
            if is_barrier_placement_legal(state.board, state.cop_pos, target, state.barriers_placed, movement)
        ]

    return tuple(actions)


def first_legal_strategy(state: MatchState, side: Side) -> Action:
    """Deterministic placeholder: always STAY if legal, else the first legal
    action found. Mainly useful for tests that need reproducible matches."""
    actions = legal_actions(state, side)
    for action in actions:
        if isinstance(action, MoveAction) and action.direction is Direction.STAY:
            return action
    return actions[0]


def make_random_strategy(rng: random.Random) -> Strategy:
    """A placeholder strategy that picks uniformly among all legal actions.

    Takes an explicit Random instance so callers (e.g. the selftest CLI) can
    seed it for a reproducible match.
    """

    def strategy(state: MatchState, side: Side) -> Action:
        actions = legal_actions(state, side)
        return rng.choice(actions)

    return strategy
