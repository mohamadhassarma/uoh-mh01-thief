"""Negotiable house-rule constants, named and documented individually rather
than scattered through match.py's loop or silently baked in. Split out of
match.py purely to keep that file under the project's ~150-line budget;
re-exported from there (`from .house_rules import ...`) so existing
`from .domain.match import FIRST_MOVER` call sites are unaffected.

See PRD-01 "Open questions" for the full rationale on each.
"""

from __future__ import annotations

from .state import Side

# Provisional: rulebook Ch. 10 does not pin down who moves first. Kept as one
# named constant, not scattered through the loop, so it is easy to find and
# renegotiate. See PRD-01 "Open questions". Not book-fixed — PRD-03 (item 10)
# treats this as a negotiable HOUSE RULE, signed into the handshake `terms`
# (shared.terms.terms_from_config) so a mismatched opponent implementation
# refuses to play instead of silently disagreeing on whose turn it is.
FIRST_MOVER: Side = Side.POLICE

# PRD-03 (verified against the book's Table 2 + rules #21/#22, supersedes
# PRD-01's original symmetric-coordinate-overlap reading): capture-by-
# landing requires the POLICE to be the one whose own action produced the
# coordinate overlap — never a passive predicate over either side's move.
# See reducers.apply_move and rules.is_capture_state's docstrings. Also a
# negotiable house rule per PRD-03 item 10, signed into the handshake terms
# for the same reason as FIRST_MOVER above.
CAPTURE_CLAIM_MECHANIC = "police_turn_gated_claim"

# Provisional: rulebook Appendix F defines max_moves as "maximum number of
# moves in a match" but does not define the counting basis. This engine
# reads it as PER-PLAYER: each side has its own budget of max_moves actions
# (moves and, for the police, barrier placements each count as one unit
# against that side's own budget).
#
# This was changed from an earlier "combined actions by both sides" reading
# after empirical testing against the real config/game.json values
# (max_moves=35, survival_threshold=35) showed the combined reading breaks
# the contract: it exhausts the ceiling at roughly half the actions the
# thief needs to reach survival_threshold, so a SURVIVAL win — and with it
# the survival_cop/survival_thief rows of the mandatory scoring table —
# became structurally unreachable. 9 of 11 self-play seeds tried under the
# combined reading ended in UndefinedOutcomeError before any other terminal
# condition could fire. An interpretation that renders a mandatory scoring
# row dead is the wrong interpretation, so this was corrected rather than
# left as the provisional default. See PRD-01 "Open questions" for the full
# evidence and for why it is still flagged as negotiable, not settled.
MAX_MOVES_COUNTING_BASIS = "per-player: each side's own action count is compared independently against max_moves"
