"""Match state and its reducers.

MatchState is immutable: every action produces a *new* state rather than
mutating the old one, and every action is appended to an immutable move_log.
That is what makes deterministic replay-from-log possible later (stage 6):
replay is just folding these same reducers over a saved log from the initial
state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from .board import Board, Direction, Position
from .config import GameConfig, MovementConfig
from .rules import (
    destination_of,
    is_barrier_placement_legal,
    is_capture_state,
    is_move_legal,
)


class Side(str, Enum):
    POLICE = "police"
    THIEF = "thief"


def other_side(side: Side) -> Side:
    return Side.THIEF if side is Side.POLICE else Side.POLICE


def actions_taken_by(state: "MatchState", side: Side) -> int:
    """How many of its own actions `side` has taken so far — the basis for
    the per-player max_moves ceiling. See match.py's MAX_MOVES_COUNTING_BASIS.
    """
    return state.police_actions_taken if side is Side.POLICE else state.thief_actions_taken


class IllegalActionError(Exception):
    """Raised when a side attempts an illegal move or barrier placement.

    match.py catches this and converts it into a TECHNICAL_LOSS terminal
    condition — this is expected game flow (rule: "An agent attempting an
    illegal move loses by technical loss"), not a bug in the engine.
    """

    def __init__(self, offending_side: Side, message: str):
        super().__init__(message)
        self.offending_side = offending_side


class ActionType(str, Enum):
    MOVE = "move"
    BARRIER = "barrier"


@dataclass(frozen=True)
class LogEntry:
    turn_number: int
    actor: Side
    action_type: ActionType
    detail: str  # direction name for MOVE, "(row,col)" for BARRIER
    resulting_cop_pos: Position
    resulting_thief_pos: Position
    capture_triggered: bool = False
    capture_claimed_by_police: bool = False


@dataclass(frozen=True)
class MatchState:
    config: GameConfig
    board: Board
    cop_pos: Position
    thief_pos: Position
    turn_number: int
    whose_turn: Side
    barriers_placed: int
    thief_survived_steps: int
    police_actions_taken: int
    thief_actions_taken: int
    move_log: tuple[LogEntry, ...]

    @staticmethod
    def initial(config: GameConfig, first_mover: Side) -> "MatchState":
        board = Board(grid_size=config.board.grid_size)
        return MatchState(
            config=config,
            board=board,
            cop_pos=Position(*config.board.cop_start),
            thief_pos=Position(*config.board.thief_start),
            turn_number=1,
            whose_turn=first_mover,
            barriers_placed=0,
            thief_survived_steps=0,
            police_actions_taken=0,
            thief_actions_taken=0,
            move_log=(),
        )


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

    captured = is_capture_state(new_cop_pos, new_thief_pos)
    # Only the police's own landing counts as a declared claim (the
    # rulebook's Capture Claim mechanism is police-only). If the thief walks
    # onto the police, the overlap is still detected and still a capture, but
    # there is no claim to log — see rules.is_capture_state's docstring.
    claimed = captured and actor is Side.POLICE

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


def next_turn(state: MatchState, first_mover: Side) -> MatchState:
    """Hand the turn to the other side. The round counter advances when play
    returns to `first_mover` (one round == one action from each side)."""
    next_side = other_side(state.whose_turn)
    new_turn_number = state.turn_number + 1 if next_side is first_mover else state.turn_number
    return replace(state, whose_turn=next_side, turn_number=new_turn_number)
