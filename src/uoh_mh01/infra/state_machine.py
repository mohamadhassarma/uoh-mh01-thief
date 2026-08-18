"""The mandatory turn-protocol state machine (rulebook rules #4/#5).

Its job is deadlock prevention: without a formal machine that rejects illegal
transitions loudly, a peer-to-peer system with no central judge can hang
forever with no error message. This machine tracks ONE side's own
active-turn protocol — see PRD-02 "Architecture decisions" for why the given
transition table implies WAITING_FOR_OPPONENT is a pure sit-and-wait state
(its only outgoing edge is to COMPUTING_MOVE — i.e. incoming opponent data
never drives a transition here, only starting my own turn does).
"""

from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    WAITING_FOR_OPPONENT = "waiting_for_opponent"
    COMPUTING_MOVE = "computing_move"
    COMMITTING = "committing"
    AWAITING_REVEAL = "awaiting_reveal"
    VERIFYING = "verifying"
    TECHNICAL_LOSS = "technical_loss"


# The canonical transition table, exactly as specified — no edges added or
# removed. Notably COMMITTING and VERIFYING have no TECHNICAL_LOSS edge: in
# this engine that's because both are pure local computation (placeholder in
# stage 2, real hashing in stage 3) with nothing to fail on. COMPUTING_MOVE
# and AWAITING_REVEAL do have one, because AWAITING_REVEAL is where the only
# real network call of the turn happens, and COMPUTING_MOVE's edge exists
# defensively for a future strategy module that could raise.
TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.WAITING_FOR_OPPONENT: frozenset({Phase.COMPUTING_MOVE}),
    Phase.COMPUTING_MOVE: frozenset({Phase.COMMITTING, Phase.TECHNICAL_LOSS}),
    Phase.COMMITTING: frozenset({Phase.AWAITING_REVEAL}),
    Phase.AWAITING_REVEAL: frozenset({Phase.VERIFYING, Phase.TECHNICAL_LOSS}),
    Phase.VERIFYING: frozenset({Phase.WAITING_FOR_OPPONENT}),
    Phase.TECHNICAL_LOSS: frozenset(),
}


class IllegalTransitionError(Exception):
    """Raised immediately on an illegal transition attempt — turns a silent
    runtime deadlock into a loud development-time error, per rule #5."""

    def __init__(self, current: Phase, attempted: Phase):
        allowed = sorted(p.value for p in TRANSITIONS[current])
        super().__init__(
            f"illegal state transition: {current.value} -> {attempted.value} "
            f"(from {current.value}, only {allowed or ['<terminal>']} allowed)"
        )
        self.current = current
        self.attempted = attempted


class StateMachine:
    """Mutable, single-owner turn-protocol tracker. Not part of domain/ —
    this is purely an infra/runtime concern with no game-rule content, and
    unlike domain.MatchState it is not required to be immutable or
    replay-deterministic."""

    def __init__(self, initial: Phase = Phase.WAITING_FOR_OPPONENT):
        self._phase = initial
        self.history: list[Phase] = [initial]

    @property
    def phase(self) -> Phase:
        return self._phase

    def transition(self, target: Phase) -> None:
        if target not in TRANSITIONS[self._phase]:
            raise IllegalTransitionError(self._phase, target)
        self._phase = target
        self.history.append(target)

    def is_terminal(self) -> bool:
        return not TRANSITIONS[self._phase]
