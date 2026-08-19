"""Test-only brains for the real-CLI role-alternation conformance test
(test_cli_role_alternation.py) — deliberately simple and DISTINGUISHABLE by
which direction they move, so a role-alternating series played over real
subprocesses can prove from the log artifacts alone which brain actually
ran each sub-game, not merely that some brain did.
"""

from __future__ import annotations

from uoh_mh01.domain.board import Direction
from uoh_mh01.domain.brain_base import BrainBase, _OpponentPositionGuard
from uoh_mh01.domain.match import MoveAction
from uoh_mh01.domain.rules import legal_moves
from uoh_mh01.domain.state import Side


class AlwaysNorthBrain(BrainBase):
    """Marker brain: always moves N (STAY if N happens to be illegal)."""

    def _pick_move(self, obs: _OpponentPositionGuard, side: Side) -> MoveAction:
        options = legal_moves(obs.board, obs.own_pos, obs.config.movement)
        return MoveAction(Direction.N if Direction.N in options else Direction.STAY)


class AlwaysSouthBrain(BrainBase):
    """Marker brain: always moves S (STAY if S happens to be illegal)."""

    def _pick_move(self, obs: _OpponentPositionGuard, side: Side) -> MoveAction:
        options = legal_moves(obs.board, obs.own_pos, obs.config.movement)
        return MoveAction(Direction.S if Direction.S in options else Direction.STAY)
