"""Handling an INCOMING opponent move or terminal-condition declaration.

Split out of orchestrator.py to keep files under the project's ~150-line
budget (mirroring the reference implementation's own peer/turn_handler.py
split — see PRD-02 "Part A findings"). A mixin, not a standalone class, so
PeerRuntime keeps a single ordinary method-call surface
(`self.receive_opponent_move(...)`) even though the implementation lives
here. Per PRD-02 "Architecture decisions" #2, this NEVER transitions this
peer's own state machine — it only updates MatchState and, on a terminal
condition, this peer's outcome.
"""

from __future__ import annotations

import logging

from ..domain.match import UndefinedOutcomeError
from ..domain.scoring import TerminalCondition, score_for
from ..domain.state import (
    IllegalActionError,
    MatchState,
    Side,
    apply_barrier,
    apply_move,
    other_side,
)
from ..domain.terminal_detect import detect_from_last_action, detect_pre_turn
from .outcomes import DisputedOutcomeError
from .protocol import MoveRequest, request_to_action
from .protocol_response import MoveResponse, TerminalInfo

logger = logging.getLogger(__name__)


def _counter_mismatch(request: MoveRequest, expected: MatchState) -> str | None:
    """B2: every message carries the sender's own post-action counters; the
    receiver rejects any message whose counters don't match what its OWN
    local state expects — the one place a lost/duplicated/reordered message
    is caught rather than silently applied. See PRD-02 'Stage 2
    corrections'."""
    if request.police_actions_taken != expected.police_actions_taken or request.thief_actions_taken != expected.thief_actions_taken:
        return (
            f"counter mismatch: sender claims police={request.police_actions_taken} "
            f"thief={request.thief_actions_taken}, my local state expects "
            f"police={expected.police_actions_taken} thief={expected.thief_actions_taken}"
        )
    return None


class _TurnReceiverMixin:
    async def receive_opponent_move(self, request: MoveRequest) -> MoveResponse:
        self._in_flight += 1
        try:
            async with self._lock:
                sender = Side(request.role)
                if sender is not other_side(self.role):
                    return MoveResponse(accepted=False, reason=f"unexpected sender role {request.role!r}")
                if request.action_type == "declare_terminal":
                    return self._handle_declare_terminal(sender, request)
                return self._handle_move_or_barrier(sender, request)
        finally:
            self._in_flight -= 1

    def _handle_declare_terminal(self, sender: Side, request: MoveRequest) -> MoveResponse:
        mismatch = _counter_mismatch(request, self.state)
        if mismatch is not None:
            return MoveResponse(accepted=False, divergence=mismatch)

        my_claim = detect_pre_turn(self.state, sender)
        my_condition = my_claim.condition if my_claim else None
        self._opponent_moved.set()

        if my_condition != request.claimed_condition:
            self._pending_error = DisputedOutcomeError(mine=my_condition, theirs=request.claimed_condition)
            return MoveResponse(accepted=True, claim_agreement=False)

        try:
            self._finish_claim(my_claim)
        except UndefinedOutcomeError as exc:
            self._pending_error = exc
            return MoveResponse(accepted=True, claim_agreement=True)
        return MoveResponse(accepted=True, terminal=self._current_terminal_info(), claim_agreement=True)

    def _handle_move_or_barrier(self, sender: Side, request: MoveRequest) -> MoveResponse:
        if self.state.whose_turn is not sender:
            return MoveResponse(accepted=False, reason="it is not the sender's turn per my local state")

        action = request_to_action(request)
        try:
            new_state = apply_move(self.state, action.direction) if request.action_type == "move" else apply_barrier(self.state, action.target)
        except IllegalActionError as exc:
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=sender)
            return MoveResponse(
                accepted=False,
                reason=str(exc),
                terminal=TerminalInfo("technical_loss", *score_for(TerminalCondition.TECHNICAL_LOSS, self.config.scoring), sender.value),
            )

        mismatch = _counter_mismatch(request, new_state)
        if mismatch is not None:
            return MoveResponse(accepted=False, divergence=mismatch)

        claim = detect_from_last_action(new_state)
        my_condition = claim.condition if claim else None
        self.state = new_state
        self.log.record_action(self.state.move_log[-1])
        self.watchdog.heartbeat()

        if my_condition != request.claimed_condition:
            self._pending_error = DisputedOutcomeError(mine=my_condition, theirs=request.claimed_condition)
            self._opponent_moved.set()
            return MoveResponse(accepted=True, terminal=None, claim_agreement=False)

        if claim is not None:
            self._finish_claim(claim)  # never UNDEFINED_CEILING here: that only ever arrives via "declare_terminal"
        else:
            self._advance_turn()

        self._opponent_moved.set()
        return MoveResponse(
            accepted=True,
            terminal=self._current_terminal_info(),
            claim_agreement=(True if request.claimed_condition is not None else None),
        )
