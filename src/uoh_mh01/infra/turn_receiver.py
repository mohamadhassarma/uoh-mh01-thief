"""Handling an INCOMING opponent turn, popped from my own inbox by the poll
loop (docs/WIRE.md §4) — never inside a tool handler.

GUTTED, deliberately. There is no opponent move to apply: the contract does
not put the mover's move on the wire (§2.1), so this side cannot — and must
not — reconstruct the opponent's board. This handler does exactly four things:

  1. records the opponent's commit for the post-sub-game audit,
  2. notes any barrier they declared (public by rule, impassable for both),
  3. folds hint + smell_grid into MY belief,
  4. resolves the claim protocol (capture claim / claim response / win claim).
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.board import Position
from ..domain.own_state import note_opponent_barrier
from ..domain.scoring import TerminalCondition
from ..domain.state import Side, other_side
from ..domain.terminal_detect import answer_capture_claim
from .receiver_helpers import absorb_opponent_signals
from .turn_message import ProtocolError, TurnMessage
from .turn_message_builders import parse_turn_message

logger = logging.getLogger(__name__)


class _TurnReceiverMixin:
    async def receive_opponent_turn(self, raw: dict[str, Any]) -> None:
        """Process one inbound turn. Validation happens BEFORE any state
        change: an inbound turn is adversarial input and a partially applied
        bad turn cannot be rolled back (docs/WIRE.md §3)."""
        if self.outcome is not None:
            # A message that arrives after this side already settled must not
            # silently rewrite an outcome already returned to my own caller
            # (PRD-03 "Symmetric timeout outcomes"). With ack-only tools there
            # is no rejection to send back — the sender learns it by timing out.
            logger.debug("ignored a turn that arrived after this sub-game settled")
            return

        try:
            message = parse_turn_message(raw)
        except ProtocolError as exc:
            # A malformed turn is the SENDER's fault, and it is a technical
            # loss for them — not something to absorb quietly.
            logger.warning("refused a malformed inbound turn: %s", exc)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=other_side(self.role))
            return

        if message.sender != other_side(self.role).value:
            logger.warning("refused a turn claiming sender=%r", message.sender)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=other_side(self.role))
            return

        # At-least-once delivery (kit SPEC §7.1): a retried push carries the
        # SAME commit. Processing it twice would double-count a step and desync
        # the audit, so a repeat is dropped rather than re-applied.
        if message.commit in self._seen_commits:
            logger.debug("dropped a duplicate turn for commit %s", message.commit[:8])
            return
        self._seen_commits.add(message.commit)

        async with self._lock:
            self._absorb_turn(message)
            self._resolve_claims(message)

    def _absorb_turn(self, message: TurnMessage) -> None:
        """Steps 1-3: audit commit, declared barrier, belief. Nothing here
        touches an opponent position, because none was sent."""
        self.received_commits.record(message.step, message.commit)
        if message.barrier_placed:
            row, col = message.barrier_placed
            self.state = note_opponent_barrier(self.state, Position(row, col))
        self._belief = absorb_opponent_signals(self._belief, self.state.board, message)

    def _resolve_claims(self, message: TurnMessage) -> None:
        """Step 4: the claim protocol — the ONLY way a capture or a survival is
        established now that no shared board exists."""
        # The thief confirmed my capture claim: I am the police and I won.
        if message.claim_response and message.claim_response.get("caught"):
            self._finish(TerminalCondition.CAPTURE_LANDING)
            return

        # The thief claims it survived its full step budget.
        if message.win_claim:
            self._finish(TerminalCondition.SURVIVAL)
            return

        # The police claims my cell. Answer honestly on my NEXT turn — lying is
        # pointless, the audit reveals my sealed position (docs/WIRE.md §5).
        if message.capture_claim:
            answer = answer_capture_claim(self.state, message.capture_claim)
            self._pending_claim_response = answer
            self._i_am_caught = bool(answer["caught"])

        self._take_turn_back()

    def _other_side(self) -> Side:
        return other_side(self.role)
