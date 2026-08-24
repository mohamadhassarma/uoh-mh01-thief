"""Terminal condition -> (police_score, thief_score), and the string that
condition is allowed to appear as outside this process.

Deliberately does NOT decide *when* a terminal condition fires — that is
match.py's job. This module only knows the scoring table and the projection.

TWO VOCABULARIES, ON PURPOSE. `TerminalCondition` is OURS: it distinguishes
the three ways a capture can happen, which is a real distinction and matches
the three families the interop SPEC names (SPEC.md:153-190: co-location,
rule 46, rule 47). The LEAGUE has one word for all three. SPEC.md says all
three "settle CAPTURE" and puts the distinction in `claim_response`, not in
the result string; the reference emits a single `"capture"`
(ref_impl domain/scoring.py:13, peer/runtime.py:122/:127) and its
`score_subgame` treats anything that is not capture/survival as a technical
loss worth 0/0 to BOTH sides.

So we kept the taxonomy and stopped exporting it. `to_wire_result` is the one
door: nothing that leaves this process may use `.value` on a capture.

WHAT THIS COST BEFORE IT WAS FIXED. We emitted `"capture_landing"` as
`result_claim` and as `summary.result` for six sub-games against a live
opponent. A conforming peer scores that 0/0 while we scored it 20/5 — two
honest peers describing one sub-game two ways, which is the contradictory
report App. E rule 35 zeroes BOTH teams for. `docs/WIRE.md:212` had documented
the correct vocabulary all along; only the code disagreed.
"""

from __future__ import annotations

import logging
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

# The league's word for every capture, whichever family it was.
WIRE_CAPTURE = "capture"

# What WE used to emit. Still accepted on the way IN - from our own artifacts
# written before this was fixed, and from any peer that copied the mistake -
# but never produced on the way out again.
LEGACY_CAPTURE_RESULTS = frozenset(condition.value for condition in _CAPTURE_CONDITIONS)

logger = logging.getLogger(__name__)


def to_wire_result(condition: TerminalCondition) -> str:
    """The result string for the wire, the log artifact and the report.

    The ONLY sanctioned way to turn a TerminalCondition into an outward-facing
    string. Using `.value` instead is what put `capture_landing` in front of a
    real opponent, so `test_wire_result_conformance.py` fails the build if any
    emitting path goes back to it.
    """
    return WIRE_CAPTURE if condition in _CAPTURE_CONDITIONS else condition.value


# Everything a result string is allowed to be on the way out. `capture` and
# `survival` are the league's (ref_impl domain/scoring.py:13-14); the other two
# are ours and are recorded in docs/WIRE.md as an open divergence - they score
# 0/0 on either reading, so they are a labelling question, not a scoring one,
# and neither has ever actually been emitted in a real series.
WIRE_RESULTS = frozenset({WIRE_CAPTURE, "survival", "technical_loss", "tie"})


def check_result_vocabulary(result: str, where: str) -> None:
    """Warn - never raise - if a non-conforming result string is being emitted.

    A guard at the door rather than a rule in a docstring. Had this existed,
    six `capture_landing` reveals to a live opponent would each have logged a
    warning instead of passing silently.

    Deliberately NOT an exception: a wrong label on a sub-game that was really
    played is a bad outcome, and forfeiting that sub-game to a raise mid-series
    is a worse one.
    """
    if result not in WIRE_RESULTS:
        logger.warning(
            "emitting non-league result string %r via %s - the league's vocabulary is %s "
            "(see domain/scoring.to_wire_result)",
            result, where, sorted(WIRE_RESULTS),
        )


def is_capture_result(result: str) -> bool:
    """Both vocabularies, because reading is where tolerance belongs."""
    return result == WIRE_CAPTURE or result in LEGACY_CAPTURE_RESULTS


def score_for_result(
    result: str, scoring: ScoringConfig, offending_side: Side | None = None
) -> tuple[int, int]:
    """Score a result STRING - as read from an artifact or off the wire.

    Emit strictly, receive tolerantly. `"capture"` and all three of our old
    names score identically, because they describe the same event.

    An unrecognised string scores 0/0 rather than raising, matching the
    reference's own rule that anything which is not capture/survival is a
    technical loss (ref_impl domain/scoring.py:25-31). It is logged, loudly,
    because the likeliest cause is another peer exporting ITS internal
    vocabulary - exactly the bug this function exists because of. Raising
    instead would mean one unknown string from an opponent could stop us
    reporting a series we actually played.
    """
    if is_capture_result(result):
        return (scoring.capture_cop, scoring.capture_thief)
    try:
        condition = TerminalCondition(result)
    except ValueError:
        logger.warning(
            "unrecognised result string %r scored as a technical loss (0/0) - "
            "if this came from an opponent, their result vocabulary differs from the league's",
            result,
        )
        return (scoring.technical_loss, scoring.technical_loss)
    return score_for(condition, scoring, offending_side=offending_side)


def score_for(
    condition: TerminalCondition,
    scoring: ScoringConfig,
    offending_side: Side | None = None,
) -> tuple[int, int]:
    """Return (police_score, thief_score) for a terminal condition.

    `offending_side` is optional context for TECHNICAL_LOSS, kept only for
    logging/report purposes — the score itself is symmetric (see below) and
    does not depend on it. It is `None` both for engine-internal technical
    losses with no single guilty party (e.g. a wire-protocol divergence
    detected by the counter check — see PRD-02 "Stage 2 corrections") and,
    naturally, ignored for every other condition.
    """
    if condition in _CAPTURE_CONDITIONS:
        return (scoring.capture_cop, scoring.capture_thief)

    if condition is TerminalCondition.SURVIVAL:
        return (scoring.survival_cop, scoring.survival_thief)

    if condition is TerminalCondition.TECHNICAL_LOSS:
        # config/game.json only defines a single scalar `technical_loss`
        # value (0), and TODO.md is explicit that this means a 0/0 pair for
        # both sides — not just the offending side. See PRD-01.
        return (scoring.technical_loss, scoring.technical_loss)

    if condition is TerminalCondition.TIE:
        return (scoring.tie_score, scoring.tie_score)

    raise AssertionError(f"unhandled TerminalCondition: {condition}")  # pragma: no cover
