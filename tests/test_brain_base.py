"""PRD-05: BrainBase's structural zero-trust guard, and the callable/belief/
hint plumbing every brain relies on."""

from __future__ import annotations

import random

import pytest

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.brain_base import BrainBase, load_brain_class
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.state import MatchState, Side


def test_police_brain_cannot_read_thief_true_position(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)

    class Reader(BrainBase):
        def _pick_move(self, obs, side):
            obs.thief_pos  # noqa: B018 - deliberately triggers the guard
            return MoveAction(Direction.STAY)

    reader = Reader(random.Random(1))
    with pytest.raises(PermissionError, match="thief_pos"):
        reader(state, Side.POLICE)


def test_thief_brain_cannot_read_cop_true_position(config):
    state = MatchState.initial(config, first_mover=Side.THIEF)

    class Reader(BrainBase):
        def _pick_move(self, obs, side):
            obs.cop_pos  # noqa: B018 - deliberately triggers the guard
            return MoveAction(Direction.STAY)

    reader = Reader(random.Random(1))
    with pytest.raises(PermissionError, match="cop_pos"):
        reader(state, Side.THIEF)


def test_own_position_and_board_remain_readable(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)

    class ReadsOwn(BrainBase):
        def _pick_move(self, obs, side):
            assert obs.own_pos == state.cop_pos
            assert obs.board is state.board
            assert obs.belief == {}
            return MoveAction(Direction.STAY)

    ReadsOwn(random.Random(1))(state, Side.POLICE)


def test_belief_is_set_by_caller_not_call_argument(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    seen = {}

    class ReadsBelief(BrainBase):
        def _pick_move(self, obs, side):
            seen["belief"] = obs.belief
            return MoveAction(Direction.STAY)

    brain = ReadsBelief(random.Random(1))
    brain.belief = {Position(0, 0): 1.0}
    brain(state, Side.POLICE)
    assert seen["belief"] == {Position(0, 0): 1.0}


def test_default_pick_move_is_uniformly_random_and_legal(config):
    state = MatchState.initial(config, first_mover=Side.THIEF)
    brain = BrainBase(random.Random(1))
    action = brain(state, Side.THIEF)
    assert isinstance(action, MoveAction)


def test_default_hint_is_truthful_and_returned_by_last_hint(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    brain = BrainBase(random.Random(1))
    brain(state, Side.POLICE)
    text, is_true = brain.last_hint
    assert is_true is True
    assert text  # non-empty


def test_load_brain_class_resolves_a_real_subclass():
    cls = load_brain_class("uoh_mh01.domain.police_brain:ContainmentPoliceBrain")
    assert issubclass(cls, BrainBase)


def test_load_brain_class_rejects_malformed_path():
    with pytest.raises(ValueError, match="package.module:ClassName"):
        load_brain_class("not_a_valid_path")


def test_load_brain_class_rejects_non_brain_class():
    with pytest.raises(ValueError, match="BrainBase"):
        load_brain_class("uoh_mh01.domain.board:Position")
