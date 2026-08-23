"""`OwnGameState`: everything ONE PEER truthfully knows about itself.

There is no shared board across the wire (docs/WIRE.md §2.1). A peer is
authoritative only for its own position, its own step count and — for the
police — its own barrier quota. Barriers the opponent declares are noted as
they arrive; the opponent's POSITION is never held here at all, because it is
never sent. The opponent exists only as a belief grid (domain/belief.py).

This is the structural replacement for `_OpponentPositionGuard`. The guard
blocked one attribute name on a state object that still *held* the opponent's
position — it could be defeated by any transitive path (`state.move_log`
carried both positions). A type that simply has no such field cannot be
defeated at all.

Contrast `domain/state.py`'s `MatchState`, which legitimately holds BOTH
positions: that is the single-process SIMULATOR (`domain/match.py`,
`domain/eval_match.py`, `selftest`, the evaluation harness), which plays both
sides and is not a peer. `own_view()` projects a `MatchState` down to one
side's `OwnGameState` so a brain sees the same restricted surface in both
paths.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .board import Board, Position
from .config import GameConfig
from .state import ActionType, IllegalActionError, MatchState, Side


@dataclass(frozen=True)
class OwnStepEntry:
    """One of MY OWN actions. Carries my resulting position only."""

    step: int
    action_type: ActionType
    detail: str
    resulting_own_pos: Position
    barrier_placed: Position | None = None


@dataclass(frozen=True)
class OwnGameState:
    config: GameConfig
    role: Side
    board: Board  # my own known barriers: mine + every one the opponent declared
    own_pos: Position
    step_number: int
    barriers_placed: int
    survived_steps: int
    step_log: tuple[OwnStepEntry, ...] = ()

    @staticmethod
    def initial(config: GameConfig, role: Side) -> OwnGameState:
        start = config.board.cop_start if role is Side.POLICE else config.board.thief_start
        return OwnGameState(
            config=config,
            board=Board(grid_size=config.board.grid_size),
            role=role,
            own_pos=Position(*start),
            step_number=0,
            barriers_placed=0,
            survived_steps=0,
        )

    @property
    def turn_number(self) -> int:
        """Alias kept for brains and log records, which think in turns. A step
        here is one of MY OWN actions — the reference numbers each peer's own
        chain independently (docs/WIRE.md §2.2)."""
        return self.step_number


def note_opponent_barrier(state: OwnGameState, cell: Position) -> OwnGameState:
    """Record a barrier the opponent declared — impassable for both, and the
    only board fact that legitimately crosses the wire."""
    return replace(state, board=state.board.with_barrier(cell))


def apply_own_move(state: OwnGameState, direction) -> OwnGameState:
    """Apply MY OWN move. Raises `IllegalActionError` against my own role, so
    an illegal self-move is still a technical loss I inflict on myself."""
    from .rules import destination_of, is_move_legal

    if not is_move_legal(state.board, state.own_pos, direction, state.config.movement):
        raise IllegalActionError(state.role, f"illegal move {direction.value} from {state.own_pos}")
    dest = destination_of(state.own_pos, direction)
    entry = OwnStepEntry(
        step=state.step_number + 1,
        action_type=ActionType.MOVE,
        detail=direction.value,
        resulting_own_pos=dest,
    )
    survived = state.survived_steps + 1 if state.role is Side.THIEF else state.survived_steps
    return replace(
        state,
        own_pos=dest,
        step_number=state.step_number + 1,
        survived_steps=survived,
        step_log=(*state.step_log, entry),
    )


def apply_own_barrier(state: OwnGameState, target: Position) -> OwnGameState:
    """Place one of MY OWN barriers (police only)."""
    from .rules import is_barrier_placement_legal

    if not is_barrier_placement_legal(
        state.board, state.own_pos, target, state.barriers_placed, state.config.movement
    ):
        raise IllegalActionError(state.role, f"illegal barrier placement at {target}")
    entry = OwnStepEntry(
        step=state.step_number + 1,
        action_type=ActionType.BARRIER,
        detail=f"({target.row},{target.col})",
        resulting_own_pos=state.own_pos,
        barrier_placed=target,
    )
    return replace(
        state,
        board=state.board.with_barrier(target),
        step_number=state.step_number + 1,
        barriers_placed=state.barriers_placed + 1,
        step_log=(*state.step_log, entry),
    )


def own_view(state: MatchState, side: Side) -> OwnGameState:
    """Project the SIMULATOR's omniscient `MatchState` down to one side's own
    view, so a brain sees exactly the same restricted surface whether it is
    driven by the simulator or by a live peer. Without this the simulator
    would hand brains an object still carrying the opponent's true position —
    the very leak `_OpponentPositionGuard` used to paper over."""
    own_pos = state.cop_pos if side is Side.POLICE else state.thief_pos
    return OwnGameState(
        config=state.config,
        board=state.board,
        role=side,
        own_pos=own_pos,
        step_number=state.turn_number,
        barriers_placed=state.barriers_placed,
        survived_steps=state.thief_survived_steps,
    )
