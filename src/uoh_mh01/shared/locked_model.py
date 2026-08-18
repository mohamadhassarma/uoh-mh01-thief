"""Locked-model declarations exchanged in the handshake's negotiate EXTRAS
(never inside `terms` — a doc hash is not itself a signed contract value,
mirroring the interop kit's own `locked_model` pattern, SPEC §7).

PRD-03 item 12: the book requires exchanging and hash-locking the FULL
pheromone emission/decay model, with a concrete worked example, BEFORE the
series opens (ch.4, verified directly in the book PDF) — even though the
model itself is stage 4 (PRD-04) and not implemented yet. This module is
that hook, built now so the handshake has something real to carry.
"""

from __future__ import annotations

import hashlib

from ..domain.canonical import canonical_json

# The book's own binding formula (ch.4, verified directly against the PDF):
#   tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)
# — multiplicative decay, winning over the reference implementation's
# differing (subtractive) computation. See PRD-04 for the full spec; NOT
# implemented here, only declared and hashed.
SCENT_MODEL_DOC = {
    "family": "scent_model",
    "name": "multiplicative_book_v1",
    "formula": "tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)",
    "example": {"center_intensity_before": 0.9, "decay_rate": 0.1, "after_one_round_of_decay": 0.81},
}


def scent_model_sha256() -> str:
    return hashlib.sha256(canonical_json(SCENT_MODEL_DOC).encode("utf-8")).hexdigest()
