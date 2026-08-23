"""Small pure helpers for turn_receiver.py, split out purely to keep that file
under the project's ~150-line budget.

`sender_position()`, `counter_mismatch()` and `early_response()` are all GONE.
The first two served the mirrored model. The third short-circuited a tool
handler with a cached response — meaningless now that every tool is ack-only
and returns `{"ok": True}`; duplicate suppression moved to the point of
PROCESSING instead (`_seen_commits` in turn_receiver).
"""

from __future__ import annotations

from ..domain import belief as belief_module
from ..domain.belief import BeliefMap
from ..domain.board import Board
from ..domain.hints import fuse_hint_into_belief
from ..domain.scent import deserialize_field
from .turn_message import TurnMessage


def absorb_opponent_signals(belief: BeliefMap, board: Board, message: TurnMessage) -> BeliefMap:
    """PRD-04/PRD-05: fold the opponent's own trail and hint (never its true
    position — it is not sent) into belief. A hint's truthfulness is
    unverifiable live, so it always gets the same fixed, modest trust weight
    (domain.hints.DEFAULT_HINT_TRUST_WEIGHT)."""
    if message.smell_grid:
        belief = belief_module.update_from_scent(belief, deserialize_field(message.smell_grid), board)
    if message.hint:
        belief = fuse_hint_into_belief(belief, board, message.hint)
    return belief
