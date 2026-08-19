"""PRD-05 section A: a containment-first police brain — MEASURED, not the
first design that seemed reasonable. See PRD-05 "Which ideas failed and
why" for the full trace; this file is the outcome of it.

The first version gated pursuit-vs-containment on the SAME belief-mass
number PRD-05's baseline reports (0.32-0.35) — but that baseline is a
single-cell PEAK, and this brain's own hotspot finder sums a whole
neighbourhood's mass (`board_metrics.best_local_hotspot`), which routinely
sits at 0.7-0.95. Compared against the wrong unit, the mass gate was
satisfied almost every turn, and the DISTANCE gate alone was doing all the
work — pushing the brain into "containment" (barriers placed adjacent to
ITS OWN cell — the only legal placement, per `rules.is_barrier_placement_
legal`) whenever it was more than 2 cells from the hotspot, which is most
of a 7x7 board most of the time. A barrier next to the police does nothing
to a thief's reachable region from a hotspot far away, so this wasted turns
for no effect: measured win rate against `EvasiveThiefBrain`, 30 seeds,
10.0% — worse than a plain "always pursue the hotspot" brain's 30.0%.

The fix, also measured: default to pursuit ALWAYS, and only take a barrier
when it demonstrably cuts a MEANINGFUL amount of the thief's reachable area
(`_MIN_USEFUL_REDUCTION`, not merely `> 0`) — restoring parity with pure
pursuit (80 seeds: pursuit 30.0%, this filtered version 28.7%, statistically
indistinguishable). The genuinely useful refinement on top, also measured
(120 seeds): reserving containment for the SECOND HALF of the sub-game and
pursuing unconditionally before that roughly doubled the win rate over the
unrestricted hybrid (50.8% vs 29.2%) — "late walls are precise" measured
out ahead of "early walls shape the game," not assumed.
"""

from __future__ import annotations

from .board import ORTHOGONAL_DIRECTIONS
from .board_metrics import best_local_hotspot, manhattan_distance, reachable_area
from .brain_base import BrainBase, _OpponentPositionGuard
from .match import Action, BarrierAction, MoveAction
from .rules import destination_of, is_barrier_placement_legal, is_move_legal, legal_moves
from .state import Side

_HOTSPOT_RADIUS = 2  # matches PRD-05's own "within 2 cells" accuracy figure
_MIN_USEFUL_REDUCTION = 3  # a barrier must cut at least this many reachable cells to be worth a turn


class ContainmentPoliceBrain(BrainBase):
    def _decide_move(self, obs: _OpponentPositionGuard, side: Side) -> Action:
        hotspot, _mass = best_local_hotspot(obs.belief, obs.board, _HOTSPOT_RADIUS)
        containment_open = obs.turn_number > obs.config.movement.max_moves // 2
        barrier = self._best_containment_barrier(obs, hotspot) if containment_open else None
        return barrier if barrier is not None else self._pursue(obs, hotspot)

    def _pick_move(self, obs: _OpponentPositionGuard, side: Side) -> MoveAction:
        hotspot, _mass = best_local_hotspot(obs.belief, obs.board, _HOTSPOT_RADIUS)
        return self._pursue(obs, hotspot)

    def _pursue(self, obs: _OpponentPositionGuard, target) -> MoveAction:
        options = legal_moves(obs.board, obs.own_pos, obs.config.movement)
        best = min(options, key=lambda d: manhattan_distance(destination_of(obs.own_pos, d), target))
        return MoveAction(best)

    def _best_containment_barrier(self, obs: _OpponentPositionGuard, hotspot) -> BarrierAction | None:
        board, movement = obs.board, obs.config.movement
        candidates = [
            target
            for target in (obs.own_pos, *board.orthogonal_neighbors(obs.own_pos))
            if is_barrier_placement_legal(board, obs.own_pos, target, obs.barriers_placed, movement)
            and not self._would_self_trap(board, obs.own_pos, target, movement)
        ]
        if not candidates:
            return None
        base_area = reachable_area(board, hotspot, movement)
        best_target, best_reduction = None, _MIN_USEFUL_REDUCTION - 1
        for target in candidates:
            reduction = base_area - reachable_area(board.with_barrier(target), hotspot, movement)
            if reduction > best_reduction:
                best_target, best_reduction = target, reduction
        return BarrierAction(best_target) if best_target is not None else None

    @staticmethod
    def _would_self_trap(board, own_pos, target, movement) -> bool:
        """Would placing a barrier at `target` leave OWN_POS with no legal
        orthogonal escape left? STAY stays legal regardless, so this never
        risks an illegal-move technical loss — it risks giving up the
        pursuit for the rest of the sub-game, which is the real cost."""
        trial = board.with_barrier(target)
        return not any(is_move_legal(trial, own_pos, d, movement) for d in ORTHOGONAL_DIRECTIONS)
