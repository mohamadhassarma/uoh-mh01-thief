"""Small pure helpers for turn_receiver.py, split out purely to keep that
file under the project's ~150-line budget.
"""

from __future__ import annotations

from typing import Any

from ..domain.state import MatchState, Side
from .protocol import MoveRequest
from .protocol_response import MoveResponse


def sender_position(state: MatchState, sender: Side):
    return state.cop_pos if sender is Side.POLICE else state.thief_pos


def early_response(runtime: Any, request: MoveRequest) -> MoveResponse | None:
    """A response to short-circuit `receive_opponent_move` with, BEFORE any
    other handling — `None` means "no early answer, proceed normally."

    - A retried commit gets back the SAME answer I gave the first time,
      regardless of what my state looks like now — this is what makes a
      lost/delayed RESPONSE (not a lost request) harmless. See
      orchestrator.py's `_replayed_responses` docstring.
    - If my side has already finished this sub-game (e.g. a timeout-based
      technical loss I already self-declared), a genuinely NEW message
      arriving after that point is rejected outright rather than silently
      overwriting an outcome already returned to my own caller. See PRD-03
      "Symmetric timeout outcomes"."""
    if request.commit and request.commit in runtime._replayed_responses:
        return runtime._replayed_responses[request.commit]
    if runtime.outcome is not None:
        return MoveResponse(accepted=False, reason="my side has already finished this sub-game")
    return None


def counter_mismatch(request: MoveRequest, expected: MatchState) -> str | None:
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
