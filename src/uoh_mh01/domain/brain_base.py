"""PRD-05: `BrainBase`, the pluggable move-selection + hint interface both
brains extend, and the structural zero-trust guard every brain call goes
through.

`_pick_move(observation, side)` is the core movement decision (both sides).
`_decide_move(observation, side)` is the full decision INCLUDING whether to
place a barrier — police-only in the shipped brains, but not restricted
here, since a future police-side subclass is the only one with a legal
reason to return a `BarrierAction` at all (`rules.is_barrier_placement_legal`
already refuses a thief's attempt).

THE ONE INVARIANT (PRD-05): the move is chosen by pure Python — nothing in
this module or its subclasses ever calls an LLM to decide movement. A
`generate_hint` override may eventually be told to phone a language model
for the TEXT of a hint (not in this stage — the shipped `template` provider
is zero-tokens, per PRD-05 section C), but the returned `Action` from
`_pick_move`/`_decide_move` must never depend on one.
"""

from __future__ import annotations

import importlib
import random

from .belief import BeliefMap
from .board import Board, Position
from .config import GameConfig
from .hints import generate_hint
from .match import Action, MoveAction, Strategy
from .rules import legal_moves
from .state import MatchState, Side
from .strategies import make_random_strategy


class _OpponentPositionGuard:
    """Wraps a MatchState so code that only ever receives THIS object —
    never the raw MatchState — cannot read the opponent's true position,
    structurally rather than by convention: the forbidden attribute raises
    on access instead of merely being undocumented. Every other field
    (board, config, turn_number, barrier counts, ...) passes through
    unchanged, including the OWN side's position field.
    """

    def __init__(self, state: MatchState, side: Side, belief: BeliefMap):
        self._state = state
        self._side = side
        self.belief = belief

    def __getattr__(self, name: str):
        forbidden = "thief_pos" if self._side is Side.POLICE else "cop_pos"
        if name == forbidden:
            raise PermissionError(
                f"a {self._side.value} brain attempted to read '{name}' — the true opponent "
                "position is never available to a brain (Zero-Trust, PRD-05)"
            )
        return getattr(self._state, name)

    @property
    def own_pos(self) -> Position:
        return self._state.cop_pos if self._side is Side.POLICE else self._state.thief_pos

    @property
    def board(self) -> Board:
        return self._state.board

    @property
    def config(self) -> GameConfig:
        return self._state.config


class BrainBase:
    """Base class for an injectable strategy. Instances are directly usable
    as the `Strategy` callable `PeerRuntime`/`run_match` already expect
    (`__call__(state, side) -> Action`) — no change to that type was
    needed.

    `self.belief` is set by the CALLER (orchestrator/harness) immediately
    before each invocation, not passed as a call argument — this keeps the
    `Strategy` signature exactly `Callable[[MatchState, Side], Action]`,
    so every pre-existing 2-argument lambda-based test keeps working
    unchanged. Callers detect a brain via `hasattr(strategy, "belief")`.
    """

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        # A SEPARATE stream for hint decisions, seeded once (one single draw
        # off `self.rng`) rather than reused — stage-5 close-out found that
        # sharing one RNG between movement and hints confounds any
        # measurement of hint effects: a hint decision that conditionally
        # consumes an extra draw (e.g. "lie or not", then "which decoy")
        # shifts EVERY subsequent movement roll for the rest of the game,
        # so comparing two hint policies under a shared stream is really
        # comparing two different sequences of MOVES, not just two hint
        # policies. See PRD-05 "Which ideas failed and why".
        self.hint_rng = random.Random(self.rng.random())
        self.belief: BeliefMap = {}
        self.last_hint: tuple[str, bool] = ("", True)

    def __call__(self, state: MatchState, side: Side) -> Action:
        obs = _OpponentPositionGuard(state, side, self.belief)
        action = self._decide_move(obs, side) if side is Side.POLICE else self._pick_move(obs, side)
        self.last_hint = self._generate_hint(obs, side, action)
        return action

    def _decide_move(self, obs: _OpponentPositionGuard, side: Side) -> Action:
        """Default: no barrier logic — just move. Overridden by police
        brains that want to consider `BarrierAction` too."""
        return self._pick_move(obs, side)

    def _pick_move(self, obs: _OpponentPositionGuard, side: Side) -> MoveAction:
        """Default fallback: uniformly random among legal moves."""
        options = legal_moves(obs.board, obs.own_pos, obs.config.movement)
        return MoveAction(self.rng.choice(options))

    def _generate_hint(self, obs: _OpponentPositionGuard, side: Side, action: Action) -> tuple[str, bool]:
        """Default: always truthful, region-based (`domain.hints`).
        Overridden by brains that want to deceive. Uses `self.hint_rng`,
        never `self.rng` — see `__init__`'s docstring."""
        return generate_hint(obs.own_pos, obs.board.grid_size, tell_truth=True, rng=self.hint_rng)


def load_brain_class(dotted_path: str) -> type[BrainBase]:
    """Resolve `"package.module:ClassName"` into a `BrainBase` subclass —
    the config-injection mechanism `[strategy] police_class`/`thief_class`
    points at (PeerConfig, PRD-05)."""
    if ":" not in dotted_path:
        raise ValueError(f"strategy class path must be 'package.module:ClassName', got {dotted_path!r}")
    module_name, class_name = dotted_path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None or not (isinstance(cls, type) and issubclass(cls, BrainBase)):
        raise ValueError(f"{dotted_path!r} does not resolve to a BrainBase subclass")
    return cls


def resolve_strategy(dotted_path: str | None, seed: int | str | None) -> Strategy:
    """Picks a brain (or the shipped random baseline) for ONE role. Callers
    in a role-alternating series (infra/series_subgame.py) MUST call this
    fresh for every sub-game rather than reuse one instance across the whole
    series: a role-specific brain (e.g. `ContainmentPoliceBrain`) is only
    correct for the role it was designed for, and per-brain state (e.g. a
    thief's direction streak) must not leak across a sub-game boundary."""
    if dotted_path is None:
        return make_random_strategy(random.Random(seed))
    return load_brain_class(dotted_path)(random.Random(seed))
