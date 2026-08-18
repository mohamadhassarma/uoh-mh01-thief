"""Driving THIS peer's own active turns.

Split out of orchestrator.py to keep files under the project's ~150-line
budget (mirroring the reference implementation's own peer/turn_sender.py
split — see PRD-02 "Part A findings"). A mixin, not a standalone class, so
PeerRuntime keeps a single ordinary method-call surface
(`self._take_my_turn()`) even though the implementation lives here.
"""

from __future__ import annotations

import logging

from ..domain.match import Action, BarrierAction, MoveAction
from ..domain.scoring import TerminalCondition
from ..domain.state import apply_barrier, apply_move, other_side
from ..domain.terminal_detect import (
    DetectedTerminal,
    detect_from_last_action,
    detect_pre_turn,
)
from .mcp_client import send_with_retry
from .outcomes import DisputedOutcomeError
from .protocol import MoveRequest, action_to_request, declare_terminal_request
from .state_machine import Phase
from .watchdog import OpponentUnresponsiveError

logger = logging.getLogger(__name__)


class _TurnSenderMixin:
    def _apply_own_action(self, action: Action):
        if isinstance(action, MoveAction):
            return apply_move(self.state, action.direction)
        assert isinstance(action, BarrierAction)
        return apply_barrier(self.state, action.target)

    async def _take_my_turn(self) -> None:
        pre_claim = detect_pre_turn(self.state, self.role)
        if pre_claim is not None:
            await self._declare_and_settle(pre_claim)
            return

        self._transition(Phase.COMPUTING_MOVE)
        try:
            action: Action = self._strategy(self.state, self.role)
        except Exception:
            logger.exception("local move computation failed")
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.role)
            return

        self._transition(Phase.COMMITTING)
        commit = self._commit(action)
        turn_number = self.state.turn_number

        # Apply MY OWN action to MY OWN state — and hand the turn to the
        # opponent — BEFORE sending it. See PRD-02 "Architecture decisions"
        # #3 for the race this closes. Unlike stage 2's first cut, the
        # resulting terminal CLAIM (if any) is not yet trusted as my final
        # outcome — see "Stage 2 corrections" B1: it still has to survive a
        # declare/confirm round trip with the opponent.
        async with self._lock:
            new_state = self._apply_own_action(action)
            claim = detect_from_last_action(new_state)
            self.state = new_state
            self.log.record_action(self.state.move_log[-1])
            if claim is None:
                self._advance_turn()

        request = action_to_request(
            action,
            self.role,
            turn_number,
            police_actions_taken=self.state.police_actions_taken,
            thief_actions_taken=self.state.thief_actions_taken,
            claimed_condition=claim.condition if claim else None,
        )
        self._transition(Phase.AWAITING_REVEAL)
        await self._send_and_resolve(request, claim, commit)

    async def _declare_and_settle(self, claim: DetectedTerminal) -> None:
        """Entrapment or the max_moves ceiling: a terminal condition detected
        with NO accompanying move. Declared explicitly rather than just
        going silent — see PRD-02 'Stage 2 corrections' B1."""
        self._transition(Phase.COMPUTING_MOVE)
        self._transition(Phase.COMMITTING)
        request = declare_terminal_request(
            self.role,
            self.state.turn_number,
            claim.condition,
            police_actions_taken=self.state.police_actions_taken,
            thief_actions_taken=self.state.thief_actions_taken,
        )
        self._transition(Phase.AWAITING_REVEAL)
        await self._send_and_resolve(request, claim, commit=None)

    async def _send_and_resolve(self, request: MoveRequest, claim: DetectedTerminal | None, commit) -> None:
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

        self._transition(Phase.VERIFYING)
        if commit is not None:
            self._verify(commit, response)

        if claim is not None:
            theirs = response.terminal.condition if response.terminal is not None else None
            if response.claim_agreement:
                self._finish_claim(claim)
            else:
                raise DisputedOutcomeError(mine=claim.condition, theirs=theirs)

        self._transition(Phase.WAITING_FOR_OPPONENT)
