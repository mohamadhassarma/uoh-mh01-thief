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

from .board import Board, Position
from .config import GameConfig


class Side(str, Enum):
    POLICE = "police"
    THIEF = "thief"


def other_side(side: Side) -> Side:
    return Side.THIEF if side is Side.POLICE else Side.POLICE


def actions_taken_by(state: MatchState, side: Side) -> int:
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
    def initial(config: GameConfig, first_mover: Side) -> MatchState:
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


def next_turn(state: MatchState, first_mover: Side) -> MatchState:
    """Hand the turn to the other side. The round counter advances when play
    returns to `first_mover` (one round == one action from each side)."""
    next_side = other_side(state.whose_turn)
    new_turn_number = state.turn_number + 1 if next_side is first_mover else state.turn_number
    return replace(state, whose_turn=next_side, turn_number=new_turn_number)
