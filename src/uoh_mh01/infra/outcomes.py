"""Runtime-level outcome/exception types shared by orchestrator.py and its
turn-handling mixins (turn_sender.py, turn_receiver.py). Kept in their own
module, separate from orchestrator.py, purely to break an import cycle: the
mixins need these types, and orchestrator.py needs the mixins.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.scoring import TerminalCondition
from ..domain.state import Side


class DisputedOutcomeError(Exception):
    """Raised when this side's own independent recomputation of a terminal
    condition disagrees with the opponent's claim, after a declare/confirm
    exchange (or vice versa). Never silently resolved — see PRD-02
    'Stage 2 corrections' B1: both sides log both claims and stop, leaving
    resolution to stage 3's mutual audit rather than inventing one here."""

    def __init__(self, mine: str | None, theirs: str | None):
        super().__init__(f"terminal-condition disagreement: mine={mine!r} theirs={theirs!r}")
        self.mine = mine
        self.theirs = theirs


@dataclass
class MatchOutcome:
    """Only ever constructed for a genuinely resolved, mutually-agreed match.
    An undefined outcome (max_moves ceiling) raises UndefinedOutcomeError; a
    disagreement raises DisputedOutcomeError. Neither is an all-None instance
    of this class — see PRD-01/PRD-02 'Open questions'."""

    terminal_condition: TerminalCondition
    police_score: int
    thief_score: int
    offending_side: Side | None = None

