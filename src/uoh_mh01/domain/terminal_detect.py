"""Pure, side-independent terminal-condition detection.

Both the side that just acted (building a CLAIM) and the side re-verifying an
opponent's claim (independently checking it) call the SAME functions against
their OWN local MatchState. Neither ever trusts a claimed condition without
recomputing it from scratch — see PRD-02 "Terminal conditions must be
declared, never inferred from silence".
"""

from __future__ import annotations

from dataclasses import dataclass

from .rules import is_thief_trapped
from .scoring import TerminalCondition
from .state import ActionType, MatchState, Side, actions_taken_by

# Wire-level marker for "max_moves ceiling reached, no other condition fired".
# Not a TerminalCondition member on purpose: the rulebook does not define a
# score for this case (see domain.match.UndefinedOutcomeError), so it must
# never be representable as a normal, scoreable condition.
UNDEFINED_CEILING = "undefined_ceiling"


@dataclass(frozen=True)
class DetectedTerminal:
    """One side's own claim/verdict about whether the match just ended.

    `condition` is a TerminalCondition value, or the UNDEFINED_CEILING
    marker string for the unscoreable max_moves case. `offending_side` is
    only meaningful for conditions that have one (none of the ones detected
    here do — capture/survival/entrapment/ceiling are not technical losses).
    """

    condition: str
    offending_side: Side | None = None


def detect_from_last_action(state: MatchState) -> DetectedTerminal | None:
    """Did the LAST entry in state.move_log end the match? Both the side that
    made the move and the side that just applied it (its own or received)
    derive this identically from the same action — that agreement is exactly
    what makes it safe to use as the basis of a claim that still goes through
    declare/confirm rather than being trusted outright."""
    if not state.move_log:
        return None
    last = state.move_log[-1]
    if last.capture_triggered:
        condition = (
            TerminalCondition.CAPTURE_BARRIER if last.action_type is ActionType.BARRIER else TerminalCondition.CAPTURE_LANDING
        )
        return DetectedTerminal(condition.value)
    if last.actor is Side.THIEF and state.thief_survived_steps >= state.config.movement.survival_threshold:
        return DetectedTerminal(TerminalCondition.SURVIVAL.value)
    return None


# ----------------------------------------------------------------------------
# PEER PATH — the claim protocol. No shared board exists here, so nothing below
# ever inspects an opponent position; a terminal condition is either CLAIMED
# from my own state or CONFIRMED by the opponent's honest answer.
#
# GATED OFF on this path, deliberately: capture-by-entrapment and
# capture-by-barrier. Both are real book rules (§3.4) and both stay ACTIVE in
# the simulator above, but neither can be detected by the side it would
# benefit — only the thief can see that it is surrounded, and only the thief
# knows a barrier landed on its own cell. Emitting either unilaterally would
# be an asymmetric terminal the opponent cannot independently derive, which is
# exactly the desync App. E rule 35 zeroes both teams for. They resolve here
# through the ordinary capture claim instead. See PRD-01 "Open questions".
# ----------------------------------------------------------------------------


def peer_capture_claim(own, action) -> list[int] | None:
    """The police's "I claim you are at [r,c]" — its OWN cell after a move.

    Police-only and MOVE-only, matching the reference
    (`ref_impl/src/police_thief/peer/turn_sender.py:46-49`): a barrier
    placement never carries a capture claim.
    """
    from .match import MoveAction

    if own.role is not Side.POLICE or not isinstance(action, MoveAction):
        return None
    return [own.own_pos.row, own.own_pos.col]


def peer_win_claim(own) -> dict | None:
    """The thief's `{"type": "survival"}` once it has taken enough of its OWN
    steps — self-evident from its own state, and provable at audit."""
    if own.role is not Side.THIEF:
        return None
    if own.survived_steps >= own.config.movement.survival_threshold:
        return {"type": "survival"}
    return None


def answer_capture_claim(own, claim: list[int]) -> dict:
    """The honest answer to a capture claim. Lying is pointless: the audit
    reveals the sealed true position and a false answer forfeits the game
    (`ref_impl/src/police_thief/domain/rules.py:26-32`)."""
    caught = [own.own_pos.row, own.own_pos.col] == list(claim)
    return {"claim": list(claim), "caught": caught}


def peer_ceiling_reached(own) -> bool:
    """My own max_moves ceiling — the one pre-turn self-check that survives on
    the peer path, since it reads nothing but my own action count."""
    return own.step_number >= own.config.movement.max_moves


def detect_pre_turn(state: MatchState, role: Side) -> DetectedTerminal | None:
    """Checked before `role` acts: entrapment (thief only) and the max_moves
    ceiling. Both are self-detected with NO accompanying move — there is
    nothing for the opponent to derive independently except by re-running
    this same check against its own mirrored copy of the state, which is
    exactly why these are the two conditions that most need an explicit
    declare/confirm exchange (see PRD-02 "Open questions" #9, stage-2
    corrections)."""
    movement = state.config.movement
    if role is Side.THIEF and is_thief_trapped(state.board, state.thief_pos, movement):
        return DetectedTerminal(TerminalCondition.CAPTURE_ENTRAPMENT.value)
    if actions_taken_by(state, role) >= movement.max_moves:
        return DetectedTerminal(UNDEFINED_CEILING)
    return None
