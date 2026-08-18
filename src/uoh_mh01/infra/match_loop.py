"""Driving THIS peer's own top-level match loop: whose turn is it, the two
private timeout budgets (B3), and top-of-loop freeze detection.

Split out of orchestrator.py (alongside turn_sender.py/turn_receiver.py) to
keep that file under the project's ~150-line budget — PeerRuntime is still
the one class and the one live-state owner; only this slice of its method
bodies lives here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from ..domain.match import FIRST_MOVER, UndefinedOutcomeError
from ..domain.scoring import TerminalCondition, score_for
from ..domain.state import Side, next_turn, other_side
from ..domain.terminal_detect import UNDEFINED_CEILING, DetectedTerminal
from .outcomes import DisputedOutcomeError, MatchOutcome
from .protocol_response import TerminalInfo
from .state_machine import Phase
from .watchdog import FreezeDetected

logger = logging.getLogger(__name__)

# Grace period for an opponent message CURRENTLY in flight (self._in_flight
# > 0) when my own passive-wait timeout fires (_wait_for_opponent) — covers
# ordinary processing latency under load; never extends the wait when the
# opponent sent nothing at all (_in_flight stays 0). An internal robustness
# margin, not a signed contract value.
_IN_FLIGHT_GRACE_SEC = 5.0


class _MatchLoopMixin:
    async def run_match(self) -> MatchOutcome:
        try:
            while self.outcome is None:
                self.watchdog.assert_alive()
                if self._pending_error is not None:
                    raise self._pending_error
                if self.state.whose_turn is self.role:
                    await self._run_my_turn_within_budget()
                else:
                    await self._wait_for_opponent()
        except FreezeDetected as exc:
            # Last-resort net: every narrower timeout is meant to resolve a
            # terminal condition before this fires. Rule #35 has no "the
            # protocol didn't resolve" case, so this must not propagate bare.
            # See PRD-02 "Stage 2 corrections" (round 2).
            logger.warning("watchdog fired with no narrower timeout catching it first: %s", exc)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.state.whose_turn)
        except UndefinedOutcomeError as exc:
            self.log.finalize(condition=None, police_score=None, thief_score=None, undefined_outcome=str(exc))
            raise
        except DisputedOutcomeError as exc:
            self.log.finalize(
                condition=None, police_score=None, thief_score=None, disputed={"mine": exc.mine, "theirs": exc.theirs}
            )
            raise

        self.log.finalize(
            condition=self.outcome.terminal_condition.value,
            police_score=self.outcome.police_score,
            thief_score=self.outcome.thief_score,
            offending_side=self.outcome.offending_side.value if self.outcome.offending_side else None,
            unconfirmed_claim=self._unconfirmed_claim,
        )
        return self.outcome

    async def _run_my_turn_within_budget(self) -> None:
        """B3: this peer's own PRIVATE turn_timeout_seconds budget for one
        whole turn (local compute + the network exchange), independent of
        watchdog_timeout_sec. A timeout here self-forfeits rather than
        hanging — but note it cannot transition the state machine (whatever
        Phase _take_my_turn had reached has no TECHNICAL_LOSS edge from every
        node in the given table), exactly like the existing entrapment
        pre-check already settles outside the formal per-turn protocol. See
        PRD-02 'Stage 2 corrections' B3."""
        try:
            await asyncio.wait_for(self._take_my_turn(), timeout=self.peer_config.turn_timeout_seconds)
        except TimeoutError:
            logger.warning("exceeded my own private turn_timeout_seconds budget")
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.role)

    async def _wait_for_opponent(self) -> None:
        self._opponent_moved.clear()
        wait_budget = min(self.config.network.watchdog_timeout_sec, self.peer_config.turn_timeout_seconds)
        # A plain timeout here is not itself a fault — it just means neither
        # the opponent nor a turn_timeout_seconds breach has happened yet;
        # the top-of-loop watchdog.assert_alive() is what reports a real
        # freeze, precisely, one loop iteration later.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._opponent_moved.wait(), timeout=wait_budget)
        if self.outcome is not None or self._pending_error is not None:
            return
        if self._in_flight > 0:
            # The opponent's message DID arrive before I gave up — slow
            # under load, not silent. Grace period instead of unilaterally
            # blaming a side that is not actually unresponsive. PRD-03
            # "Symmetric timeout outcomes".
            deadline = asyncio.get_event_loop().time() + _IN_FLIGHT_GRACE_SEC
            while self._in_flight > 0 and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.05)
            if self.outcome is not None or self._pending_error is not None:
                return
        if time.monotonic() - self._turn_started_at > self.peer_config.turn_timeout_seconds:
            logger.warning("opponent exceeded my private turn_timeout_seconds budget")
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=other_side(self.role))

    def _transition(self, phase: Phase) -> None:
        self.state_machine.transition(phase)
        self.log.record_phase(phase)
        self.watchdog.heartbeat()

    def _advance_turn(self) -> None:
        self.state = next_turn(self.state, FIRST_MOVER)
        self._turn_started_at = time.monotonic()

    def _finish(
        self, condition: TerminalCondition, *, offending_side: Side | None = None, unconfirmed_claim: str | None = None
    ) -> None:
        police_score, thief_score = score_for(condition, self.config.scoring, offending_side=offending_side)
        self.outcome = MatchOutcome(condition, police_score, thief_score, offending_side=offending_side)
        if unconfirmed_claim is not None:
            self._unconfirmed_claim = unconfirmed_claim
        self._opponent_moved.set()

    def _finish_claim(self, claim: DetectedTerminal) -> None:
        """Turn a CONFIRMED claim (agreed by both sides) into this side's own
        settled outcome — never called for a claim that hasn't survived
        declare/confirm. See PRD-02 'Stage 2 corrections' B1."""
        if claim.condition == UNDEFINED_CEILING:
            raise UndefinedOutcomeError(
                "max_moves ceiling reached without any other terminal condition firing, "
                "confirmed by both sides after a declare/confirm exchange — see PRD-01 'Open questions'"
            )
        self._finish(TerminalCondition(claim.condition), offending_side=claim.offending_side)

    def _current_terminal_info(self) -> TerminalInfo | None:
        if self.outcome is None:
            return None
        return TerminalInfo(
            self.outcome.terminal_condition.value,
            self.outcome.police_score,
            self.outcome.thief_score,
            self.outcome.offending_side.value if self.outcome.offending_side else None,
        )
