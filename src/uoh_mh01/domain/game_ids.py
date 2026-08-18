"""Deterministic shared game identifiers (PRD-03 / book App. F Table 20).

Both peers derive the SAME `game_id` (human-readable) and `game_uid`
(stable UUID) from data they BOTH hold after the handshake — the agreed
`terms` plus the two group ids — with no further round-trip needed, because
the derivation is a pure function of shared inputs.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .canonical import canonical_json


def derive_game_ids(terms: dict[str, Any], group_a: str, group_b: str) -> tuple[str, str]:
    """Return `(game_id, game_uid)`, identical for both peers regardless of
    which group calls this `group_a` and which `group_b` — both the id and
    the uid are built from `sorted([group_a, group_b])`, so naming order
    never matters and neither peer has to be told which one it is.

    `game_id = "-vs-".join(sorted(group_ids))` — names the four standardized
    artifacts (book App. F Table 20).

    `game_uid = UUID(SHA256(canonical_json(terms) + "|" + "|".join(sorted(group_ids)))[:16])` —
    derived from the flat NEGOTIATED terms, never the whole config. Deriving
    from a wider object (e.g. the raw config/game.json) produces a uid that
    is internally self-consistent across one team's own four artifacts —
    looks completely healthy — but fails the CROSS-team join, silently,
    because the uid never crosses the wire on its own (interop kit SPEC §4 /
    WARNINGS §2). `tests/test_vectors.py` asserts this function is fed the
    extracted `terms`, not a raw config dict, specifically to catch that
    class of bug.
    """
    pair = sorted([group_a, group_b])
    game_id = "-vs-".join(pair)
    seed = f"{canonical_json(terms)}|{'|'.join(pair)}"
    game_uid = str(uuid.UUID(bytes=hashlib.sha256(seed.encode("utf-8")).digest()[:16]))
    return game_id, game_uid
