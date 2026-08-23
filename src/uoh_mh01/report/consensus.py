"""The settlement consensus signature — a SECOND canonical form, and NOT the
one `domain/canonical.py` computes for the wire.

THE TRAP. PRD-03's per-step commits serialize COMPACT
(`separators=(",", ":")`). This signature serializes with json.dumps's
DEFAULT, SPACED separators (`", "` / `": "`). Same sorted keys, same
`ensure_ascii=False`, different bytes, different hash. A team that reuses its
wire canonicaliser here produces a signature that is internally consistent,
survives every local test, and fails at the one moment both teams must
agree — settlement. The interop kit ships `compact_form_sha256` in its vector
purely to prove the two forms do not coincide; `tests/test_consensus.py`
asserts against that field too, so a silent swap back to the compact form
cannot pass.

AUTHORITY. The book is SILENT on this construction: a full-text search of the
PDF finds no occurrence of "קונסנזוס" at all, and §9 specifies only the
report's mandatory CONTENT. The professor's reference implementation
(`report/report_writer.py::consensus_signature`, tag v3.0.0 / 960499f) and
the interop kit vector `report_consensus.json` (tier CORE) agree with each
other exactly — same serialization, same sign-then-insert ordering, same
Hebrew key — so under this project's standing source order (book, then
reference, then kit) the reference and kit carry it unopposed.

SIGN-THEN-INSERT. The hash covers the body BEFORE the signature key exists in
it; the key is then added. Verification is therefore not "re-hash the
document" but "remove the key, re-serialize, re-hash, compare" — see
`verify_signed`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# The signature field's name is Hebrew in both authorities, so it stays
# Hebrew here: an ASCII alias would be a different key and hash to a different
# document. Literally "shared consensus signature".
CONSENSUS_KEY = "חתימת_קונסנזוס_משותפת"


def consensus_json(payload: Any) -> str:
    """The spaced canonical form. `separators` is deliberately NOT passed —
    json.dumps's default IS the specified form here, and naming it explicitly
    invites someone to "tidy" it into the compact one."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def consensus_signature(payload: Any) -> str:
    return hashlib.sha256(consensus_json(payload).encode("utf-8")).hexdigest()


def sign_then_insert(report: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `report` carrying its own consensus signature.

    The ordering is load-bearing: the signature is computed over the report
    WITHOUT the key, then inserted (`ref_impl` report_writer.py:82-84).
    """
    return {**report, CONSENSUS_KEY: consensus_signature(report)}


def verify_signed(signed: dict[str, Any]) -> bool:
    """Pop the key, re-serialize spaced, re-hash, compare. Returns False for a
    document that carries no signature at all — an absent signature is not a
    valid one."""
    if CONSENSUS_KEY not in signed:
        return False
    body = dict(signed)
    claimed = body.pop(CONSENSUS_KEY)
    return consensus_signature(body) == claimed


def symmetric_scope(game_id: str, aggregate: dict[str, Any], sub_games: list[dict[str, Any]]) -> dict[str, Any]:
    """What actually goes under the hash for `result_<game_id>.json`.

    NOT the whole document. The two peers legitimately differ on wall-clock
    timestamps and on each side's own token counts, so hashing the whole body
    could never produce equal signatures between two honest, conformant
    teams — it would fail settlement by construction, every time. Only the
    symmetric outcome is covered: the ids, the aggregate, and each sub-game
    trimmed to the five fields both sides derive identically
    (`ref_impl` report/emit.py:110-118).
    """
    return {
        "game_id": game_id,
        "aggregate": aggregate,
        "sub_games": [
            {
                "sub_game_number": row["sub_game_number"],
                "roles": row["roles"],
                "result": row["result"],
                "winner_group": row["winner_group"],
                "score": row["score"],
            }
            for row in sub_games
        ],
    }
