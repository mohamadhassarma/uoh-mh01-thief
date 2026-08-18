"""Locked-model declarations exchanged in the handshake's negotiate EXTRAS
(never inside `terms` — a doc hash is not itself a signed contract value,
mirroring the interop kit's own `locked_model` pattern, SPEC §7).

PRD-03 item 12 required hash-locking the pheromone model before stage 4
existed to implement it; PRD-04 now implements `multiplicative_book_v1`
(domain/scent.py) and this module's `SCENT_MODEL_DOC` is updated to the
interop kit's own 4-key `{family, name, params, example}` schema (SPEC §7)
rather than the ad-hoc `{family, name, formula, example}` shape used before
the model existed. Reasons this is worth doing, not just cosmetic:

- A bare hash over an ad-hoc dict means two teams implementing the SAME
  model from the SAME book chapter still declare different hashes, because
  they serialized different field sets, and refuse each other for no real
  reason (kit SPEC §7's own stated rationale for the schema existing).
- The kit's `vectors/locked_model.json` PROMOTES this exact doc (byte-exact
  clean-room reproduction, issue #6) with a registered SHA-256. This
  project is not a counted participant in that league, but reproducing
  their exact hash is still a real, checkable conformance signal — see
  `tests/test_scent.py::test_locked_scent_model_matches_the_kit_promoted_hash`.
"""

from __future__ import annotations

import hashlib

from ..domain.canonical import canonical_json

# Book v3.0.0 ch.4 / figure 4, cross-checked against the interop kit's
# PROMOTED `multiplicative_book_v1` registration (SPEC §5.1,
# vectors/locked_model.json, vectors/scent_book_v3.json). `params` mirrors
# that registration field-for-field; see domain/scent.py for the actual
# implementation these params describe.
SCENT_MODEL_DOC = {
    "family": "scent_model",
    "name": "multiplicative_book_v1",
    "params": {
        "field_size": 5,
        "center_intensity": 0.9,
        "decay_rho": 0.1,
        "kernel": [
            [0.04, 0.14, 0.2, 0.14, 0.04],
            [0.14, 0.42, 0.62, 0.42, 0.14],
            [0.2, 0.62, 0.9, 0.62, 0.2],
            [0.14, 0.42, 0.62, 0.42, 0.14],
            [0.04, 0.14, 0.2, 0.14, 0.04],
        ],
        "kernel_source": "book v3.0.0 figure 4 — printed values, verbatim lookup",
        "decay": "multiplicative",
        "update": "tau' = clamp((1 - rho) * tau + kernel_delta, 0, center_intensity)",
        "evaluation_order": "(1 - rho) * tau + delta, then clamp",
        "rounding_decimals": None,
        "clamp": [0.0, 0.9],
        "cadence": "per_full_turn",
        "order": "decay_then_deposit",
        "receiver_side_decay": False,
        "initial_field": "empty",
        "transmitted": False,
    },
    "example": {
        "note": "the clamp case: a saturated cell decays, then takes an adjacent deposit",
        "tau": 0.9,
        "delta": 0.62,
        "raw": (1.0 - 0.1) * 0.9 + 0.62,  # computed, not transcribed — see the module docstring
        "clamped": 0.9,
    },
}


def scent_model_sha256() -> str:
    return hashlib.sha256(canonical_json(SCENT_MODEL_DOC).encode("utf-8")).hexdigest()
