"""The four thread-safe mailboxes the MCP tools fill and the runtime drains
(docs/WIRE.md §4, mirroring `ref_impl/src/police_thief/infra/mcp_server.py:37-44`).

This is what makes the tools ack-only. A handler that did work before returning
could deadlock two peers each awaiting the other inside a handler — the
highest-severity failure available in this design
(`interop_kit/sparring/transport/server.py:5-8`). Every handler now validates
nothing, computes nothing, and returns `{"ok": True}` after one `append`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Inboxes:
    """One peer's inbound mail. Ordinary deques: everything runs on a single
    event loop, and the tool handlers never await between check and append."""

    agreements: deque[dict[str, Any]] = field(default_factory=deque)
    turns: deque[dict[str, Any]] = field(default_factory=deque)
    audits: deque[dict[str, Any]] = field(default_factory=deque)
    controls: deque[dict[str, Any]] = field(default_factory=deque)

    def drain_stale(self) -> None:
        """Drop advisory control mail left over from a finished sub-game.

        TURNS AND AUDITS ARE DELIBERATELY NOT DROPPED, unlike the reference's
        blanket `drain_inboxes` (`ref_impl` mcp_client.py:87-97). The two peers
        do not reach a sub-game boundary at the same instant, so the opponent
        can legitimately send its FIRST turn of sub-game N+1 while this side is
        still finishing N's audit. Clearing the queue here would discard that
        turn, and since the contract's TurnMessage has no sub-game field there
        is nothing to re-request it with — this side would then wait out its
        whole turn budget for a message that already arrived and was thrown
        away. A leftover turn simply waits in the queue instead; audits carry
        their own `sub_game_number` on the envelope and are matched on it.

        The agreements inbox is untouched for the SAME reason, and since the
        handshake moved inside the sub-game loop (infra/series_handshake.py)
        that reason now bites: the opponent greets for sub-game N+1 as soon as
        its own N settles, which is routinely before this side has finished
        N's audit. Clearing that greeting would strand both peers — they would
        wait out their handshake budget for a message we acknowledged and
        threw away, which is precisely the failure the kit warns about
        (`sparring/netplay.py:12-14`).
        """
        self.controls.clear()


async def poll(queue: deque[dict[str, Any]], *, timeout: float, poll_interval: float) -> dict[str, Any] | None:
    """Pop the oldest message from `queue`, waiting up to `timeout` for one to
    arrive. Returns `None` on timeout — the caller decides what silence means.

    This replaces waiting on an `asyncio.Event` set from inside a tool handler.
    The event coupled "a message arrived" to "the handler already applied it";
    polling a queue keeps arrival and processing separate, which is what lets
    the handler stay dumb.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        if queue:
            return queue.popleft()
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(min(poll_interval, max(0.0, deadline - loop.time())))


def poll_now(queue: deque[dict[str, Any]]) -> dict[str, Any] | None:
    """Non-blocking pop — used for the advisory control channel, which must
    never stall the game loop (`ref_impl` mcp_client.py:80-85)."""
    return queue.popleft() if queue else None
