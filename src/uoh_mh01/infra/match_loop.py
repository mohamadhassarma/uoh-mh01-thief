"""Driving THIS peer's own top-level match loop: whose turn is it, the two
private timeout budgets (B3), and top-of-loop freeze detection.

Split out of orchestrator.py (alongside turn_sender.py/turn_receiver.py) to
keep that file under the project's ~150-line budget — PeerRuntime is still
the one class and the one live-state owner; only this slice of its method
bodies lives here.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..domain.match import UndefinedOutcomeError
from ..domain.scoring import TerminalCondition, score_for
from ..domain.state import Side, other_side
from ..domain.terminal_detect import UNDEFINED_CEILING, DetectedTerminal
from .control_link import PLAYING, WAITING
from .inboxes import poll, poll_now
from .mcp_client import send_control
from .outcomes import DisputedOutcomeError, MatchOutcome
from .state_machine import Phase
from .watchdog import FreezeDetected

logger = logging.getLogger(__name__)

# How often the poll loop checks its own turns inbox. The reference's own
# `network.poll_interval_seconds` default (ref_impl runtime.py:103); an
# internal cadence, not a signed contract value.
_POLL_INTERVAL_SEC = 0.5

# The advisory control channel's own budget. Was 2.0s, which was not headroom
# but a guarantee of failure: a control round-trip over a public tunnel
# measured 1.8-2.1s, so one side logged 16 control timeouts against 2
# successes on a healthy link. Nothing was lost (the channel is unscored and
# fire-and-forget) but the signal was, and a budget that always fails cannot
# tell you anything. 10s is real headroom over the worst tunnel latency we
# have measured; it stays fire-and-forget, so a departed opponent still costs
# the game nothing.
_CONTROL_TIMEOUT_SEC = 10.0


class _MatchLoopMixin:
    async def run_match(self) -> MatchOutcome:
        self._announce_control(PLAYING)
        try:
            while self.outcome is None:
                self.watchdog.assert_alive()
                if self._pending_error is not None:
                    raise self._pending_error
                if self.whose_turn is self.role:
                    await self._run_my_turn_within_budget()
                else:
                    await self._wait_for_opponent()
        except FreezeDetected as exc:
            # Last-resort net: every narrower timeout is meant to resolve a
            # terminal condition before this fires. Rule #35 has no "the
            # protocol didn't resolve" case, so this must not propagate bare.
            # See PRD-02 "Stage 2 corrections" (round 2).
            logger.warning("watchdog fired with no narrower timeout catching it first: %s", exc)
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=self.whose_turn)
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
        """POLL my own turns inbox (docs/WIRE.md §4). Replaces waiting on an
        asyncio.Event that a tool handler set: the handler is ack-only now and
        does no processing, so arrival and processing are separate concerns and
        only the loop that owns the state ever touches it.

        A plain empty poll is not a fault — it just means the opponent has not
        moved YET. Silence only becomes a technical loss once my own private
        turn_timeout_seconds budget has elapsed since the turn changed hands.
        """
        self._announce_control(WAITING)
        self._drain_control_channel()
        message = await poll(self.inboxes.turns, timeout=_POLL_INTERVAL_SEC, poll_interval=_POLL_INTERVAL_SEC)
        if message is not None:
            await self.receive_opponent_turn(message)
            return
        if self.outcome is not None or self._pending_error is not None:
            return
        if time.monotonic() - self._turn_started_at > self.peer_config.turn_timeout_seconds:
            logger.warning("opponent exceeded my private turn_timeout_seconds budget")
            self._finish(TerminalCondition.TECHNICAL_LOSS, offending_side=other_side(self.role))

    def _drain_control_channel(self) -> None:
        """Process every pending control message. Non-blocking and advisory:
        nothing here can change a game outcome (docs/WIRE.md §6)."""
        while (raw := poll_now(self.inboxes.controls)) is not None:
            self.control.handle(raw)

    def _announce_control(self, status: str) -> None:
        """Opt in on first use, then broadcast my status on change only.

        FIRE-AND-FORGET, deliberately. Awaiting these put advisory traffic on
        the critical path: two best-effort 2s sends against an unreachable
        opponent burned 4s before the first turn was even attempted, and the
        watchdog — which measures GAME progress — fired on that stall and
        blamed the wrong side. The channel is optional and unscored, so it must
        never be able to cost a game.
        """
        if not self.control.i_enabled:
            self._fire_control(self.control.enable())
        message = self.control.status_update(status, sub_game_number=self.sub_game_number)
        if message is not None:
            self._fire_control(message)

    def _fire_control(self, message: dict) -> None:
        task = asyncio.create_task(
            send_control(
                self.peer_config.opponent_url,
                message,
                response_timeout_sec=min(_CONTROL_TIMEOUT_SEC, self.config.network.response_timeout_sec),
            )
        )
        # Hold a reference until it finishes: a bare create_task can be
        # garbage-collected mid-flight.
        self._control_tasks.add(task)
        task.add_done_callback(self._control_tasks.discard)

    def _transition(self, phase: Phase) -> None:
        self.state_machine.transition(phase)
        self.log.record_phase(phase)
        self.watchdog.heartbeat()

    def _hand_turn_over(self) -> None:
        """The turn token travels WITH the message I am about to send —
        receiving one is what makes the other side green (docs/WIRE.md §4)."""
        self.whose_turn = other_side(self.role)
        self._turn_started_at = time.monotonic()

    def _take_turn_back(self) -> None:
        """Their message arrived, so the token is mine again."""
        self.whose_turn = self.role
        self._turn_started_at = time.monotonic()

    def _finish(
        self, condition: TerminalCondition, *, offending_side: Side | None = None, unconfirmed_claim: str | None = None
    ) -> None:
        police_score, thief_score = score_for(condition, self.config.scoring, offending_side=offending_side)
        self.outcome = MatchOutcome(condition, police_score, thief_score, offending_side=offending_side)
        if unconfirmed_claim is not None:
            self._unconfirmed_claim = unconfirmed_claim

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

