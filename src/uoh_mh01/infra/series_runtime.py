"""SeriesRuntime: the ONE long-lived object per process for the whole
num_games-sub-game series (PRD-03). Owns the FastMCP server — built once,
listening for the whole series, unlike stage 2's per-match server — and
answers `negotiate`/`submit_audit` directly; `receive_turn` traffic is
delegated to whichever PeerRuntime is currently playing a sub-game.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from .audit import AuditResult, verify_revealed
from .negotiation import NegotiateMessage
from .protocol import MoveRequest
from .protocol_response import MoveResponse


class StaleAuditRevealError(Exception):
    """Raised when an incoming submit_audit call names a sub_game_number
    this side has not started even after a bounded wait — the two sides'
    loops are not perfectly wall-clock synchronized between sub-games, so
    this is treated as a retry case by the caller (mcp_client's
    send_audit_reveal), not a hard failure."""


class SeriesRuntime:
    def __init__(self) -> None:
        self.current_peer_runtime: Any = None  # a PeerRuntime, set fresh per sub-game by series.py
        self.current_sub_game_number: int | None = None
        self._my_negotiate_message: NegotiateMessage | None = None
        # Keyed by sub_game_number, never reset by a later sub-game starting —
        # a submit_audit call for sub-game N can legitimately arrive well after
        # this side has already moved on to sub-game N+1 (its opponent was
        # simply slower to finish N), and must still land against N's own
        # commit log and wake N's own waiter, not get silently discarded or
        # misattributed to whichever sub-game happens to be "current" now.
        self._peer_runtimes_by_sub_game: dict[int, Any] = {}
        self._audit_results: dict[int, AuditResult] = {}
        self._audit_events: dict[int, asyncio.Event] = defaultdict(asyncio.Event)

    def set_negotiate_message(self, message: NegotiateMessage) -> None:
        self._my_negotiate_message = message

    def start_sub_game(self, sub_game_number: int, peer_runtime: Any) -> None:
        """Call once per sub-game, before running its match — tags which
        sub-game is now current (for routing receive_turn traffic) and
        registers it so a submit_audit call for THIS sub-game can be served
        (immediately, or after a bounded wait if it arrives first)."""
        self.current_peer_runtime = peer_runtime
        self.current_sub_game_number = sub_game_number
        self._peer_runtimes_by_sub_game[sub_game_number] = peer_runtime

    async def wait_for_audit_of_opponent(self, sub_game_number: int, timeout: float) -> AuditResult | None:
        event = self._audit_events[sub_game_number]
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            return None
        return self._audit_results.get(sub_game_number)

    # ------------------------------------------------------------------
    # PeerServerHandlers protocol (infra/mcp_server.py)
    # ------------------------------------------------------------------

    async def receive_opponent_move(self, request: MoveRequest) -> MoveResponse:
        # The two sides' series loops are not perfectly wall-clock
        # synchronized between sub-games (or even at series start, right
        # after the handshake) — a message legitimately meant for the
        # sub-game I am ABOUT to start can arrive before I've called
        # start_sub_game() for it. receive_turn is not retried by the sender
        # on an application-level rejection (only on transport failure), so
        # unlike submit_audit's StaleAuditRevealError (which relies on the
        # caller's own retry loop), this side must absorb the wait itself —
        # bounded, so a message for a sub-game I will never reach still
        # fails cleanly rather than hanging.
        deadline = asyncio.get_event_loop().time() + 5.0
        while self.current_sub_game_number != request.sub_game_number and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        if self.current_peer_runtime is None or self.current_sub_game_number != request.sub_game_number:
            return MoveResponse(
                accepted=False,
                reason=f"I am on sub_game_number={self.current_sub_game_number!r}, not {request.sub_game_number!r}",
            )
        return await self.current_peer_runtime.receive_opponent_move(request)

    async def receive_negotiate(self, message: NegotiateMessage) -> NegotiateMessage:
        # Deliberately does not itself verify `message` here — negotiate is
        # a symmetric exchange; each side calls the other and runs its OWN
        # verify_peer_message(mine, theirs) after getting this response.
        assert self._my_negotiate_message is not None, "negotiate() called before set_negotiate_message()"
        return self._my_negotiate_message

    async def receive_audit_reveal(self, records: list[dict[str, Any]], sub_game_number: int) -> AuditResult:
        peer_runtime = self._peer_runtimes_by_sub_game.get(sub_game_number)
        if peer_runtime is None:
            # Arrived before I called start_sub_game() for it (a real
            # possibility right after a fast sub-game finish on the
            # opponent's side) — bounded wait, mirroring
            # receive_opponent_move's own startup-race handling, rather than
            # rejecting outright.
            deadline = asyncio.get_event_loop().time() + 5.0
            while peer_runtime is None and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.05)
                peer_runtime = self._peer_runtimes_by_sub_game.get(sub_game_number)
            if peer_runtime is None:
                raise StaleAuditRevealError(
                    f"submit_audit for sub_game_number={sub_game_number}, which I have not started "
                    "even after a bounded wait — the caller's retry loop will try again shortly"
                )
        result = verify_revealed(records, peer_runtime.received_commits)
        self._audit_results[sub_game_number] = result
        self._audit_events[sub_game_number].set()
        return result
