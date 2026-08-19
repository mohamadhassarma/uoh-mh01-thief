"""The inbound half of the peer: a FastMCP server exposing the reference/
interop-kit wire surface (SPEC §7.5, PROMOTED — `vectors/turn_message.json`):
`negotiate` (once, at series start), `receive_turn` (every turn),
`submit_audit` (once per sub-game, at its end), and the optional
`receive_control` status channel. Each REQUIRED tool takes a single dict
argument — `message` for `negotiate`/`receive_turn`/`receive_control`,
`payload` for `submit_audit` — mirroring the reference's own documented
asymmetry exactly, not a per-field parameter list of this project's own
invention (stage-5 close-out: our previous `submit_move`/`reveal_audit`
names and per-field signatures were a genuine wire-shape deviation, found
via a live rehearsal against the interop kit's sparring peer and confirmed
against `ref_impl/src/police_thief/infra/mcp_server.py`).

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
    async def receive_turn(message: dict[str, Any]) -> dict[str, Any]:
        request = parse_move_request(**message)
        response = await runtime.receive_opponent_move(request)
        return response.to_dict()

    @mcp.tool
    async def negotiate(message: dict[str, Any]) -> dict[str, Any]:
        negotiate_message = NegotiateMessage.from_dict(message)
        response = await runtime.receive_negotiate(negotiate_message)
        return response.to_kwargs()

    @mcp.tool
    async def submit_audit(payload: dict[str, Any]) -> dict[str, Any]:
        result = await runtime.receive_audit_reveal(payload["records"], payload["sub_game_number"])
        return {"passed": result.passed, "verified_steps": result.verified_steps, "failed_steps": list(result.failed_steps)}

    @mcp.tool
    async def receive_control(message: dict[str, Any]) -> dict[str, Any]:
        # OPTIONAL per SPEC §7.5: "a status channel touching no game state;
        # answering 200 is conformant" — no runtime wiring needed, matching
        # the reference/kit's own implementation of this tool exactly.
        return {"ok": True}

    return mcp
