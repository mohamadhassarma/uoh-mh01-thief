"""PRD-05 section B: an evasive thief brain built around trail-breaking,
not distance-maximising.

Survival (35 steps) is the win condition, not distance from the believed
police position — that figure is only a proxy, and PRD-05 is explicit that
pure distance-maximising is naive: a long straight run is exactly what lets
the police's own containment brain sharpen its hotspot and box the thief
in early. `EvasiveThiefBrain` tracks its own recent direction streak and
FORCES a change once it has run the same way for `_STREAK_BREAK_LIMIT`
turns, regardless of how "productive" continuing looks — the trail-breaking
PRD-05 asks for, made concrete and measurable rather than left as an
intuition. Candidate moves are also scored by post-move reachable area
(`board_metrics.reachable_area`), so it does not run itself into a
forming, half-built wall it could see coming.

Hint deception (PRD-05 section C) is tied to threat, not constant: this
brain only *considers* lying about its region when its own belief says
police is close — deception is cheapest to justify exactly when a
misdirected pursuer costs the police the most ground.

MEASURED, not assumed — and the first measurement was actively wrong, for a
confirmed reason worth recording. Sweeping `_LIE_PROBABILITY` in
{0.0, 0.5, 1.0} against `ContainmentPoliceBrain` originally gave police
argmax accuracy going UP as lying went up (backwards). Root cause, confirmed
by inspection then fixed, not just hypothesised: `BrainBase` had ONE shared
`random.Random` stream for movement AND hints. A lie decision consumes a
different number of draws than telling the truth (an extra `rng.choice` for
the decoy region), so changing `_LIE_PROBABILITY` silently shifted the RNG
stream feeding EVERY later movement roll that sub-game — the sweep was
comparing different SEQUENCES OF MOVES, not different hint policies. Fixed
by giving `BrainBase` a separate `self.hint_rng`, seeded once off `self.rng`
at construction so hint decisions never perturb movement (see
`brain_base.py`). Re-measured after the fix, 200 seeds: argmax-within-1/-2
now moves the EXPECTED direction as lying increases — 28.6%/56.9% (never
lie) -> 28.1%/56.5% (0.5) -> 28.0%/56.0% (always lie, under threat) — a
real but small suppression effect. Police win rate is statistically flat
across all three (46.0% / 46.5% / 46.0%): at `hints.
DEFAULT_HINT_TRUST_WEIGHT`'s deliberately modest 0.15, deception measurably
softens the TARGETED metric (belief accuracy) without being large enough to
move the metric that actually decides the game. Kept at 0.5, not 0.0: win
rate does not favour 0.0, and 0.5 keeps the small, real, correctly-signed
suppression effect. See PRD-05 "Which ideas failed and why" for the full
trace, including the original (wrong) numbers.
"""

from __future__ import annotations

from .board import Direction
from .board_metrics import best_local_hotspot, manhattan_distance, reachable_area
from .brain_base import BrainBase
from .hints import generate_hint
from .match import Action, MoveAction
from .own_state import OwnGameState
from .rules import destination_of, legal_moves
from .state import Side

_HOTSPOT_RADIUS = 2
_SAFE_DISTANCE = 4  # PRD-05's own "within 2 cells" figure, doubled for a safety margin
_STREAK_BREAK_LIMIT = 3
_LIE_PROBABILITY = 0.5  # only consulted when under threat — see module docstring


class EvasiveThiefBrain(BrainBase):
    def __init__(self, rng=None):
        super().__init__(rng)
        self._last_direction: Direction | None = None
        self._streak = 0

    def _pick_move(self, obs: OwnGameState, side: Side) -> MoveAction:
        hotspot, _mass = best_local_hotspot(self.belief, obs.board, _HOTSPOT_RADIUS)
        under_threat = manhattan_distance(obs.own_pos, hotspot) <= _SAFE_DISTANCE
        options = list(legal_moves(obs.board, obs.own_pos, obs.config.movement))

        must_break = self._streak >= _STREAK_BREAK_LIMIT
        candidates = [d for d in options if d != self._last_direction] if must_break and len(options) > 1 else options

        def score(direction: Direction) -> float:
            dest = destination_of(obs.own_pos, direction)
            safety = manhattan_distance(dest, hotspot) if under_threat else 0
            mobility = reachable_area(obs.board, dest, obs.config.movement)
            return safety * 2.0 + mobility * 0.1 + self.rng.random() * 0.5

        chosen = max(candidates, key=score)
        self._streak = self._streak + 1 if chosen == self._last_direction else 1
        self._last_direction = chosen
        return MoveAction(chosen)

    def _generate_hint(self, obs: OwnGameState, side: Side, action: Action) -> tuple[str, bool]:
        hotspot, _mass = best_local_hotspot(self.belief, obs.board, _HOTSPOT_RADIUS)
        under_threat = manhattan_distance(obs.own_pos, hotspot) <= _SAFE_DISTANCE
        tell_truth = not (under_threat and self.hint_rng.random() < _LIE_PROBABILITY)
        return generate_hint(obs.own_pos, obs.board.grid_size, tell_truth=tell_truth, rng=self.hint_rng)
