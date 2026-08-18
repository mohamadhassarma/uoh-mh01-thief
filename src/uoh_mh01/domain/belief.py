"""The probabilistic belief map over the opponent's hidden position (PRD-04).

Fed by the opponent's own transmitted scent field (domain/scent.py) each
turn. Two invariants are structural, not just usually-true:

- **Never on a barrier or off-board.** `reachable_cells` is recomputed
  against the CURRENT board every call (barriers appear mid-match), and
  every belief-producing function in this module renormalizes over exactly
  that set — a cell that is not reachable can never carry mass, by
  construction, not by convention.
- **Always a valid probability distribution.** Non-negative, sums to 1 over
  the reachable set (or is the uniform distribution if a caller manages to
  hand in an all-zero map, which cannot happen from this module's own
  functions but must not crash if it ever does).

`decay_confidence`'s blend-toward-uniform is this engine's OWN design
choice, not a book-mandated formula: App F fixes the physical scent field's
decay rate (ch.4) but says nothing about how confidence in a *belief*
should erode absent new observations. Without some such regularization a
cell driven to exactly zero by one observation could never recover even if
the opponent later moves back through it — a plain likelihood-multiply
Bayesian update has no forgetting term on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .board import Board, Position

BeliefMap = dict[Position, float]

# Both constants are this project's own tuning choice (see module
# docstring) — not values fixed anywhere in App F.
_CONFIDENCE_BLEND = 0.05  # fraction of mass pulled toward uniform each update
_LIKELIHOOD_FLOOR = 0.01  # keeps an unscented reachable cell from being ruled out outright


def reachable_cells(board: Board) -> tuple[Position, ...]:
    return tuple(
        Position(r, c)
        for r in range(board.grid_size)
        for c in range(board.grid_size)
        if not board.is_barrier(Position(r, c))
    )


def _renormalize(masses: Mapping[Position, float], reachable: tuple[Position, ...]) -> BeliefMap:
    total = sum(masses.get(pos, 0.0) for pos in reachable)
    if total <= 0.0:
        uniform = 1.0 / len(reachable)
        return dict.fromkeys(reachable, uniform)
    return {pos: masses.get(pos, 0.0) / total for pos in reachable}


def initial_belief(board: Board) -> BeliefMap:
    """Uniform over every reachable cell — no observation has arrived yet,
    so no cell is preferred over any other."""
    reachable = reachable_cells(board)
    uniform = 1.0 / len(reachable)
    return dict.fromkeys(reachable, uniform)


def decay_confidence(belief: BeliefMap, board: Board, blend: float = _CONFIDENCE_BLEND) -> BeliefMap:
    """Erode confidence toward uniform in the absence of a fresh
    observation this turn — see module docstring."""
    reachable = reachable_cells(board)
    uniform = 1.0 / len(reachable)
    blended = {pos: (1.0 - blend) * belief.get(pos, 0.0) + blend * uniform for pos in reachable}
    return _renormalize(blended, reachable)


def update_from_scent(belief: BeliefMap, scent: Mapping[Position, float], board: Board) -> BeliefMap:
    """Fold one turn's worth of the opponent's OWN transmitted scent field
    into the belief map: confidence first erodes toward uniform (this
    turn's motion uncertainty — see `decay_confidence`), then the prior is
    re-weighted by scent intensity (a cell with no reported scent still
    gets `_LIKELIHOOD_FLOOR`, never zero, so it stays reachable in a future
    update rather than being permanently excluded)."""
    prior = decay_confidence(belief, board)
    reachable = reachable_cells(board)
    weighted = {pos: prior[pos] * (scent.get(pos, 0.0) + _LIKELIHOOD_FLOOR) for pos in reachable}
    return _renormalize(weighted, reachable)


@dataclass(frozen=True)
class HintClaim:
    """One opponent-supplied natural-language hint, already reduced to a
    trust weight by the CALLER — this module never assigns one itself.

    `text` is kept for the audit trail (it is part of the sealed record);
    `weight` in [0, 1] is how much a future strategy chooses to believe it —
    0 for "ignore entirely" (the safe default, since the book explicitly
    permits deception and a hint is a claim, not evidence), up to 1 for
    "treat as fully reliable". A negative-leaning strategy that suspects a
    bluff is free to invert the claimed cell instead of discounting it —
    that decision logic is stage 5's, not this module's.
    """

    text: str
    weight: float = 0.0


def apply_hint(belief: BeliefMap, claim: HintClaim, claimed_cell: Position | None, board: Board) -> BeliefMap:
    """Nudge belief toward (or, at `weight` supplied negative by a caller
    that has already decided to invert it, away from) `claimed_cell` by
    `claim.weight`. Decoding `text` into `claimed_cell` at all is stage 5's
    hint-parsing job (PRD-04 explicitly excludes it here) — this function's
    only responsibility is folding an ALREADY-INTERPRETED claim in with
    exactly the trust the caller assigned it, never more.

    `claimed_cell=None` or `claim.weight==0` is a no-op: the default posture
    for an unparsed or fully-distrusted hint is to leave belief untouched,
    not to silently treat silence as truth.
    """
    if claimed_cell is None or claim.weight == 0.0 or claimed_cell not in belief:
        return belief
    reachable = reachable_cells(board)
    w = max(-1.0, min(1.0, claim.weight))
    bumped = {pos: belief[pos] * (1.0 + w) if pos == claimed_cell else belief[pos] for pos in reachable}
    return _renormalize(bumped, reachable)
