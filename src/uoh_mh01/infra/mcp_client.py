"""The outbound half of the peer: calls the opponent's exposed MCP tool.

Every network operation here goes through watchdog.call_with_timeout, so a
silent/dead opponent surfaces as OpponentUnresponsiveError within
response_timeout_sec — never a hang.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Client

from .audit import AuditResult
from .negotiation import NegotiateMessage
from .protocol import MoveRequest
from .protocol_response import MoveResponse
from .watchdog import FreezeWatchdog, OpponentUnresponsiveError, call_with_timeout


async def send_move(opponent_url: str, request: MoveRequest, *, response_timeout_sec: float) -> MoveResponse:
    """Deliver `request` to the opponent's receive_turn tool and return their
    response. Raises OpponentUnresponsiveError if the opponent doesn't
    respond within response_timeout_sec, for any reason."""

    async def _call() -> MoveResponse:
        async with Client(opponent_url, timeout=response_timeout_sec) as client:
            result = await client.call_tool(
                "receive_turn",
                {"message": request.to_kwargs()},
                timeout=response_timeout_sec,
            )
            return MoveResponse.from_dict(result.data)

    return await call_with_timeout(_call(), operation="receive_turn", timeout_sec=response_timeout_sec)


async def send_with_retry(
    opponent_url: str,
    request: MoveRequest,
    *,
    response_timeout_sec: float,
    watchdog: FreezeWatchdog,
    watchdog_timeout_sec: float,
) -> MoveResponse:
    """Send `request`, retrying at a steady ~1s cadence on connection failure
    (see PRD-02 "Architecture decisions" #4 — connecting to an opponent whose
    server hasn't started listening yet fails FAST, not after
    response_timeout_sec) until watchdog_timeout_sec has elapsed since the
    watchdog's last heartbeat. Raises OpponentUnresponsiveError once that
    ceiling is reached — the caller decides what that means for the match."""
    while True:
        try:
            return await send_move(opponent_url, request, response_timeout_sec=response_timeout_sec)
        except OpponentUnresponsiveError:
            if watchdog.seconds_since_heartbeat() > watchdog_timeout_sec:
                raise
            await asyncio.sleep(1.0)


async def send_negotiate(
    opponent_url: str, message: NegotiateMessage, *, response_timeout_sec: float, watchdog_timeout_sec: float
) -> NegotiateMessage:
    """Deliver my own signed negotiate message and return the opponent's.
    Retried at a steady ~1s cadence (mirroring send_with_retry) since the
    two peers' processes may not both be listening yet at series start."""

    async def _call() -> NegotiateMessage:
        async with Client(opponent_url, timeout=response_timeout_sec) as client:
            result = await client.call_tool("negotiate", {"message": message.to_kwargs()}, timeout=response_timeout_sec)
            return NegotiateMessage.from_dict(result.data)

    deadline_clock = asyncio.get_event_loop().time
    started = deadline_clock()
    while True:
        try:
            return await call_with_timeout(_call(), operation="negotiate", timeout_sec=response_timeout_sec)
        except OpponentUnresponsiveError:
            if deadline_clock() - started > watchdog_timeout_sec:
                raise
            await asyncio.sleep(1.0)


async def send_audit_reveal(
    opponent_url: str,
    records: list[dict[str, Any]],
    *,
    sub_game_number: int,
    response_timeout_sec: float,
    watchdog_timeout_sec: float,
) -> AuditResult:
    """Reveal my own sealed records' nonces to the opponent and return their
    verdict on them. Retried at a steady ~1s cadence (mirroring
    send_with_retry/send_negotiate) — a sub-game's audit begins right after
    both sides' own match loops end, and the two sides are not guaranteed to
    reach this point at exactly the same wall-clock moment. `sub_game_number`
    lets the responder detect and reject (triggering a retry, not a
    misattributed result) a reveal meant for a sub-game it hasn't reached
    yet or has already moved past."""

    async def _call() -> AuditResult:
        async with Client(opponent_url, timeout=response_timeout_sec) as client:
            result = await client.call_tool(
                "submit_audit",
                {"payload": {"records": records, "sub_game_number": sub_game_number}},
                timeout=response_timeout_sec,
            )
            data = result.data
            return AuditResult(passed=data["passed"], verified_steps=data["verified_steps"], failed_steps=tuple(data["failed_steps"]))

    deadline_clock = asyncio.get_event_loop().time
    started = deadline_clock()
    while True:
        try:
            return await call_with_timeout(_call(), operation="submit_audit", timeout_sec=response_timeout_sec)
        except OpponentUnresponsiveError:
            if deadline_clock() - started > watchdog_timeout_sec:
                raise
            await asyncio.sleep(1.0)
