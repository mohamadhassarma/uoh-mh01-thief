"""Builder/parser functions for `MoveRequest` (infra/protocol.py), split out
purely to keep protocol.py under the project's ~150-line budget.
"""

from __future__ import annotations

from ..domain.board import Direction, Position
from ..domain.match import Action, BarrierAction, MoveAction
from ..domain.state import Side
from .protocol import _ACTION_TYPES, MoveRequest, ProtocolError


def parse_move_request(
    role: str,
    turn_number: int,
    action_type: str,
    direction: str | None,
    target_row: int | None,
    target_col: int | None,
    police_actions_taken: int = 0,
    thief_actions_taken: int = 0,
    claimed_condition: str | None = None,
    claimed_offending_side: str | None = None,
    commit: str = "",
    sub_game_number: int = 1,
    smell_grid: dict[str, float] | None = None,
    hint: str = "",
    hint_is_true: bool | None = None,
) -> MoveRequest:
    if role not in ("police", "thief"):
        raise ProtocolError(f"role must be 'police' or 'thief', got {role!r}")
    if action_type not in _ACTION_TYPES:
        raise ProtocolError(f"action_type must be one of {sorted(_ACTION_TYPES)}, got {action_type!r}")
    if action_type == "move":
        if direction is None:
            raise ProtocolError("action_type='move' requires 'direction'")
    elif action_type == "barrier":
        if target_row is None or target_col is None:
            raise ProtocolError("action_type='barrier' requires 'target_row' and 'target_col'")
    else:  # declare_terminal
        if claimed_condition is None:
            raise ProtocolError("action_type='declare_terminal' requires 'claimed_condition'")
    return MoveRequest(
        role=role,
        turn_number=turn_number,
        action_type=action_type,
        direction=direction,
        target_row=target_row,
        target_col=target_col,
        police_actions_taken=police_actions_taken,
        thief_actions_taken=thief_actions_taken,
        claimed_condition=claimed_condition,
        claimed_offending_side=claimed_offending_side,
        commit=commit,
        sub_game_number=sub_game_number,
        smell_grid=smell_grid,
        hint=hint,
        hint_is_true=hint_is_true,
    )


def action_to_request(
    action: Action,
    role: Side,
    turn_number: int,
    *,
    police_actions_taken: int,
    thief_actions_taken: int,
    claimed_condition: str | None = None,
    commit: str = "",
    sub_game_number: int = 1,
    smell_grid: dict[str, float] | None = None,
    hint: str = "",
    hint_is_true: bool | None = None,
) -> MoveRequest:
    if isinstance(action, MoveAction):
        base = {
            "role": role.value,
            "turn_number": turn_number,
            "action_type": "move",
            "direction": action.direction.value,
        }
    elif isinstance(action, BarrierAction):
        base = {
            "role": role.value,
            "turn_number": turn_number,
            "action_type": "barrier",
            "target_row": action.target.row,
            "target_col": action.target.col,
        }
    else:
        raise ProtocolError(f"unknown action type: {action!r}")
    return MoveRequest(
        **base,
        police_actions_taken=police_actions_taken,
        thief_actions_taken=thief_actions_taken,
        claimed_condition=claimed_condition,
        commit=commit,
        sub_game_number=sub_game_number,
        smell_grid=smell_grid,
        hint=hint,
        hint_is_true=hint_is_true,
    )


def declare_terminal_request(
    role: Side,
    turn_number: int,
    claimed_condition: str,
    *,
    police_actions_taken: int,
    thief_actions_taken: int,
    commit: str = "",
    sub_game_number: int = 1,
) -> MoveRequest:
    """Build a no-move 'I detected a terminal condition' message — see
    protocol.py's module docstring for why this reuses MoveRequest's shape
    and why it is named `declare_terminal`, not `concede`."""
    return MoveRequest(
        role=role.value,
        turn_number=turn_number,
        action_type="declare_terminal",
        police_actions_taken=police_actions_taken,
        thief_actions_taken=thief_actions_taken,
        claimed_condition=claimed_condition,
        commit=commit,
        sub_game_number=sub_game_number,
    )


def request_to_action(request: MoveRequest) -> Action:
    if request.action_type == "move":
        return MoveAction(Direction(request.direction))
    return BarrierAction(Position(request.target_row, request.target_col))
