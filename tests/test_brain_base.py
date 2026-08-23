"""PRD-05/PRD-06: zero-trust is now STRUCTURAL, and the BrainBase plumbing.

`_OpponentPositionGuard` is gone. It wrapped a state object that still HELD
the opponent's position and blocked exactly one attribute name — defeatable by
any transitive path (`state.move_log` carried both positions and passed
straight through `__getattr__`). A brain is now handed an `OwnGameState`,
which has no opponent-position field to leak. These tests pin that property at
the type level, which is the only place it can actually be guaranteed.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.brain_base import BrainBase, load_brain_class
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.own_state import OwnGameState, own_view
from uoh_mh01.domain.state import MatchState, Side


def test_own_game_state_has_no_opponent_position_field_at_all(config):
    own = OwnGameState.initial(config, Side.POLICE)
    fields = {f.name for f in dataclasses.fields(own)}
    assert "thief_pos" not in fields
    assert "cop_pos" not in fields
    # And nothing reachable smuggles it back in: the step log is own-only.
    assert all("thief" not in f.name and "cop" not in f.name for f in dataclasses.fields(own))


def test_own_game_state_exposes_only_my_own_position(config):
    police = OwnGameState.initial(config, Side.POLICE)
    thief = OwnGameState.initial(config, Side.THIEF)
    assert police.own_pos == Position(*config.board.cop_start)
    assert thief.own_pos == Position(*config.board.thief_start)
    with pytest.raises(AttributeError):
        police.thief_pos  # noqa: B018 - the field does not exist to be read


def test_own_view_projects_the_simulator_state_without_leaking_the_opponent(config):
    """The simulator legitimately holds both positions; a brain driven by it
    must still see only its own side."""
    state = MatchState.initial(config, first_mover=Side.THIEF)
    projected = own_view(state, Side.POLICE)
    assert projected.own_pos == state.cop_pos
    assert not hasattr(projected, "thief_pos")


def test_a_brain_driven_by_the_simulator_receives_the_projected_own_view(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    seen = {}

    class Recorder(BrainBase):
        def _pick_move(self, own, side):
            seen["own"] = own
            return MoveAction(Direction.STAY)

    Recorder(random.Random(1))(state, Side.POLICE)
    assert isinstance(seen["own"], OwnGameState)
    assert seen["own"].own_pos == state.cop_pos
    assert not hasattr(seen["own"], "thief_pos")


def test_belief_is_set_by_the_caller_on_the_brain_not_passed_in_the_state(config):
    state = OwnGameState.initial(config, Side.POLICE)
    seen = {}

    class ReadsBelief(BrainBase):
        def _pick_move(self, own, side):
            seen["belief"] = self.belief
            return MoveAction(Direction.STAY)

    brain = ReadsBelief(random.Random(1))
    brain.belief = {Position(0, 0): 1.0}
    brain(state, Side.POLICE)
    assert seen["belief"] == {Position(0, 0): 1.0}


def test_default_pick_move_is_legal(config):
    brain = BrainBase(random.Random(1))
    action = brain(OwnGameState.initial(config, Side.THIEF), Side.THIEF)
    assert isinstance(action, MoveAction)


def test_default_hint_is_truthful_and_returned_by_last_hint(config):
    brain = BrainBase(random.Random(1))
    brain(OwnGameState.initial(config, Side.POLICE), Side.POLICE)
    text, is_true = brain.last_hint
    assert is_true is True
    assert text


def test_load_brain_class_resolves_a_real_subclass():
    assert issubclass(load_brain_class("uoh_mh01.domain.police_brain:ContainmentPoliceBrain"), BrainBase)


def test_load_brain_class_rejects_malformed_path():
    with pytest.raises(ValueError, match="package.module:ClassName"):
        load_brain_class("not_a_valid_path")


def test_load_brain_class_rejects_non_brain_class():
    with pytest.raises(ValueError, match="BrainBase"):
        load_brain_class("uoh_mh01.domain.board:Position")
