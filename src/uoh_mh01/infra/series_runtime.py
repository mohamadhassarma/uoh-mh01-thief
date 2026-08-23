"""SeriesRuntime: the ONE long-lived object per process for the whole
num_games-sub-game series (PRD-03). Owns the FastMCP server — built once,
listening for the whole series — and the four inboxes its ack-only tools fill.

It no longer answers anything. Under the contract every tool enqueues and
returns `{"ok": True}` (docs/WIRE.md §1), so this class is now a mailbox holder
plus the per-sub-game bookkeeping the series loop needs. The audit-routing
dance it used to do — waking a waiter for a reveal that arrived before this
side reached that sub-game — is gone: a reveal that arrives early simply waits
in the audits inbox until the sub-game that wants it polls for it.
"""

from __future__ import annotations

from typing import Any

from .inboxes import Inboxes, poll


class SeriesRuntime:
    def __init__(self) -> None:
        self.inboxes = Inboxes()
        self.current_peer_runtime: Any = None
        self.current_sub_game_number: int | None = None

    def start_sub_game(self, sub_game_number: int, peer_runtime: Any) -> None:
        """Called once per sub-game, before running its match. Hands the shared
        inboxes to the runtime that will drain them, and clears mail left over
        from the sub-game that just ended."""
        self.current_peer_runtime = peer_runtime
        self.current_sub_game_number = sub_game_number
        self.inboxes.drain_stale()
        peer_runtime.inboxes = self.inboxes

    async def wait_for_agreement(self, *, timeout: float, poll_interval: float = 0.25) -> dict[str, Any] | None:
        """The opponent's signed agreement, from my own agreements inbox."""
        return await poll(self.inboxes.agreements, timeout=timeout, poll_interval=poll_interval)

    async def wait_for_audit_reveal(
        self, *, sub_game_number: int, timeout: float, poll_interval: float = 0.25
    ) -> dict[str, Any] | None:
        """The opponent's full-chain reveal for THIS sub-game.

        `sub_game_number` rides as a tolerated extra key on the envelope
        (docs/WIRE.md §5). A reveal for a DIFFERENT sub-game is set aside and
        restored rather than consumed: the two peers' loops are not wall-clock
        synchronized, so a reveal for the next sub-game can legitimately land
        while this one is still settling.
        """
        deferred: list[dict[str, Any]] = []
        try:
            while True:
                payload = await poll(self.inboxes.audits, timeout=timeout, poll_interval=poll_interval)
                if payload is None:
                    return None
                if payload.get("sub_game_number", sub_game_number) == sub_game_number:
                    return payload
                deferred.append(payload)
        finally:
            self.inboxes.audits.extendleft(reversed(deferred))
