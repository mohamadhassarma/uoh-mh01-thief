import dataclasses

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.reducers import apply_move
from uoh_mh01.domain.scoring import TerminalCondition
from uoh_mh01.domain.state import MatchState, Side
from uoh_mh01.domain.terminal_detect import (
    UNDEFINED_CEILING,
    detect_from_last_action,
    detect_pre_turn,
)


def test_detect_pre_turn_finds_nothing_on_a_fresh_state(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    assert detect_pre_turn(state, Side.THIEF) is None
    assert detect_pre_turn(state, Side.POLICE) is None


def test_detect_pre_turn_finds_entrapment(config_factory):
    config = config_factory(grid_size=5, thief_start=(0, 0), cop_start=(4, 4))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    boxed = state.board.with_barrier(Position(0, 1)).with_barrier(Position(1, 0))
    state = dataclasses.replace(state, board=boxed)

    result = detect_pre_turn(state, Side.THIEF)

    assert result is not None
    assert result.condition == TerminalCondition.CAPTURE_ENTRAPMENT.value


def test_detect_pre_turn_ignores_entrapment_for_police(config_factory):
    # Police can trap itself (legal, no exception per PRD-01), but entrapment
    # is only ever a THIEF terminal condition.
    config = config_factory(grid_size=5, cop_start=(0, 0))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    boxed = state.board.with_barrier(Position(0, 1)).with_barrier(Position(1, 0))
    state = dataclasses.replace(state, board=boxed)

    assert detect_pre_turn(state, Side.POLICE) is None


def test_detect_pre_turn_finds_the_max_moves_ceiling(config_factory):
    config = config_factory(max_moves=2)
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = dataclasses.replace(state, police_actions_taken=2)

    result = detect_pre_turn(state, Side.POLICE)

    assert result is not None
    assert result.condition == UNDEFINED_CEILING


def test_detect_from_last_action_is_none_on_an_empty_log(config):
    state = MatchState.initial(config, first_mover=Side.POLICE)
    assert detect_from_last_action(state) is None


def test_detect_from_last_action_finds_a_capture_by_landing(config_factory):
    config = config_factory(grid_size=5, cop_start=(2, 2), thief_start=(2, 3))
    state = MatchState.initial(config, first_mover=Side.POLICE)
    state = apply_move(state, Direction.E)  # cop steps onto the thief's cell

    result = detect_from_last_action(state)

    assert result is not None
    assert result.condition == TerminalCondition.CAPTURE_LANDING.value


def test_detect_from_last_action_finds_survival(config_factory):
    config = config_factory(grid_size=5, survival_threshold=1, thief_start=(2, 2), cop_start=(4, 4))
    state = MatchState.initial(config, first_mover=Side.THIEF)
    state = apply_move(state, Direction.E)  # the thief's one required step

    result = detect_from_last_action(state)

    assert result is not None
    assert result.condition == TerminalCondition.SURVIVAL.value
