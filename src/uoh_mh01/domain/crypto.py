"""Commit-Reveal over SHA-256 (PRD-03) — the mandatory mechanism (book ch.5.3
/ Table 12 rules #17-#20-ish) is binding; the exact preimage the book's own
printed listing shows is not (see PRD-03's "Commit preimage" section for the
full citation and the deliberate, documented choice made instead).

commit = SHA256( canonical_json(payload) + "|" + nonce )

Nonce is pipe-appended OUTSIDE the canonicalized payload, not a key inside
it — matching the reference implementation's actual code and the interop
kit's CORE `commit_reveal.json` vector, not the book's own ch.5.3 printed
listing (which puts nonce inside the object with no `ensure_ascii=False`).
Chosen for interop: the opponent's audit re-hashes OUR revealed records with
THEIR serializer, so matching what real opponent teams will build against
matters more than fidelity to an illustration the book's own clarification
page says does not bind participants.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from .canonical import canonical_json

NONCE_BYTES = 16


def commit_of(payload: dict[str, Any], nonce: str) -> str:
    """The commit hash for `payload` under the already-known `nonce`."""
    preimage = f"{canonical_json(payload)}|{nonce}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, str]:
    """Generate a fresh cryptographic nonce and this payload's commit hash.
    Returns `{"nonce": ..., "commit": ...}` — the nonce must stay secret
    until the post-sub-game mutual audit (book rule: nonces revealed only
    at Final Reveal/Audit); only `commit` may be sent immediately."""
    nonce = secrets.token_hex(NONCE_BYTES)
    return {"nonce": nonce, "commit": commit_of(payload, nonce)}


def verify(payload: dict[str, Any], nonce: str, commit: str) -> bool:
    """Does `(payload, nonce)` reproduce `commit`? Used both for self-audit
    (do my own revealed records still match what I committed to) and for
    the opponent's cross-audit of my revealed records."""
    return commit_of(payload, nonce) == commit
