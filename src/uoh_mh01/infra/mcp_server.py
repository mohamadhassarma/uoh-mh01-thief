"""The inbound half of the peer: a FastMCP server exposing the single
`submit_move` tool the opponent calls on their turn.

The tool handler itself contains no game logic — it parses the wire request
and delegates straight to the runtime's `receive_opponent_move`, per rule #3
(the Orchestrator/runtime coordinates; transport stays dumb).
"""

from __future__ import annotations

from typing import Any, Protocol

from fastmcp import FastMCP

from .protocol import MoveRequest, parse_move_request
from .protocol_response import MoveResponse


class MoveReceiver(Protocol):
    async def receive_opponent_move(self, request: MoveRequest) -> MoveResponse: ...


def build_server(runtime: MoveReceiver, *, name: str = "uoh-mh01-peer") -> FastMCP:
    mcp = FastMCP(name)

    @mcp.tool
    async def submit_move(
        role: str,
        turn_number: int,
        action_type: str,
        direction: str | None = None,
        target_row: int | None = None,
        target_col: int | None = None,
        police_actions_taken: int = 0,
        thief_actions_taken: int = 0,
        claimed_condition: str | None = None,
        claimed_offending_side: str | None = None,
    ) -> dict[str, Any]:
        request = parse_move_request(
            role,
            turn_number,
            action_type,
            direction,
            target_row,
            target_col,
            police_actions_taken,
            thief_actions_taken,
            claimed_condition,
            claimed_offending_side,
        )
        response = await runtime.receive_opponent_move(request)
        return response.to_dict()

    return mcp
