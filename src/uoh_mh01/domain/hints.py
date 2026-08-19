"""Trash-talk hints: template-generated (zero tokens, offline, per PRD-05
section C — "keep it"), never LLM-produced. A hint is a self-declared claim
about the sender's own rough whereabouts, phrased as one of nine named
board regions ("the north", "the center", "the southeast", ...) — never the
exact cell, and never the opponent's position (a hint is always about the
SENDER, never about the SENDER's belief of the other side).

Being template-based (not free NLP text) is what makes a hint DECODABLE at
all: the receiver can recover an approximate claimed cell from the region
name without doing real language understanding, which is what lets
`belief.apply_hint` (PRD-04's interface, unused until now) actually get
called with a real claim instead of staying a theoretical hook.

The book explicitly permits deception (PRD-04/PRD-05): `generate_hint` can
be asked to lie, and the caller (a brain) decides when. Nothing here
decides truthfulness on its own, and nothing here trusts a *received*
hint's self-declared verdict — see `fuse_hint_into_belief`'s fixed,
deliberately modest trust weight, independent of what the sender claims.
"""

from __future__ import annotations

import random

from .belief import BeliefMap, HintClaim, apply_hint
from .board import Position

# (row_band, col_band) in a 3x3 grid over the board, 0=low..2=high.
_REGIONS: dict[str, tuple[int, int]] = {
    "northwest": (0, 0), "north": (0, 1), "northeast": (0, 2),
    "west": (1, 0), "center": (1, 1), "east": (1, 2),
    "southwest": (2, 0), "south": (2, 1), "southeast": (2, 2),
}

# A hint that received the receiver's own trust, always, regardless of the
# sender's self-declared verdict (which the receiver cannot verify live —
# only the post-game audit can). This project's own tuning choice, same
# spirit as PRD-04's belief-confidence constants: modest enough that a lie
# does not wreck belief, non-zero enough that a truthful hint helps.
DEFAULT_HINT_TRUST_WEIGHT = 0.15


def _band(coord: int, grid_size: int) -> int:
    third = grid_size / 3.0
    return min(2, int(coord // third))


def region_name(pos: Position, grid_size: int) -> str:
    row_band, col_band = _band(pos.row, grid_size), _band(pos.col, grid_size)
    for name, (rb, cb) in _REGIONS.items():
        if (rb, cb) == (row_band, col_band):
            return name
    raise AssertionError("unreachable: every band pair is covered")  # pragma: no cover


def region_centroid(name: str, grid_size: int) -> Position | None:
    """The approximate cell a region name refers to, or None if `name`
    isn't one of the nine known regions (an unparseable/foreign hint
    degrades to "no claim", never to a guessed cell — mirroring the interop
    kit's own "strict parse or degrade" principle for widened trail
    sources)."""
    bands = _REGIONS.get(name)
    if bands is None:
        return None
    row_band, col_band = bands
    third = grid_size / 3.0
    row = min(grid_size - 1, max(0, int((row_band + 0.5) * third)))
    col = min(grid_size - 1, max(0, int((col_band + 0.5) * third)))
    return Position(row, col)


def generate_hint(true_pos: Position, grid_size: int, *, tell_truth: bool, rng: random.Random) -> tuple[str, bool]:
    """Build (text, hint_is_true) — `hint_is_true` is the sender's OWN
    self-declared verdict about the claim it is about to make, sealed
    alongside `text` (infra/turn_sender.py): a false value here for a
    truthful-looking sentence, or vice versa, is exactly the "lying about
    whether you lied" tamper case, caught by the existing commit-reveal
    audit re-hash once both fields are inside the sealed payload.

    Word count is well under `world.hint_max_words` (15) by construction —
    the template is fixed at 5 words; still enforced defensively in
    infra/turn_sender.py before anything goes on the wire.
    """
    true_region = region_name(true_pos, grid_size)
    if tell_truth:
        return f"I am near the {true_region}.", True
    decoy_region = rng.choice([name for name in _REGIONS if name != true_region])
    return f"I am near the {decoy_region}.", False


def parse_claimed_region(hint_text: str) -> str | None:
    # Longest name first: "east" is a literal substring of "southeast" and
    # "northeast", and "west" of "southwest"/"northwest" — checking the
    # compound names first is what stops a real "southeast" claim from
    # being silently misread as the plain "east" region.
    for name in sorted(_REGIONS, key=len, reverse=True):
        if name in hint_text:
            return name
    return None


def enforce_word_cap(text: str, max_words: int) -> str:
    """`world.hint_max_words` (15) enforced BEFORE anything goes on the
    wire — a brain's own template is well under the cap by construction,
    but this is the actual, checked enforcement point, not an assumption."""
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])


def fuse_hint_into_belief(
    belief: BeliefMap, board, hint_text: str, *, trust_weight: float = DEFAULT_HINT_TRUST_WEIGHT
) -> BeliefMap:
    """Decode `hint_text` into a claimed cell and fold it into `belief` with
    a fixed, modest trust — regardless of any self-declared truth/lie
    verdict the sender attached, which is unverifiable in real time and
    exists for the audit trail, not for live trust. An unparseable hint
    (foreign text, empty string) is a no-op, per `belief.apply_hint`'s own
    "no claimed cell -> untouched" contract.
    """
    region = parse_claimed_region(hint_text)
    claimed_cell = region_centroid(region, board.grid_size) if region else None
    claim = HintClaim(text=hint_text, weight=trust_weight)
    return apply_hint(belief, claim, claimed_cell, board)
