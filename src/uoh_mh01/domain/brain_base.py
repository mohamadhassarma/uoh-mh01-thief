"""PRD-05: `BrainBase`, the pluggable move-selection + hint interface both
brains extend.

`_pick_move(own, side)` is the core movement decision (both sides).
`_decide_move(own, side)` is the full decision INCLUDING whether to place a
barrier — police-only in the shipped brains, but not restricted here.

THE ONE INVARIANT (PRD-05): the move is chosen by pure Python — nothing in
this module or its subclasses ever calls an LLM to decide movement.

ZERO-TRUST IS NOW STRUCTURAL, NOT GUARDED. A brain is handed an
`OwnGameState` (domain/own_state.py), which has no opponent-position field at
all. This replaces `_OpponentPositionGuard`, which wrapped a state object that
still HELD the opponent's position and blocked exactly one attribute name — it
was defeatable by any transitive path (`state.move_log` carried both
positions, and passed straight through `__getattr__`). A type that lacks the
field cannot leak it.

Callers may pass either an `OwnGameState` (the live peer runtime) or the
simulator's omniscient `MatchState` (domain/match.py, domain/eval_match.py);
the latter is projected through `own_state.own_view()` before any brain code
sees it, so both paths present the identical restricted surface.
"""

from __future__ import annotations

import importlib
import random

from .belief import BeliefMap
from .hints import generate_hint
from .match import Action, MoveAction, Strategy
from .own_state import OwnGameState, own_view
from .rules import legal_moves
from .state import MatchState, Side
from .strategies import make_random_strategy


class BrainBase:
    """Base class for an injectable strategy. Instances are directly usable as
    the `Strategy` callable `PeerRuntime`/`run_match` already expect
    (`__call__(state, side) -> Action`).

    `self.belief` is set by the CALLER (orchestrator/harness) immediately
    before each invocation, not passed as a call argument — this keeps the
    `Strategy` signature exactly `Callable[[state, Side], Action]`, so every
    pre-existing 2-argument lambda-based test keeps working unchanged.
    """

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        # A SEPARATE stream for hint decisions, seeded once off `self.rng`
        # rather than shared with it: a hint decision that conditionally
        # consumes an extra draw would otherwise shift every subsequent
        # movement roll, making any measurement of hint effects a measurement
        # of different move sequences instead. See PRD-05.
        self.hint_rng = random.Random(self.rng.random())
        self.belief: BeliefMap = {}
        self.last_hint: tuple[str, bool] = ("", True)

    def __call__(self, state: OwnGameState | MatchState, side: Side) -> Action:
        own = own_view(state, side) if isinstance(state, MatchState) else state
        action = self._decide_move(own, side) if side is Side.POLICE else self._pick_move(own, side)
        self.last_hint = self._generate_hint(own, side, action)
        return action

    def _decide_move(self, own: OwnGameState, side: Side) -> Action:
        """Default: no barrier logic — just move. Overridden by police brains
        that want to consider `BarrierAction` too."""
        return self._pick_move(own, side)

    def _pick_move(self, own: OwnGameState, side: Side) -> MoveAction:
        """Default fallback: uniformly random among legal moves."""
        options = legal_moves(own.board, own.own_pos, own.config.movement)
        return MoveAction(self.rng.choice(options))

    def _generate_hint(self, own: OwnGameState, side: Side, action: Action) -> tuple[str, bool]:
        """Default: always truthful, region-based (`domain.hints`). Uses
        `self.hint_rng`, never `self.rng` — see `__init__`."""
        return generate_hint(own.own_pos, own.board.grid_size, tell_truth=True, rng=self.hint_rng)


def load_brain_class(dotted_path: str) -> type[BrainBase]:
    """Resolve `"package.module:ClassName"` into a `BrainBase` subclass — the
    config-injection mechanism `[strategy] police_class`/`thief_class` points
    at (PeerConfig, PRD-05)."""
    if ":" not in dotted_path:
        raise ValueError(f"strategy class path must be 'package.module:ClassName', got {dotted_path!r}")
    module_name, class_name = dotted_path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, BrainBase)):
        raise ValueError(f"{dotted_path!r} does not resolve to a BrainBase subclass")
    return cls


def resolve_strategy(dotted_path: str | None, seed: int | str | None) -> Strategy:
    """Picks a brain (or the shipped random baseline) for ONE role. Callers in
    a role-alternating series (infra/series_subgame.py) MUST call this fresh
    for every sub-game: a role-specific brain is only correct for the role it
    was designed for, and per-brain state (e.g. a thief's direction streak)
    must not leak across a sub-game boundary."""
    if dotted_path is None:
        return make_random_strategy(random.Random(seed))
    return load_brain_class(dotted_path)(random.Random(seed))
