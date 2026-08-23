"""The outbound half of the peer: pushes to the opponent's MCP tools.

Symmetric push (docs/WIRE.md §4): each side CALLS the other's tool with its own
message and POLLS its own inbox for the other's. Nothing here returns game
data — every tool acks — so these functions return `None`. The reply you are
waiting for arrives in your own inbox, not as a return value.

Every call goes through `watchdog.call_with_timeout`, so a silent opponent
surfaces as `OpponentUnresponsiveError` within `response_timeout_sec` rather
than hanging.

Every send reuses ONE pooled connection per opponent, held for the whole
series (infra/mcp_pool.py) — see that module for why per-call connections are
a compatibility defect and not just a slow one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from .mcp_pool import acquire, evict
from .watchdog import FreezeWatchdog, OpponentUnresponsiveError, call_with_timeout

logger = logging.getLogger(__name__)

# `submit_audit` takes `payload`; the other three take `message`. This looks
# like an inconsistency and it is load-bearing — a peer that sends `message` to
# submit_audit is rejected (ref_impl mcp_client.py:37-38, kit client.py:99).
_PAYLOAD_TOOLS = frozenset({"submit_audit"})

# Reconnect backoff. Deliberately NOT a flat cadence: the failure this most
# often follows is a rate-limited or overwhelmed edge, and hammering it once a
# second is what caused the outage in the first place. Capped so that a 60s
# deadline still buys ~10 attempts rather than 6.
_RETRY_FIRST_SEC = 1.0
_RETRY_MAX_SEC = 8.0

async def _call(opponent_url: str, tool: str, argument: dict[str, Any], *, response_timeout_sec: float) -> None:
    arg_name = "payload" if tool in _PAYLOAD_TOOLS else "message"

    async def _invoke() -> None:
        client = await acquire(opponent_url, response_timeout_sec=response_timeout_sec)
        try:
            await client.call_tool(tool, {arg_name: argument}, timeout=response_timeout_sec)
        except BaseException:
            # Any failure retires this connection. A pooled session can go
            # stale for reasons that are nobody fault — a tunnel idle-timing it
            # out, the far end restarting between sub-games — and a stale
            # session that is never retired would fail forever. The reconnect
            # itself is left to the retry layer below, so exactly one place
            # decides how hard to keep trying.
            await evict(opponent_url, client)
            raise

    await call_with_timeout(_invoke(), operation=tool, timeout_sec=response_timeout_sec)


async def _call_with_retry(
    opponent_url: str,
    tool: str,
    argument: dict[str, Any],
    *,
    response_timeout_sec: float,
    deadline_sec: float,
    watchdog: FreezeWatchdog | None = None,
) -> None:
    """Retry with exponential backoff until the deadline. Two peers started by
    hand are not listening at the same instant, so a refused connection early
    on is expected, not fatal (PRD-02 "Architecture decisions" #4)."""
    clock = asyncio.get_event_loop().time
    started = clock()
    delay = _RETRY_FIRST_SEC
    while True:
        try:
            await _call(opponent_url, tool, argument, response_timeout_sec=response_timeout_sec)
            return
        except OpponentUnresponsiveError:
            elapsed = watchdog.seconds_since_heartbeat() if watchdog else clock() - started
            if elapsed > deadline_sec:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RETRY_MAX_SEC)


async def send_turn(
    opponent_url: str,
    message: dict[str, Any],
    *,
    response_timeout_sec: float,
    watchdog: FreezeWatchdog,
    watchdog_timeout_sec: float,
) -> None:
    """Push one TurnMessage. Returns nothing: the opponent's reply is its own
    turn, which arrives in MY inbox (docs/WIRE.md §4)."""
    await _call_with_retry(
        opponent_url,
        "receive_turn",
        message,
        response_timeout_sec=response_timeout_sec,
        deadline_sec=watchdog_timeout_sec,
        watchdog=watchdog,
    )


async def send_negotiate(
    opponent_url: str, message: dict[str, Any], *, response_timeout_sec: float, watchdog_timeout_sec: float
) -> None:
    """Push my own signed agreement. Theirs arrives in my agreements inbox."""
    await _call_with_retry(
        opponent_url,
        "negotiate",
        message,
        response_timeout_sec=response_timeout_sec,
        deadline_sec=watchdog_timeout_sec,
    )


async def send_audit_reveal(
    opponent_url: str,
    audit_payload: dict[str, Any],
    *,
    sub_game_number: int,
    response_timeout_sec: float,
    watchdog_timeout_sec: float,
) -> None:
    """Push my full sealed chain. Best-effort, mirroring the reference
    (`mcp_client.py:99-108`): the winner's process may exit right after reading
    its own inbox, killing its server mid-response — but my payload usually
    landed anyway, and THEIRS may already be sitting in my inbox. An
    unreachable opponent here must not unwind an already-settled sub-game.

    `sub_game_number` is a tolerated EXTRA key on the envelope, never inside
    the AuditPayload: the contract shape is exactly
    {sender, records, result_claim} (docs/WIRE.md §5), but this series still
    has to route the reveal to the right sub-game.
    """
    with contextlib.suppress(OpponentUnresponsiveError):
        await _call_with_retry(
            opponent_url,
            "submit_audit",
            {**audit_payload, "sub_game_number": sub_game_number},
            response_timeout_sec=response_timeout_sec,
            deadline_sec=watchdog_timeout_sec,
        )


async def send_control(opponent_url: str, message: dict[str, Any], *, response_timeout_sec: float) -> None:
    """Best-effort control send: short timeout, errors suppressed, so a slow or
    departed opponent never stalls the game loop. Control messages are advisory
    and are never sealed or scored (`ref_impl` mcp_client.py:73-78)."""
    with contextlib.suppress(OpponentUnresponsiveError, Exception):
        await _call(opponent_url, "receive_control", message, response_timeout_sec=response_timeout_sec)
