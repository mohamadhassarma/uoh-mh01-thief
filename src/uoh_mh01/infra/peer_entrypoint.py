"""`run_peer`: start this peer's MCP server and drive its match loop.

Split out of orchestrator.py to keep files under the project's ~150-line
budget. Still the sole process-level entry point (rule #3) — PeerRuntime
itself remains the only place holding live match state; this function only
wires it to the transport and the log file.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..domain.match import Strategy
from ..domain.state import Side
from ..shared.peer_config import PeerConfig
from .outcomes import MatchOutcome

logger = logging.getLogger(__name__)


async def run_peer(
    role: Side,
    config,
    peer_config: PeerConfig,
    *,
    strategy: Strategy | None = None,
    log_path: str | None = None,
) -> MatchOutcome:
    """Start this peer's MCP server and drive its match loop to a terminal
    state. Raises UndefinedOutcomeError on the rulebook's unscoreable
    max_moves case, or DisputedOutcomeError if the opponent's own claim
    disagreed with this side's independent recomputation (PRD-02 'Stage 2
    corrections' B1). Writes logs/<role>_match.json in every case."""
    from ..orchestrator import PeerRuntime
    from .mcp_server import build_server

    runtime = PeerRuntime(role, config, peer_config, strategy=strategy)
    server = build_server(runtime, name=f"uoh-mh01-{role.value}")

    server_task = asyncio.create_task(
        server.run_http_async(
            transport="http",
            host="127.0.0.1",
            port=peer_config.my_port,
            show_banner=False,
            log_level="warning",
        )
    )

    try:
        outcome = await runtime.run_match()
    finally:
        # Bounded drain instead of a blind fixed sleep (PRD-02 'Stage 2
        # corrections' B3): wait for any in-flight receive_opponent_move
        # call to finish returning its value, up to a small cap, then a
        # brief fixed pause for the HTTP transport to actually flush that
        # response — this can't be observed directly, so the pause is still
        # a heuristic, just no longer an UNCONDITIONAL one paid on every
        # shutdown regardless of whether anything was in flight.
        deadline = time.monotonic() + 2.0
        while runtime._in_flight > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            # Expected: we just asked for cancellation ourselves. Anything
            # else the server raised while tearing down is not actionable at
            # shutdown — log it at debug level rather than silently
            # swallowing it outright.
            logger.debug("server task raised during shutdown", exc_info=True)
        runtime.log.write(log_path or f"logs/{role.value}_match.json")

    return outcome
