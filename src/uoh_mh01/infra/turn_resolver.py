"""Resolving the opponent's response to one of MY OWN sent turns.

Split out of turn_sender.py to keep files under the project's ~150-line
budget. A mixin, not a standalone class — see turn_sender.py's own
module docstring for why.
"""

from __future__ import annotations

import logging

from ..domain.scoring import TerminalCondition
from ..domain.state import other_side
from ..domain.terminal_detect import DetectedTerminal
from .mcp_client import send_with_retry
from .outcomes import DisputedOutcomeError
from .protocol import MoveRequest
from .state_machine import Phase
from .watchdog import OpponentUnresponsiveError

logger = logging.getLogger(__name__)


class _TurnResolverMixin:
    async def _send_and_resolve(self, request: MoveRequest, claim: DetectedTerminal | None) -> None:
        try:
            response = await send_with_retry(
                self.peer_config.opponent_url,
                request,
                response_timeout_sec=self.config.network.response_timeout_sec,
                watchdog=self.watchdog,
                watchdog_timeout_sec=self.config.network.watchdog_timeout_sec,
            )
        except OpponentUnresponsiveError:
            # Genuine silence — including silence in response to my own
            # claim. A claim I cannot get confirmed is not scored on trust
            # alone; see PRD-02 "Stage 2 corrections" B1's documented
            # trade-off. The score is always the symmetric technical-loss
            # pair, never the claimed outcome — but the claim itself is
            # still recorded alongside it for the audit (round 2 of the
            # corrections: silence must still reach a reportable terminal
            # condition, and losing the claim from the record would make
            # that record less useful, not incorrect).
            logger.warning("opponent unresponsive beyond watchdog_timeout_sec during AWAITING_REVEAL")
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(
                TerminalCondition.TECHNICAL_LOSS,
                offending_side=other_side(self.role),
                unconfirmed_claim=claim.condition if claim else None,
            )
            return

        if response.divergence is not None:
            logger.warning("opponent reported a counter divergence: %s", response.divergence)
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=None)
            return

        if not response.accepted:
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.role)
            return

        # Real cryptographic verification happens at the post-sub-game
        # mutual audit (infra/audit.py), not per turn — a per-turn hash
        # check is impossible without the opponent's nonce, which stays
        # secret until then. VERIFYING still exists as a formal phase (the
        # mandatory transition table gives it no failure edge, matching
        # this — see PRD-02 "Architecture decisions" #1).
        self._transition(Phase.VERIFYING)

        if claim is not None:
            theirs = response.terminal.condition if response.terminal is not None else None
            if response.claim_agreement:
                self._finish_claim(claim)
            else:
                raise DisputedOutcomeError(mine=claim.condition, theirs=theirs)

        self._transition(Phase.WAITING_FOR_OPPONENT)
