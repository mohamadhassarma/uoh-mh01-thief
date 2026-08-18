"""The two state reducers: `apply_move`, `apply_barrier`.

Split out of state.py purely to keep that file under the project's
~150-line budget. Both take a `MatchState` and return a *new* one plus one
appended `LogEntry` — nothing is mutated in place (see state.py's own
docstring for why that matters for replay).
"""

from __future__ import annotations

from dataclasses import replace

from .board import Direction, Position
from .config import MovementConfig
from .rules import destination_of, is_barrier_placement_legal, is_capture_state, is_move_legal
from .state import ActionType, IllegalActionError, LogEntry, MatchState, Side


def apply_move(state: MatchState, direction: Direction) -> MatchState:
    """Apply a move for whichever side has the turn. Raises IllegalActionError
    if the move is not legal — callers (match.py) turn that into TECHNICAL_LOSS.
    """
    actor = state.whose_turn
    movement: MovementConfig = state.config.movement
    pos = state.cop_pos if actor is Side.POLICE else state.thief_pos

    if not is_move_legal(state.board, pos, direction, movement):
        raise IllegalActionError(actor, f"{actor.value} attempted illegal move {direction.value} from {pos}")

    dest = destination_of(pos, direction)
    new_cop_pos = dest if actor is Side.POLICE else state.cop_pos
    new_thief_pos = dest if actor is Side.THIEF else state.thief_pos

    # PRD-03 (verified against the book's Table 2 + rules #21/#22): capture
    # by landing is police-turn-gated, never a passive/symmetric board-state
    # predicate. It fires only as a consequence of the POLICE's own action
    # (a fresh landing, or STAYing while already co-located) resulting in
    # coordinate overlap — never from the thief's own move. A thief walking
    # onto the police's cell is an ordinary move: both agents end up
    # co-located, which is a legal, persistent state (nothing here crashes
    # or loses information over it), and the police may claim it on ITS OWN
    # next turn by staying, or let the thief walk away by moving elsewhere.
    # See rules.is_capture_state's docstring for the underlying pure
    # coordinate predicate this gates.
    captured = actor is Side.POLICE and is_capture_state(new_cop_pos, new_thief_pos)
    claimed = captured  # capture-by-landing is now ALWAYS a police claim by construction

    entry = LogEntry(
        turn_number=state.turn_number,
        actor=actor,
        action_type=ActionType.MOVE,
        detail=direction.value,
        resulting_cop_pos=new_cop_pos,
        resulting_thief_pos=new_thief_pos,
        capture_triggered=captured,
        capture_claimed_by_police=claimed,
    )

    return replace(
        state,
        cop_pos=new_cop_pos,
        thief_pos=new_thief_pos,
        thief_survived_steps=state.thief_survived_steps + (1 if actor is Side.THIEF and not captured else 0),
        police_actions_taken=state.police_actions_taken + (1 if actor is Side.POLICE else 0),
        thief_actions_taken=state.thief_actions_taken + (1 if actor is Side.THIEF else 0),
        move_log=state.move_log + (entry,),
    )


def apply_barrier(state: MatchState, target: Position) -> MatchState:
    """Apply a police barrier placement. Raises IllegalActionError if illegal."""
    actor = state.whose_turn
    if actor is not Side.POLICE:
        raise IllegalActionError(actor, "only the police may place barriers")

    movement: MovementConfig = state.config.movement
    if not is_barrier_placement_legal(state.board, state.cop_pos, target, state.barriers_placed, movement):
        raise IllegalActionError(actor, f"police attempted illegal barrier placement at {target}")

    new_board = state.board.with_barrier(target)
    captured = target == state.thief_pos  # capture-by-barrier

    entry = LogEntry(
        turn_number=state.turn_number,
        actor=actor,
        action_type=ActionType.BARRIER,
        detail=f"({target.row},{target.col})",
        resulting_cop_pos=state.cop_pos,
        resulting_thief_pos=state.thief_pos,
        capture_triggered=captured,
        capture_claimed_by_police=captured,
    )

    return replace(
        state,
        board=new_board,
        barriers_placed=state.barriers_placed + 1,
        police_actions_taken=state.police_actions_taken + 1,  # only police can place barriers
        move_log=state.move_log + (entry,),
    )
