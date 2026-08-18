"""The wire contract between the two peers' MCP tools.

Pure geometric data plus terminal-condition claims — no strategy, no
cryptography, no natural language, per PRD-02's scope. Both mcp_server.py
and mcp_client.py import these shapes so a client-side call and the
server-side handler can never silently drift apart from each other.

`action_type == "declare_terminal"` is a move-shaped message that carries NO
move: it is how a side declares a terminal condition it detected WITHOUT
taking an action (entrapment, the max_moves ceiling — see
domain.terminal_detect). It deliberately reuses the same tool and the same
request/response shape as an ordinary move rather than inventing a second
tool, mirroring how the official reference's thief reuses its capture-claim
vocabulary for a rule-46/47 ending instead of a new message type.

Named `declare_terminal`, not `concede`: entrapment and the max_moves
ceiling are not concessions — entrapment in particular is a CAPTURE
(`capture_cop`/`capture_thief` scoring applies, the thief is caught, not
surrendering), and a string that misdescribes the outcome would appear
verbatim in the audit log and the result artifact, where both a grader and
an opponent's own verifier read it. Neither the reference implementation
nor the interop kit's SPEC name a generic "concede"/"declare" action type of
their own (both instead reuse existing field-level vocabulary —
`claim_response`/`win_claim` — rather than an action_type string), so this
name is this project's own neutral choice, not adopted from either source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.board import Direction, Position
from ..domain.match import Action, BarrierAction, MoveAction
from ..domain.state import Side

TOOL_NAME = "submit_move"

_ACTION_TYPES = frozenset({"move", "barrier", "declare_terminal"})


class ProtocolError(Exception):
    """A malformed request/response payload — a wire-schema problem, not a
    game-rule illegality (domain.rules is what decides legality)."""


@dataclass(frozen=True)
class MoveRequest:
    role: str  # the MOVER's role: "police" | "thief"
    turn_number: int
    action_type: str  # "move" | "barrier" | "declare_terminal"
    direction: str | None = None  # required if action_type == "move"
    target_row: int | None = None  # required if action_type == "barrier"
    target_col: int | None = None  # required if action_type == "barrier"
    # The sender's own local police_actions_taken/thief_actions_taken AFTER
    # this action (unchanged, for "declare_terminal"). The receiver
    # recomputes its own counters independently and rejects on any
    # mismatch — see infra.turn_receiver and PRD-02 "Stage 2 corrections" B2.
    police_actions_taken: int = 0
    thief_actions_taken: int = 0
    # The sender's own claim about whether this message ends the match:
    # a TerminalCondition value, domain.terminal_detect.UNDEFINED_CEILING,
    # or None ("play continues, as far as I can tell"). Never trusted
    # outright — the receiver always recomputes and reports agreement.
    claimed_condition: str | None = None
    claimed_offending_side: str | None = None

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "turn_number": self.turn_number,
            "action_type": self.action_type,
            "direction": self.direction,
            "target_row": self.target_row,
            "target_col": self.target_col,
            "police_actions_taken": self.police_actions_taken,
            "thief_actions_taken": self.thief_actions_taken,
            "claimed_condition": self.claimed_condition,
            "claimed_offending_side": self.claimed_offending_side,
        }


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
    )


def action_to_request(
    action: Action,
    role: Side,
    turn_number: int,
    *,
    police_actions_taken: int,
    thief_actions_taken: int,
    claimed_condition: str | None = None,
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
    )


def declare_terminal_request(
    role: Side,
    turn_number: int,
    claimed_condition: str,
    *,
    police_actions_taken: int,
    thief_actions_taken: int,
) -> MoveRequest:
    """Build a no-move 'I detected a terminal condition' message — see the
    module docstring for why this reuses MoveRequest's shape and why it is
    named `declare_terminal`, not `concede`."""
    return MoveRequest(
        role=role.value,
        turn_number=turn_number,
        action_type="declare_terminal",
        police_actions_taken=police_actions_taken,
        thief_actions_taken=thief_actions_taken,
        claimed_condition=claimed_condition,
    )


def request_to_action(request: MoveRequest) -> Action:
    if request.action_type == "move":
        return MoveAction(Direction(request.direction))
    return BarrierAction(Position(request.target_row, request.target_col))
