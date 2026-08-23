"""The inbound half of the peer: a FastMCP server exposing the reference/
interop-kit wire surface (SPEC §7.5, PROMOTED — `vectors/turn_message.json`):
`negotiate`, `receive_turn`, `submit_audit`, and the optional
`receive_control`.

Each REQUIRED tool takes a single dict argument — `message` for
`negotiate`/`receive_turn`/`receive_control`, `payload` for `submit_audit` —
mirroring the reference's documented asymmetry exactly
(`ref_impl/src/police_thief/infra/mcp_server.py:51-73`).

**EVERY HANDLER IS ACK-ONLY.** It appends to an inbox and returns
`{"ok": True}`. No parsing, no validation, no game logic, no awaiting — all of
that moved to the poll loop that drains these queues. Two peers each awaiting
the other inside a handler is an instant deadlock, which is why the reference
and the kit both keep this surface trivial.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .inboxes import Inboxes

_ACK: dict[str, Any] = {"ok": True}


def build_server(inboxes: Inboxes, *, name: str = "uoh-mh01-peer") -> FastMCP:
    mcp = FastMCP(name)

    @mcp.tool
    def negotiate(message: dict[str, Any]) -> dict[str, Any]:
        """Receive the opponent's signed game agreement."""
        inboxes.agreements.append(message)
        return _ACK

    @mcp.tool
    def receive_turn(message: dict[str, Any]) -> dict[str, Any]:
        """Receive the opponent's turn message (the turn token travels with it)."""
        inboxes.turns.append(message)
        return _ACK

    @mcp.tool
    def submit_audit(payload: dict[str, Any]) -> dict[str, Any]:
        """Receive the opponent's end-of-sub-game reveal (records + nonces)."""
        inboxes.audits.append(payload)
        return _ACK

    @mcp.tool
    def receive_control(message: dict[str, Any]) -> dict[str, Any]:
        """Receive an opponent control signal (enable / status / restart / quit)."""
        inboxes.controls.append(message)
        return _ACK

    return mcp
