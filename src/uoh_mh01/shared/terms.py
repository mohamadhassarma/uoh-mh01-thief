"""The flat, must-agree subset of the signed contract — what the pre-game
handshake signs, and what `game_uid` is derived from (PRD-03).

Deliberately NOT the whole `config/game.json`: deriving `game_uid` from a
wider object than this flat set is a real, documented, silently-invisible
cross-team failure mode (interop kit SPEC §4 / WARNINGS §2) — this function
is the one place that decides exactly what counts as "the terms".
"""

from __future__ import annotations

from typing import Any

from ..domain.config import GameConfig
from ..domain.match import CAPTURE_CLAIM_MECHANIC, FIRST_MOVER


def terms_from_config(config: GameConfig) -> dict[str, Any]:
    """Extract the flat, negotiable/binding terms both peers must agree on
    byte-for-byte. Two kinds of entries:

    - Values read from the signed `config/game.json` (board, movement,
      scoring, world, pheromones, num_games) — PRD-03 item 12 puts the
      pheromone VALUES here now even though the model consuming them is
      stage 4.
    - This engine's own house-rule CONSTANTS (`first_mover`,
      `capture_claim_mechanic`) — not yet configurable via game.json, but
      PRD-03 item 10 requires them signed anyway: an opponent
      implementation with different constants must refuse the handshake,
      not silently disagree mid-match about whose turn it is or what a
      capture means.
    """
    return {
        "grid_size": config.board.grid_size,
        "thief_start": list(config.board.thief_start),
        "cop_start": list(config.board.cop_start),
        "axis_origin_corner": config.board.axis_origin_corner,
        "axis_start_index": config.board.axis_start_index,
        "move_set": sorted(config.movement.move_set),
        "max_barriers": config.movement.max_barriers,
        "max_moves": config.movement.max_moves,
        "survival_threshold": config.movement.survival_threshold,
        "capture_cop": config.scoring.capture_cop,
        "capture_thief": config.scoring.capture_thief,
        "survival_cop": config.scoring.survival_cop,
        "survival_thief": config.scoring.survival_thief,
        "tie_score": config.scoring.tie_score,
        "technical_loss": config.scoring.technical_loss,
        "map_area": config.world.map_area,
        "hint_max_words": config.world.hint_max_words,
        "pheromone_center_intensity": config.pheromones.center_intensity,
        "pheromone_decay": config.pheromones.decay,
        "pheromone_grid_size": config.pheromones.grid_size,
        "num_games": config.network.num_games,
        "first_mover": FIRST_MOVER.value,
        "capture_claim_mechanic": CAPTURE_CLAIM_MECHANIC,
    }
