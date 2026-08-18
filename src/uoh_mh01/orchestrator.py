"""The single entry point wiring runtime (MCP transport, state machine,
watchdog) to the domain engine (rule #3). Contains NO decision logic (that's
strategies.py / stage 5's brain) and NO low-level transport itself (that's
infra/mcp_client.py and infra/mcp_server.py) — its job is to coordinate.

PeerRuntime is the only place that holds this peer's live match state. There
is exactly one instance per process; the two peers' PeerRuntime objects never
share memory, a file, or a module — the MCP transport (infra/mcp_client.py
calling into the opponent's infra/mcp_server.py) is the only channel between
them, per the Zero-Trust mandatory rules #1/#2.

The two halves of one active turn cycle — driving MY OWN turns, and handling
an INCOMING opponent move/declaration — live in infra/turn_sender.py and
infra/turn_receiver.py as mixins, to keep this file (and those) under the
project's ~150-line budget. PeerRuntime is still the one class and the one
live-state owner; only its method bodies are split across files.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import Any

from .domain.config import GameConfig
from .domain.match import FIRST_MOVER, Action, Strategy, UndefinedOutcomeError
from .domain.scoring import TerminalCondition, score_for
from .domain.state import MatchState, Side, next_turn, other_side
from .domain.strategies import make_random_strategy
from .domain.terminal_detect import UNDEFINED_CEILING, DetectedTerminal
from .infra.match_log import MatchLogRecorder
from .infra.outcomes import DisputedOutcomeError, MatchOutcome
from .infra.peer_entrypoint import run_peer
from .infra.protocol_response import MoveResponse, TerminalInfo
from .infra.stage3_placeholders import commit as _stage3_placeholder_commit
from .infra.stage3_placeholders import verify as _stage3_placeholder_verify
from .infra.state_machine import Phase, StateMachine
from .infra.turn_receiver import _TurnReceiverMixin
from .infra.turn_sender import _TurnSenderMixin
from .infra.watchdog import FreezeDetected, FreezeWatchdog
from .shared.peer_config import PeerConfig

logger = logging.getLogger(__name__)

__all__ = ["DisputedOutcomeError", "MatchOutcome", "PeerRuntime", "run_peer"]


class PeerRuntime(_TurnSenderMixin, _TurnReceiverMixin):
    """Owns this peer's local copy of the match, its state machine, and its
    watchdog, and drives its own active turns. The MCP server's tool handler
    (infra/mcp_server.py) delegates incoming opponent moves straight to
    `receive_opponent_move`; the active-turn loop lives in `run_match`. Both
    touch `self.state` under `self._lock` since they run concurrently on the
    same event loop.
    """

    def __init__(self, role: Side, config: GameConfig, peer_config: PeerConfig, strategy: Strategy | None = None):
        self.role = role
        self.config = config
        self.peer_config = peer_config
        self._strategy = strategy or make_random_strategy(random.Random())
        self.state = MatchState.initial(config, first_mover=FIRST_MOVER)
        self.state_machine = StateMachine()
        self.watchdog = FreezeWatchdog(timeout_sec=config.network.watchdog_timeout_sec)
        self.log = MatchLogRecorder(role=role.value, group_id=peer_config.group_id)
        self._opponent_moved = asyncio.Event()
        self._lock = asyncio.Lock()
        self.outcome: MatchOutcome | None = None
        self._turn_started_at = time.monotonic()
        self._in_flight = 0  # concurrent receive_opponent_move calls in progress
        # Set by the passive/receiver side (infra/turn_receiver.py) when it
        # detects a disagreement with an opponent's claim, or confirms an
        # opponent's max_moves-ceiling declare_terminal — there is no clean
        # way to raise across the MCP call boundary back into my own
        # run_match() loop, so it's staged here and re-raised at the top of
        # the loop.
        self._pending_error: BaseException | None = None
        # A claim (capture/survival/entrapment/ceiling) I made that could
        # not be confirmed because the opponent went silent — recorded in
        # the log alongside the resulting TECHNICAL_LOSS purely for the
        # audit trail (stage 2 corrections, round 2): the score is still the
        # symmetric technical-loss pair, never the claimed outcome, but the
        # claim itself must not be lost from the record. See "Stage 2
        # corrections" (round 2) in PRD-02.
        self._unconfirmed_claim: str | None = None

    # ------------------------------------------------------------------
    # Driving MY OWN active turns (loop only — the turn body is the
    # _TurnSenderMixin)
    # ------------------------------------------------------------------

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
            # Every other path (a claim's own retry-until-watchdog ceiling,
            # the passive wait's turn_timeout_seconds check) is meant to
            # resolve to a terminal condition BEFORE this fires. If none of
            # them did, this is the last-resort net: rule #35 has no
            # "the protocol didn't resolve" case, and an unreported match
            # scores zero for BOTH teams, so this may never propagate as a
            # bare exception. Whichever side currently holds the turn is the
            # one that failed to act or respond within every narrower
            # timeout. See PRD-02 "Stage 2 corrections" (round 2).
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

    def _commit(self, action: Action) -> dict[str, Any]:
        return _stage3_placeholder_commit(action)

    def _verify(self, commit: dict[str, Any], response: MoveResponse) -> None:
        _stage3_placeholder_verify(commit, response)  # always true in stage 2

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
