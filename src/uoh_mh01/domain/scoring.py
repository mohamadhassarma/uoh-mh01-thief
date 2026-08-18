"""Terminal condition -> (police_score, thief_score).

Deliberately does NOT decide *when* a terminal condition fires — that is
match.py's job. This module only knows the scoring table.
"""

from __future__ import annotations

from enum import Enum

from .config import ScoringConfig
from .state import Side


class TerminalCondition(str, Enum):
    CAPTURE_LANDING = "capture_landing"
    CAPTURE_BARRIER = "capture_barrier"
    CAPTURE_ENTRAPMENT = "capture_entrapment"
    SURVIVAL = "survival"
    TECHNICAL_LOSS = "technical_loss"
    TIE = "tie"


_CAPTURE_CONDITIONS = frozenset(
    {TerminalCondition.CAPTURE_LANDING, TerminalCondition.CAPTURE_BARRIER, TerminalCondition.CAPTURE_ENTRAPMENT}
)


def score_for(
    condition: TerminalCondition,
    scoring: ScoringConfig,
    offending_side: Side | None = None,
) -> tuple[int, int]:
    """Return (police_score, thief_score) for a terminal condition.

    `offending_side` is required for TECHNICAL_LOSS (kept for logging/report
    purposes — the score itself is symmetric, see below) and ignored otherwise.
    """
    if condition in _CAPTURE_CONDITIONS:
        return (scoring.capture_cop, scoring.capture_thief)

    if condition is TerminalCondition.SURVIVAL:
        return (scoring.survival_cop, scoring.survival_thief)

    if condition is TerminalCondition.TECHNICAL_LOSS:
        if offending_side is None:
            raise ValueError("TECHNICAL_LOSS requires offending_side")
        # config/game.json only defines a single scalar `technical_loss`
        # value (0), and TODO.md is explicit that this means a 0/0 pair for
        # both sides — not just the offending side. See PRD-01.
        return (scoring.technical_loss, scoring.technical_loss)

    if condition is TerminalCondition.TIE:
        return (scoring.tie_score, scoring.tie_score)

    raise AssertionError(f"unhandled TerminalCondition: {condition}")  # pragma: no cover
