"""A headless, synchronous, belief-aware match loop for PRD-05's evaluation
harness (scripts/evaluate_strategies.py). Mirrors `match.run_match`'s
terminal-condition logic exactly, but additionally maintains each side's
own scent trail and belief about the opponent — the same domain.scent/
domain.belief functions the real networked orchestrator calls
(infra/turn_sender.py, infra/turn_receiver.py) — so a `BrainBase` brain
behaves identically whether played live or evaluated here.

Not itself network- or crypto-aware: no commit-reveal, no MCP. This is
evaluation-only tooling, not a second production match engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .belief import BeliefMap, initial_belief, reachable_cells, update_from_scent
from .board_metrics import manhattan_distance
from .config import GameConfig
from .hints import fuse_hint_into_belief
from .house_rules import FIRST_MOVER
from .match import Action, BarrierAction, MoveAction, Strategy
from .reducers import apply_barrier, apply_move
from .rules import is_thief_trapped
from .scent import ScentField, advance_field, emit
from .state import ActionType, IllegalActionError, MatchState, Side, actions_taken_by, next_turn


@dataclass(frozen=True)
class EvalResult:
    terminal_condition: str  # a TerminalCondition value, "technical_loss", or "undefined"
    winner: str | None  # "police" | "thief" | None (tie/technical_loss/undefined)
    turns: int
    barriers_used: int
    # Manhattan distance from the POLICE's own belief argmax to the thief's
    # true cell, sampled right after each thief move (i.e. whenever police
    # has fresh information to act on) — the PRD-05 baseline metric.
    police_argmax_distances: tuple[int, ...] = field(default_factory=tuple)


def _set_belief(strategy, belief: BeliefMap) -> None:
    if hasattr(strategy, "belief"):
        strategy.belief = belief


def _last_hint(strategy) -> tuple[str, bool | None]:
    return getattr(strategy, "last_hint", ("", None))


def play_one_game(config: GameConfig, police_strategy: Strategy, thief_strategy: Strategy) -> EvalResult:
    state = MatchState.initial(config, FIRST_MOVER)
    movement = config.movement
    police_field: ScentField = {}
    thief_field: ScentField = {}
    police_belief = initial_belief(state.board)  # police's belief about the thief
    thief_belief = initial_belief(state.board)  # thief's belief about the police
    barriers_used = 0
    distances: list[int] = []

    while True:
        side = state.whose_turn

        if side is Side.THIEF and is_thief_trapped(state.board, state.thief_pos, movement):
            return _finish(state, "capture_entrapment", "police", len(state.move_log), barriers_used, distances)
        if actions_taken_by(state, side) >= movement.max_moves:
            return _finish(state, "undefined", None, len(state.move_log), barriers_used, distances)

        strategy = police_strategy if side is Side.POLICE else thief_strategy
        _set_belief(strategy, police_belief if side is Side.POLICE else thief_belief)
        action: Action = strategy(state, side)
        hint_text, _hint_is_true = _last_hint(strategy)

        try:
            new_state = apply_move(state, action.direction) if isinstance(action, MoveAction) else apply_barrier(state, action.target)
        except IllegalActionError as exc:
            winner = "thief" if exc.offending_side is Side.POLICE else "police"
            return _finish(state, "technical_loss", winner, len(state.move_log), barriers_used, distances)

        own_pos = new_state.cop_pos if side is Side.POLICE else new_state.thief_pos
        deposit = emit(own_pos, new_state.board, config.pheromones)
        if side is Side.POLICE:
            police_field = advance_field(police_field, deposit, config.pheromones)
            thief_belief = update_from_scent(thief_belief, police_field, new_state.board)
            if hint_text:
                thief_belief = fuse_hint_into_belief(thief_belief, new_state.board, hint_text)
            if isinstance(action, BarrierAction):
                barriers_used += 1
        else:
            thief_field = advance_field(thief_field, deposit, config.pheromones)
            police_belief = update_from_scent(police_belief, thief_field, new_state.board)
            if hint_text:
                police_belief = fuse_hint_into_belief(police_belief, new_state.board, hint_text)
            argmax_cell = max(reachable_cells(new_state.board), key=lambda p: police_belief[p])
            distances.append(manhattan_distance(argmax_cell, new_state.thief_pos))

        entry = new_state.move_log[-1]
        state = new_state

        if entry.capture_triggered:
            condition = "capture_barrier" if entry.action_type is ActionType.BARRIER else "capture_landing"
            return _finish(state, condition, "police", len(state.move_log), barriers_used, distances)
        if side is Side.THIEF and state.thief_survived_steps >= movement.survival_threshold:
            return _finish(state, "survival", "thief", len(state.move_log), barriers_used, distances)

        state = next_turn(state, FIRST_MOVER)


def _finish(state, condition, winner, turns, barriers_used, distances) -> EvalResult:
    return EvalResult(condition, winner, turns, barriers_used, tuple(distances))
