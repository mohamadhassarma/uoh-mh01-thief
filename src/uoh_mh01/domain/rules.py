"""Pure legality and detection predicates: moves, barrier placement,
capture, entrapment. No mutation, no I/O, no turn/score bookkeeping —
that lives in state.py / scoring.py / match.py.
"""

from __future__ import annotations

from .board import ORTHOGONAL_DIRECTIONS, Board, Direction, Position, delta_for
from .config import MovementConfig


def destination_of(pos: Position, direction: Direction) -> Position:
    return pos + delta_for(direction)


def is_move_legal(board: Board, pos: Position, direction: Direction, movement: MovementConfig) -> bool:
    """Is `direction` a legal move for an agent standing at `pos`?

    STAY is always legal — an agent is always allowed to stand still, even on
    a cell that happens to be a barrier (the police may barrier its own cell).
    Any other direction must be in the contract's move_set, land in bounds,
    and not land on a barrier.
    """
    if direction.value not in movement.move_set:
        return False
    if direction is Direction.STAY:
        return True
    dest = destination_of(pos, direction)
    return board.in_bounds(dest) and not board.is_barrier(dest)


def legal_moves(board: Board, pos: Position, movement: MovementConfig) -> tuple[Direction, ...]:
    return tuple(d for d in Direction if is_move_legal(board, pos, d, movement))


def is_barrier_placement_legal(
    board: Board,
    cop_pos: Position,
    target: Position,
    barriers_placed: int,
    movement: MovementConfig,
) -> bool:
    """May the police place a barrier at `target` right now?

    Legal targets are the police's own cell and its four orthogonal
    neighbours — never diagonal, never at range. The quota and
    already-barriered checks are independent of position.
    """
    if barriers_placed >= movement.max_barriers:
        return False
    if board.is_barrier(target):
        return False
    if not board.in_bounds(target):
        return False
    allowed_targets = (cop_pos, *board.orthogonal_neighbors(cop_pos))
    return target in allowed_targets


def is_capture_state(cop_pos: Position, thief_pos: Position) -> bool:
    """Pure coordinate-overlap check — does NOT decide who a capture is
    attributed to or whether it counts as claimed.

    PRD-03 (superseding PRD-01's original symmetric reading, verified
    against the book's Table 2 and rules #21/#22): capture-by-landing is
    police-turn-gated at the call site (state.apply_move) — this predicate
    is only consulted when `actor is Side.POLICE`. A thief walking onto the
    police's cell computes `True` here too (the coordinates DO overlap) but
    the caller does not treat it as a capture; the two agents simply end up
    co-located, a legal and persistent board state.
    """
    return cop_pos == thief_pos


def is_thief_trapped(board: Board, thief_pos: Position, movement: MovementConfig) -> bool:
    """Entrapment: all four orthogonal neighbours are off-board or barriers.

    STAY is deliberately excluded from this check. STAY is always a legal
    *move*, but the rulebook defines entrapment structurally ("all
    orthogonally adjacent cells are barriers and/or board edges") — if STAY
    counted as an escape, entrapment could never trigger at all.
    """
    for direction in ORTHOGONAL_DIRECTIONS:
        if direction.value not in movement.move_set:
            continue
        dest = destination_of(thief_pos, direction)
        if board.in_bounds(dest) and not board.is_barrier(dest):
            return False
    return True
