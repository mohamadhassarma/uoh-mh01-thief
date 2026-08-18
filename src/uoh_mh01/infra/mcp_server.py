"""The inbound half of the peer: a FastMCP server exposing the three tools
the opponent calls: `submit_move` (every turn), `negotiate` (once, at series
start), and `reveal_audit` (once per sub-game, at its end).

Tool handlers contain no game logic — they parse the wire request and
delegate straight to the runtime, per rule #3 (the Orchestrator/runtime
coordinates; transport stays dumb).
"""

from __future__ import annotations

from typing import Any, Protocol

from fastmcp import FastMCP

from .audit import AuditResult
from .negotiation import NegotiateMessage
from .protocol import MoveRequest
from .protocol_builders import parse_move_request
from .protocol_response import MoveResponse


class PeerServerHandlers(Protocol):
    async def receive_opponent_move(self, request: MoveRequest) -> MoveResponse: ...
    async def receive_negotiate(self, message: NegotiateMessage) -> NegotiateMessage: ...
    async def receive_audit_reveal(self, records: list[dict[str, Any]], sub_game_number: int) -> AuditResult: ...


def build_server(runtime: PeerServerHandlers, *, name: str = "uoh-mh01-peer") -> FastMCP:
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
        commit: str = "",
        sub_game_number: int = 1,
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
            commit,
            sub_game_number,
        )
        response = await runtime.receive_opponent_move(request)
        return response.to_dict()

    @mcp.tool
    async def negotiate(
        terms: dict[str, Any],
        nonce: str,
        signature: str,
        identity: dict[str, Any],
        scent_model_sha256: str,
        sub_game_number: int,
        role: str,
    ) -> dict[str, Any]:
        message = NegotiateMessage.from_dict(
            {
                "terms": terms,
                "nonce": nonce,
                "signature": signature,
                "identity": identity,
                "scent_model_sha256": scent_model_sha256,
                "sub_game_number": sub_game_number,
                "role": role,
            }
        )
        response = await runtime.receive_negotiate(message)
        return response.to_kwargs()

    @mcp.tool
    async def reveal_audit(records: list[dict[str, Any]], sub_game_number: int) -> dict[str, Any]:
        result = await runtime.receive_audit_reveal(records, sub_game_number)
        return {"passed": result.passed, "verified_steps": result.verified_steps, "failed_steps": list(result.failed_steps)}

    return mcp
