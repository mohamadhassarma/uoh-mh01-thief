"""The match loop: drives config, board, rules, state and scoring to play
one match to a terminal state.

Two rule-book gaps are resolved here as explicit, provisional, named
constants rather than being silently baked into the loop — see PRD-01
"Open questions" for the full rationale on both:

  - FIRST_MOVER: the rulebook does not say who moves first.
  - MAX_MOVES_COUNTING_BASIS: the rulebook does not say what a "move" is for
    max_moves-ceiling purposes (per-player vs combined actions). Switched
    from a combined-actions reading to per-player after empirical testing
    showed the combined reading makes survival_threshold structurally
    unreachable at the contract's default values — see PRD-01.

A third gap has no resolution at all, by design: if max_moves is reached
without any other terminal condition having fired, `run_match` raises
UndefinedOutcomeError instead of guessing a score. That is not a bug —
the rulebook simply does not define this outcome (see PRD-01).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .board import Direction, Position
from .config import GameConfig
from .house_rules import CAPTURE_CLAIM_MECHANIC, FIRST_MOVER, MAX_MOVES_COUNTING_BASIS
from .reducers import apply_barrier, apply_move
from .rules import is_thief_trapped
from .scoring import TerminalCondition, score_for
from .state import ActionType, IllegalActionError, MatchState, Side, actions_taken_by, next_turn

__all__ = [
    "CAPTURE_CLAIM_MECHANIC",
    "FIRST_MOVER",
    "MAX_MOVES_COUNTING_BASIS",
    "Action",
    "BarrierAction",
    "MatchResult",
    "MoveAction",
    "Strategy",
    "UndefinedOutcomeError",
    "run_match",
]


class UndefinedOutcomeError(Exception):
    """Raised when max_moves is reached without any other terminal condition
    having fired. The rulebook does not define a score for this case, so the
    engine refuses to invent one — see PRD-01 "Open questions". Callers
    (e.g. the selftest CLI) should present this as an open rules question,
    not treat it as a crash.
    """


@dataclass(frozen=True)
class MoveAction:
    direction: Direction


@dataclass(frozen=True)
class BarrierAction:
    target: Position


Action = MoveAction | BarrierAction
Strategy = Callable[[MatchState, Side], Action]


@dataclass(frozen=True)
class MatchResult:
    final_state: MatchState
    terminal_condition: TerminalCondition
    police_score: int
    thief_score: int
    offending_side: Side | None


def run_match(
    config: GameConfig,
    police_strategy: Strategy,
    thief_strategy: Strategy,
    first_mover: Side = FIRST_MOVER,
) -> MatchResult:
    state = MatchState.initial(config, first_mover)
    movement = config.movement

    while True:
        side = state.whose_turn

        # Entrapment is a state check evaluated at the start of the thief's
        # turn, before it acts — STAY is deliberately not an escape here
        # (see rules.is_thief_trapped). Checked before the max_moves ceiling
        # below so that a well-defined capture always takes priority over an
        # undefined-outcome error when both would apply to the same turn.
        if side is Side.THIEF and is_thief_trapped(state.board, state.thief_pos, movement):
            return _terminal(state, TerminalCondition.CAPTURE_ENTRAPMENT, config)

        # Per-player max_moves ceiling: checked at the START of `side`'s turn,
        # against actions `side` has already taken, not after each action.
        # This is what lets the ceiling and survival_threshold coincide
        # exactly at the contract's default values instead of the ceiling
        # firing one half-round early — see MAX_MOVES_COUNTING_BASIS above.
        if actions_taken_by(state, side) >= movement.max_moves:
            raise UndefinedOutcomeError(
                f"max_moves ceiling ({movement.max_moves}, counting basis: {MAX_MOVES_COUNTING_BASIS}) "
                f"reached by {side.value} ({actions_taken_by(state, side)} of its own actions taken) "
                "without any other terminal condition firing. The rulebook does not define an outcome "
                "for this case — see PRD-01 'Open questions'. This is not an engine bug; it is an "
                "intentionally unresolved rule."
            )

        strategy = police_strategy if side is Side.POLICE else thief_strategy
        action = strategy(state, side)

        try:
            if isinstance(action, MoveAction):
                state = apply_move(state, action.direction)
            elif isinstance(action, BarrierAction):
                state = apply_barrier(state, action.target)
            else:
                raise IllegalActionError(side, f"strategy returned an unknown action type: {action!r}")
        except IllegalActionError as exc:
            police_score, thief_score = score_for(
                TerminalCondition.TECHNICAL_LOSS, config.scoring, offending_side=exc.offending_side
            )
            return MatchResult(state, TerminalCondition.TECHNICAL_LOSS, police_score, thief_score, exc.offending_side)

        last_entry = state.move_log[-1]

        if last_entry.capture_triggered:
            condition = (
                TerminalCondition.CAPTURE_BARRIER
                if last_entry.action_type is ActionType.BARRIER
                else TerminalCondition.CAPTURE_LANDING
            )
            return _terminal(state, condition, config)

        if side is Side.THIEF and state.thief_survived_steps >= movement.survival_threshold:
            return _terminal(state, TerminalCondition.SURVIVAL, config)

        state = next_turn(state, first_mover)


def _terminal(state: MatchState, condition: TerminalCondition, config: GameConfig) -> MatchResult:
    police_score, thief_score = score_for(condition, config.scoring)
    return MatchResult(state, condition, police_score, thief_score, None)
