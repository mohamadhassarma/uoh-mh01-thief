"""The flat, must-agree subset of the signed contract — what the pre-game
handshake signs, and what `game_uid` is derived from (PRD-03).

Deliberately NOT the whole `config/game.json`: deriving `game_uid` from a
wider object than this flat set is a real, documented, silently-invisible
cross-team failure mode (interop kit SPEC §4 / WARNINGS §2) — this function
is the one place that decides exactly what counts as "the terms".

Stage-5 close-out: this used to be a wider, differently-named 23-key dict
(`grid_size`/`max_moves`/`max_barriers`/`pheromone_*`, plus `move_set`,
scoring bounds, `first_mover`, `capture_claim_mechanic` — none of which the
interop kit or the professor's own reference implementation sign). Both the
kit's `vectors/terms_signature.json` (tier CORE — "the interop floor") and
`ref_impl/src/police_thief/peer/sealing.py::terms_from_config` independently
produce the SAME flat 14-key shape below, and both do a STRICT
`terms != theirs` dict-equality check — an extra key, a missing key, or a
renamed key all refuse the handshake identically, whether talking to the
sparring peer or a real spec-conformant opponent. This function now matches
that shape exactly, key-for-key, rather than this project's own wider
invention. See PRD-05 "Which ideas failed and why" (stage-5 close-out) for
the full story of how this was found — a live rehearsal against the interop
kit's sparring peer, not a code review.

One consequence: `first_mover`/`capture_claim_mechanic`/the scoring bounds/
`move_set` are NO LONGER part of the signed, cross-verified terms — neither
outside authority signs them either, treating them as fixed engine
behaviour rather than per-match negotiable values (see
`domain.house_rules.FIRST_MOVER`'s own docstring for the turn-order
correction this same investigation produced). `max_steps` is intentionally
bound to `survival_threshold`, not `max_moves` — that is what BOTH outside
authorities do, not a typo: the wire's "step ceiling" concept is the
survival-turn count, and `max_moves` (this engine's own per-side action
budget, PRD-01 "Open questions") has no counterpart on this wire at all.
"""

from __future__ import annotations

from typing import Any

from ..domain.config import GameConfig


def terms_from_config(config: GameConfig) -> dict[str, Any]:
    """The flat 14-key terms both peers must agree on byte-for-byte — the
    interop kit's CORE `terms_signature` vector shape, reproduced key-for-
    key (see module docstring)."""
    return {
        "board_size": config.board.grid_size,
        "smell_grid_size": config.pheromones.grid_size,
        "decay_per_step": config.pheromones.decay,
        "emit_intensity": config.pheromones.center_intensity,
        "min_center_intensity": config.pheromones.min_center_intensity,
        "max_steps": config.movement.survival_threshold,
        "barriers_max": config.movement.max_barriers,
        "setting": config.world.map_area,
        "hint_max_words": config.world.hint_max_words,
        "axis_origin_corner": config.board.axis_origin_corner,
        "axis_start_index": config.board.axis_start_index,
        "thief_start": list(config.board.thief_start),
        "cop_start": list(config.board.cop_start),
        "num_games": config.network.num_games,
    }
