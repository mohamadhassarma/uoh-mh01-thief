"""Driving THIS peer's own active turns, against MY OWN state only.

Emits the contract `TurnMessage` (docs/WIRE.md §2) — ten keys, no move in the
clear — and pushes it with `send_turn`, which returns nothing. The opponent's
answer is its own turn, arriving in my inbox for the poll loop to pick up.
"""

from __future__ import annotations

import logging

from ..domain.board import Direction
from ..domain.match import Action, MoveAction
from ..domain.own_state import apply_own_barrier, apply_own_move
from ..domain.scoring import TerminalCondition
from ..domain.state import IllegalActionError
from ..domain.terminal_detect import peer_capture_claim, peer_win_claim
from .mcp_client import send_turn
from .state_machine import Phase
from .turn_message_builders import build_turn_message
from .watchdog import OpponentUnresponsiveError

logger = logging.getLogger(__name__)

_FINAL_CAUGHT_HINT = "You got me."


class _TurnSenderMixin:
    async def _take_my_turn(self) -> None:
        # The ONLY pre-turn self-check left: my own max_moves ceiling. It reads
        # nothing but my own action count. Entrapment is gated off here — see
        # domain/terminal_detect.py's peer-path banner.
        if self.state.step_number >= self.config.movement.max_moves:
            self._settle_ceiling_locally()
            return

        if self._i_am_caught:
            await self._send_final_caught()
            return

        self._transition(Phase.COMPUTING_MOVE)
        # PRD-05: a BrainBase strategy reads its `belief` attribute inside
        # __call__ — set immediately before invoking, never passed as a call
        # argument, so the Strategy signature stays 2-argument.
        if hasattr(self._strategy, "belief"):
            self._strategy.belief = self._belief

        # DELIBERATELY UNGUARDED (PRD-06 hardening). This used to be wrapped in
        # `except Exception -> technical loss`, which turned a programming error
        # into something indistinguishable from a legitimately lost game. It hid
        # a real one: after the state split, `legal_actions` raised
        # AttributeError on EVERY turn, so every game "ended" instantly in a
        # technical loss with zero sealed records and a vacuously-passing audit.
        #
        # A brain that raises is a BUG in our code, not a game event, and it must
        # be loud. Illegal-but-well-formed actions are still handled: they raise
        # IllegalActionError out of apply_own_* below, which IS a real game
        # outcome and IS caught there.
        action: Action = self._strategy(self.state, self.role)
        await self._apply_seal_and_send(action)

    async def _apply_seal_and_send(self, action: Action, *, hint_override: str | None = None) -> None:
        self._transition(Phase.COMMITTING)
        async with self._lock:
            try:
                self.state = (
                    apply_own_move(self.state, action.direction)
                    if isinstance(action, MoveAction)
                    else apply_own_barrier(self.state, action.target)
                )
            except IllegalActionError:
                # An illegal action against MY OWN state is mine alone to own —
                # there is no opponent mirror to catch it for me any more.
                logger.warning("attempted an illegal action against my own state")
                self._transition(Phase.TECHNICAL_LOSS)
                self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.role)
                return
            entry = self.state.step_log[-1]
            commit, smell_grid, hint_text, hint_is_true = self._seal_step(entry, hint_override)
            self.log.record_action(entry, self.role)

            capture_claim = peer_capture_claim(self.state, action)
            win_claim = peer_win_claim(self.state)
            claim_response, self._pending_claim_response = self._pending_claim_response, None
            barrier = entry.barrier_placed
            self._hand_turn_over()

        message = build_turn_message(
            step=entry.step,
            sender=self.role.value,
            hint=hint_text,
            smell_grid=smell_grid,
            commit=commit,
            barrier_placed=[barrier.row, barrier.col] if barrier else None,
            capture_claim=capture_claim,
            claim_response=claim_response,
            win_claim=win_claim,
        )
        # `hint_is_true` is sealed in the commit but is NOT a wire field: the
        # contract has no slot for it, and the receiver could not verify it live
        # anyway. It reaches the opponent at the audit reveal, inside the
        # payload — which is exactly what makes "lying about whether you lied" a
        # tamper finding rather than an unfalsifiable claim (PRD-05 §C).
        _ = hint_is_true

        self._transition(Phase.AWAITING_REVEAL)
        if not await self._push(message.to_wire(), capture_claim):
            return
        # My own survival claim settles on MY OWN state the moment it is sent:
        # it is provable from my sealed chain at audit and needs no
        # confirmation (ref_impl peer/turn_sender.py:55-56).
        if win_claim is not None and self.outcome is None:
            self._finish(TerminalCondition.SURVIVAL)

    async def _push(self, wire: dict, capture_claim) -> bool:
        """Push one turn. Returns False if the send failed and the sub-game is
        already settled as a technical loss."""
        try:
            await send_turn(
                self.peer_config.opponent_url,
                wire,
                response_timeout_sec=self.config.network.response_timeout_sec,
                watchdog=self.watchdog,
                watchdog_timeout_sec=self.config.network.watchdog_timeout_sec,
            )
        except OpponentUnresponsiveError:
            logger.warning("opponent unresponsive beyond watchdog_timeout_sec while sending my turn")
            self._transition(Phase.TECHNICAL_LOSS)
            self._finish(
                TerminalCondition.TECHNICAL_LOSS,
                offending_side=self._other_side(),
                # A claim I made but could never get answered still belongs in
                # the record (PRD-02 corrections, round 2).
                unconfirmed_claim=TerminalCondition.CAPTURE_LANDING.value if capture_claim else None,
            )
            return False
        self._transition(Phase.VERIFYING)
        self._transition(Phase.WAITING_FOR_OPPONENT)
        return True

    async def _send_final_caught(self) -> None:
        """The mandatory 'You got me' answer, sent before settling as captured
        (ref_impl peer/turn_sender.py:72-77). The honest answer must reach the
        opponent or it cannot claim the capture it actually earned."""
        self._i_am_caught = False
        # Still a real turn as far as the state machine is concerned: the only
        # legal edge out of WAITING_FOR_OPPONENT is COMPUTING_MOVE, and
        # _apply_seal_and_send goes straight to COMMITTING.
        self._transition(Phase.COMPUTING_MOVE)
        await self._apply_seal_and_send(MoveAction(Direction.STAY), hint_override=_FINAL_CAUGHT_HINT)
        if self.outcome is None:
            self._finish(TerminalCondition.CAPTURE_LANDING)

    def _settle_ceiling_locally(self) -> None:
        """My own max_moves ceiling, reached with nothing else having fired.

        Settled LOCALLY, with no wire message: the contract has no
        declare-terminal shape (docs/WIRE.md §2.1 — the ten keys carry claims,
        not condition declarations), so there is nothing conformant to send.
        Unreachable under the real signed contract, where
        `max_moves == survival_threshold == 35` means the thief's survival
        claim always fires first; it only matters if a future negotiation sets
        `survival_threshold > max_moves`.
        """
        from ..domain.match import UndefinedOutcomeError

        self._pending_error = UndefinedOutcomeError(
            "max_moves ceiling reached without any other terminal condition firing — "
            "see PRD-01 'Open questions'"
        )
