"""The outbound half of the peer: calls the opponent's exposed MCP tool.

Every network operation here goes through watchdog.call_with_timeout, so a
silent/dead opponent surfaces as OpponentUnresponsiveError within
response_timeout_sec — never a hang.
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

from .protocol import MoveRequest
from .protocol_response import MoveResponse
from .watchdog import FreezeWatchdog, OpponentUnresponsiveError, call_with_timeout


async def send_move(opponent_url: str, request: MoveRequest, *, response_timeout_sec: float) -> MoveResponse:
    """Deliver `request` to the opponent's submit_move tool and return their
    response. Raises OpponentUnresponsiveError if the opponent doesn't
    respond within response_timeout_sec, for any reason."""

    async def _call() -> MoveResponse:
        async with Client(opponent_url, timeout=response_timeout_sec) as client:
            result = await client.call_tool(
                "submit_move",
                request.to_kwargs(),
                timeout=response_timeout_sec,
            )
            return MoveResponse.from_dict(result.data)

    return await call_with_timeout(_call(), operation="submit_move", timeout_sec=response_timeout_sec)


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
