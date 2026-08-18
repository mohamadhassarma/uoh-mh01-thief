"""The single entry point wiring runtime (MCP transport, state machine,
watchdog) to the domain engine (rule #3). Contains NO decision logic (that's
strategies.py / stage 5's brain) and NO low-level transport itself (that's
infra/mcp_client.py and infra/mcp_server.py) — its job is to coordinate.

PeerRuntime is the only place that holds this peer's live match state. There
is exactly one instance per process; the two peers' PeerRuntime objects never
share memory, a file, or a module — the MCP transport (infra/mcp_client.py
calling into the opponent's infra/mcp_server.py) is the only channel between
them, per the Zero-Trust mandatory rules #1/#2.

The top-level match loop lives in infra/match_loop.py; the two halves of one
active turn cycle — driving MY OWN turns, and handling an INCOMING opponent
move/declaration — live in infra/turn_sender.py and infra/turn_receiver.py.
All three are mixins, split out purely to keep this file (and those) under
the project's ~150-line budget. PeerRuntime is still the one class and the
one live-state owner; only its method bodies are split across files.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from .domain import belief as belief_module
from .domain.belief import BeliefMap
from .domain.config import GameConfig
from .domain.crypto import seal
from .domain.match import FIRST_MOVER, Strategy
from .domain.scent import ScentField
from .domain.sealed_payload import build_move_payload, state_str
from .domain.state import MatchState, Side
from .domain.strategies import make_random_strategy
from .infra.audit import ReceivedCommitLog
from .infra.match_log import MatchLogRecorder
from .infra.match_loop import _MatchLoopMixin
from .infra.outcomes import DisputedOutcomeError, MatchOutcome
from .infra.protocol_response import MoveResponse
from .infra.state_machine import StateMachine
from .infra.turn_receiver import _TurnReceiverMixin
from .infra.turn_sender import _TurnSenderMixin
from .infra.watchdog import FreezeWatchdog
from .shared.peer_config import PeerConfig

logger = logging.getLogger(__name__)

__all__ = ["DisputedOutcomeError", "MatchOutcome", "PeerRuntime"]


class PeerRuntime(_MatchLoopMixin, _TurnSenderMixin, _TurnReceiverMixin):
    """Owns this peer's local copy of the match, its state machine, and its
    watchdog, and drives its own active turns. The MCP server's tool handler
    (infra/mcp_server.py) delegates incoming opponent moves straight to
    `receive_opponent_move`; the active-turn loop lives in `run_match`. Both
    touch `self.state` under `self._lock` since they run concurrently on the
    same event loop.
    """

    def __init__(
        self,
        role: Side,
        config: GameConfig,
        peer_config: PeerConfig,
        strategy: Strategy | None = None,
        *,
        sub_game_number: int = 1,
    ):
        self.role = role
        self.config = config
        self.peer_config = peer_config
        self.sub_game_number = sub_game_number
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
        # PRD-03: my own sealed (payload, nonce, commit) records, kept until
        # the mutual audit reveals nonces; and the opponent's live-received
        # (payload, commit) pairs, audited against per WARNINGS §5d — never
        # a copy the revealer could rewrite after the fact.
        self.own_sealed_records: list[dict[str, Any]] = []
        self.received_commits = ReceivedCommitLog()
        # At-least-once delivery (interop kit SPEC §7.1): a retried
        # submit_move/reveal_audit call carries the SAME commit as the
        # original. Caching the response we gave the first time and
        # replaying it verbatim on a repeat — rather than re-evaluating the
        # request against state that has since moved on — is what makes a
        # lost RESPONSE (not a lost request) harmless instead of a spurious
        # rejection. See PRD-03 "Symmetric timeout outcomes".
        self._replayed_responses: dict[str, MoveResponse] = {}
        # PRD-04: my own scent trail (domain/scent.py) and my belief about
        # the opponent's hidden position (domain/belief.py) — never derived
        # from the true opposing position (Zero-Trust, rule #1/#2).
        self._own_scent_field: ScentField = {}
        self._belief: BeliefMap = belief_module.initial_belief(self.state.board)

    # ------------------------------------------------------------------
    # The top-level match loop AND settling a final/claimed outcome
    # (_MatchLoopMixin), and the two turn-handling halves
    # (_TurnSenderMixin, _TurnReceiverMixin) hold the rest of PeerRuntime's
    # behaviour; what remains here is per-step sealing, owned directly by
    # this class since it is where own_sealed_records lives.
    # ------------------------------------------------------------------

    def _my_position(self) -> Any:
        return self.state.cop_pos if self.role is Side.POLICE else self.state.thief_pos

    def _seal_own_record(self, *, step: int, action_type: str, detail: str, smell_grid: dict[str, float] | None = None) -> str:
        """Build this step's payload (self-only position, matching the
        book/reference `state` convention), seal it (PRD-03), and stash the
        full record locally for the post-sub-game audit reveal. Returns only
        the commit hash — the one thing that may go out on the wire now.

        `smell_grid` (PRD-04) is sealed alongside the move so the opponent's
        audit re-hash catches a grid that was quietly altered between what
        went out live and what gets revealed."""
        payload = build_move_payload(
            step=step,
            role=self.role.value,
            action_type=action_type,
            detail=detail,
            state=state_str(self.state.board.grid_size, self._my_position(), self.state.board.barriers),
            smell_grid=smell_grid,
        )
        sealed = seal(payload)
        self.own_sealed_records.append({"step": step, "payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]})
        return sealed["commit"]
