import pytest

from uoh_mh01.domain.board import Direction, Position
from uoh_mh01.domain.match import (
    BarrierAction,
    MoveAction,
    UndefinedOutcomeError,
    run_match,
)
from uoh_mh01.domain.scoring import TerminalCondition
from uoh_mh01.domain.state import Side


def _scripted_strategy(actions):
    it = iter(actions)

    def strategy(state, side):
        return next(it)

    return strategy


def _stay_forever(state, side):
    return MoveAction(Direction.STAY)


def _scripted_then_stay(actions):
    """Like _scripted_strategy, but falls back to STAY forever once the
    script is exhausted, instead of raising StopIteration."""
    it = iter(actions)

    def strategy(state, side):
        try:
            return next(it)
        except StopIteration:
            return MoveAction(Direction.STAY)

    return strategy


def test_full_match_runs_to_a_terminal_state_without_crashing(config):
    result = run_match(config, _stay_forever, _stay_forever)
    assert result.terminal_condition is TerminalCondition.SURVIVAL


def test_capture_by_landing_end_to_end(config_factory):
    config = config_factory(cop_start=(2, 1), thief_start=(2, 2), survival_threshold=100, max_moves=1000)
    police = _scripted_strategy([MoveAction(Direction.E)])
    result = run_match(config, police, _stay_forever)
    assert result.terminal_condition is TerminalCondition.CAPTURE_LANDING
    assert (result.police_score, result.thief_score) == (config.scoring.capture_cop, config.scoring.capture_thief)


def test_capture_by_barrier_end_to_end(config_factory):
    config = config_factory(cop_start=(2, 1), thief_start=(2, 2), survival_threshold=100, max_moves=1000)
    police = _scripted_strategy([BarrierAction(Position(2, 2))])
    result = run_match(config, police, _stay_forever)
    assert result.terminal_condition is TerminalCondition.CAPTURE_BARRIER
    assert (result.police_score, result.thief_score) == (config.scoring.capture_cop, config.scoring.capture_thief)
    assert result.final_state.move_log[-1].capture_claimed_by_police


def test_capture_by_entrapment_end_to_end(config_factory):
    # 5x5 board, cop starts (0,0), thief sits still at (2,2) the whole time.
    # The police script walks to each of the thief's four orthogonal
    # neighbours in turn and barricades it from its own cell, carefully
    # never stepping onto (2,2) itself and never crossing an
    # already-placed barrier. Once all four neighbours are barriers, the
    # thief is trapped on its next turn — before it ever gets to act.
    config = config_factory(
        grid_size=5, cop_start=(0, 0), thief_start=(2, 2), max_barriers=4, survival_threshold=1000, max_moves=1000
    )
    police_script = [
        MoveAction(Direction.E),  # (0,0) -> (0,1)
        MoveAction(Direction.E),  # (0,1) -> (0,2)
        MoveAction(Direction.S),  # (0,2) -> (1,2)
        BarrierAction(Position(1, 2)),  # north neighbour of thief
        MoveAction(Direction.E),  # (1,2) -> (1,3)
        MoveAction(Direction.S),  # (1,3) -> (2,3)
        BarrierAction(Position(2, 3)),  # east neighbour of thief
        MoveAction(Direction.S),  # (2,3) -> (3,3)
        MoveAction(Direction.W),  # (3,3) -> (3,2)
        BarrierAction(Position(3, 2)),  # south neighbour of thief
        MoveAction(Direction.W),  # (3,2) -> (3,1)
        MoveAction(Direction.N),  # (3,1) -> (2,1)
        BarrierAction(Position(2, 1)),  # west neighbour of thief
    ]
    police = _scripted_strategy(police_script)
    result = run_match(config, police, _stay_forever)
    assert result.terminal_condition is TerminalCondition.CAPTURE_ENTRAPMENT
    assert (result.police_score, result.thief_score) == (config.scoring.capture_cop, config.scoring.capture_thief)
    assert result.final_state.thief_pos == Position(2, 2)  # thief never moved


def test_police_entrapment_is_not_a_terminal_condition(config_factory):
    # The rulebook defines entrapment for the thief only. A fully walled-in
    # police agent must NOT end the match — it should just keep STAYing while
    # the thief proceeds normally, here all the way to a SURVIVAL win. If any
    # entrapment logic were (incorrectly) applied symmetrically to the
    # police, this match would end early in some capture-like state instead.
    cop_pos = Position(2, 2)
    # survival_threshold must be comfortably above 4: the police script needs
    # 4 full rounds to finish walling itself in (one barrier per round), so
    # the thief must not win before that script completes, or the test would
    # not actually be exercising "match continues after police is trapped."
    config = config_factory(
        grid_size=5,
        cop_start=(cop_pos.row, cop_pos.col),
        thief_start=(4, 4),
        max_barriers=4,
        survival_threshold=6,
        max_moves=1000,
    )
    police_script = [
        BarrierAction(Position(1, 2)),
        BarrierAction(Position(3, 2)),
        BarrierAction(Position(2, 1)),
        BarrierAction(Position(2, 3)),
    ]
    police = _scripted_then_stay(police_script)
    result = run_match(config, police, _stay_forever)

    assert result.terminal_condition is TerminalCondition.SURVIVAL
    assert result.final_state.barriers_placed == 4
    assert result.final_state.cop_pos == cop_pos  # police sat inside its own walls the whole time


def test_technical_loss_when_a_strategy_returns_an_illegal_move(config_factory):
    config = config_factory(cop_start=(0, 0))
    illegal_police = _scripted_strategy([MoveAction(Direction.N)])  # off-board from (0,0)
    result = run_match(config, illegal_police, _stay_forever)
    assert result.terminal_condition is TerminalCondition.TECHNICAL_LOSS
    assert result.offending_side is Side.POLICE
    assert (result.police_score, result.thief_score) == (config.scoring.technical_loss, config.scoring.technical_loss)


def test_survival_triggers_at_exactly_the_threshold(config_factory):
    threshold = 5
    # Cop stays put far from the thief, far enough it can never reach it in
    # `threshold` of its own turns, so nothing but SURVIVAL can fire first.
    config = config_factory(
        grid_size=7, cop_start=(0, 0), thief_start=(6, 6), survival_threshold=threshold, max_moves=1000
    )
    result = run_match(config, _stay_forever, _stay_forever)
    assert result.terminal_condition is TerminalCondition.SURVIVAL
    assert result.final_state.thief_survived_steps == threshold


def test_max_moves_without_another_terminal_condition_is_undefined_not_guessed(config_factory):
    # Cop and thief both stay put forever: no capture, and survival_threshold
    # is set higher than max_moves so SURVIVAL cannot fire first either.
    config = config_factory(
        cop_start=(0, 0), thief_start=(4, 4), grid_size=5, survival_threshold=1000, max_moves=4
    )
    with pytest.raises(UndefinedOutcomeError):
        run_match(config, _stay_forever, _stay_forever)
