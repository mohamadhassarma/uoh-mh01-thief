"""The per-section parsers `parse_config` composes. Split out of config.py
purely to keep that file under the project's ~150-line budget.
"""

from __future__ import annotations

from typing import Any

from .config_errors import ConfigError
from .config_models import (
    BoardConfig,
    GatekeeperConfig,
    MovementConfig,
    NetworkConfig,
    PheromoneConfig,
    ScoringConfig,
    WorldConfig,
)
from .config_validators import (
    require,
    require_coord,
    require_dict,
    require_nonneg_int,
    require_positive_int,
    require_positive_number,
    require_str,
)

# axis_origin_corner and axis_start_index are marked NEGOTIABLE in the
# mandatory parameter table — the rulebook only requires both sides to agree
# on a value, not that the value be top-left/0. This engine currently only
# IMPLEMENTS that one orientation (board.py's move deltas are built for it).
# A different, mutually-agreed value is a legitimate config, not a malformed
# one — the guard below exists so an unimplemented orientation fails loudly
# as an engine limitation instead of silently misplacing agents, not because
# the value itself would be invalid. See TODO.md "Known limitations".
_SUPPORTED_AXIS_ORIGIN_CORNER = "top-left"
_SUPPORTED_AXIS_START_INDEX = 0
_SUPPORTED_MOVE_SET = frozenset({"N", "S", "E", "W", "STAY"})


def parse_board(raw: dict[str, Any]) -> BoardConfig:
    path = "board_and_agents"
    section = require_dict(raw, path, "$")

    grid_size = require_positive_int(section, "grid_size", path)

    num_agents = require_positive_int(section, "num_agents", path)
    if num_agents != 2:
        raise ConfigError(f"config/game.json: '{path}.num_agents' must be 2 (police + thief), got {num_agents}")

    origin = require(section, "axis_origin_corner", path)
    if origin != _SUPPORTED_AXIS_ORIGIN_CORNER:
        raise ConfigError(
            f"config/game.json: '{path}.axis_origin_corner' = {origin!r} is a valid, negotiable value per the "
            f"mandatory parameter table, but this ENGINE BUILD does not yet implement it — only "
            f"{_SUPPORTED_AXIS_ORIGIN_CORNER!r} is implemented so far. This is an engine limitation, not an "
            "invalid config. Supporting other orientations requires implementation work in board.py's move "
            "deltas — see TODO.md 'Known limitations'."
        )

    start_index = require(section, "axis_start_index", path)
    if start_index != _SUPPORTED_AXIS_START_INDEX:
        raise ConfigError(
            f"config/game.json: '{path}.axis_start_index' = {start_index!r} is a valid, negotiable value per "
            f"the mandatory parameter table, but this ENGINE BUILD does not yet implement it — only "
            f"{_SUPPORTED_AXIS_START_INDEX!r} is implemented so far. This is an engine limitation, not an "
            "invalid config. Supporting other orientations requires implementation work in board.py's move "
            "deltas — see TODO.md 'Known limitations'."
        )

    thief_start = require_coord(section, "thief_start", path, grid_size)
    cop_start = require_coord(section, "cop_start", path, grid_size)

    if thief_start == cop_start:
        raise ConfigError(
            f"config/game.json: '{path}.thief_start' and '{path}.cop_start' are both {thief_start} "
            "— agents cannot start on the same cell"
        )

    return BoardConfig(
        grid_size=grid_size,
        thief_start=thief_start,
        cop_start=cop_start,
        axis_origin_corner=origin,
        axis_start_index=start_index,
    )


def parse_movement(raw: dict[str, Any]) -> MovementConfig:
    path = "movement_and_barriers"
    section = require_dict(raw, path, "$")

    move_set_raw = require(section, "move_set", path)
    if not isinstance(move_set_raw, list) or not all(isinstance(m, str) for m in move_set_raw):
        raise ConfigError(f"config/game.json: '{path}.move_set' must be a list of strings, got {move_set_raw!r}")
    move_set = frozenset(move_set_raw)
    if move_set != _SUPPORTED_MOVE_SET:
        raise ConfigError(
            f"config/game.json: '{path}.move_set' = {sorted(move_set)} does not match the engine's "
            f"supported move set {sorted(_SUPPORTED_MOVE_SET)}"
        )

    return MovementConfig(
        move_set=move_set,
        max_barriers=require_positive_int(section, "max_barriers", path),
        max_moves=require_positive_int(section, "max_moves", path),
        survival_threshold=require_positive_int(section, "survival_threshold", path),
    )


def parse_scoring(raw: dict[str, Any]) -> ScoringConfig:
    path = "scoring"
    section = require_dict(raw, path, "$")

    return ScoringConfig(
        capture_cop=require_nonneg_int(section, "capture_cop", path),
        capture_thief=require_nonneg_int(section, "capture_thief", path),
        survival_cop=require_nonneg_int(section, "survival_cop", path),
        survival_thief=require_nonneg_int(section, "survival_thief", path),
        tie_score=require_nonneg_int(section, "tie_score", path),
        technical_loss=require_nonneg_int(section, "technical_loss", path),
    )


def parse_network(raw: dict[str, Any]) -> NetworkConfig:
    path = "network_and_league"
    section = require_dict(raw, path, "$")

    return NetworkConfig(
        response_timeout_sec=require_positive_number(section, "response_timeout_sec", path),
        watchdog_timeout_sec=require_positive_number(section, "watchdog_timeout_sec", path),
        num_games=require_positive_int(section, "num_games", path),
    )


def parse_gatekeeper(raw: dict[str, Any]) -> GatekeeperConfig:
    path = "rate_limiter_gatekeeper"
    section = require_dict(raw, path, "$")
    return GatekeeperConfig(
        requests_per_minute=require_positive_int(section, "requests_per_minute", path),
        concurrent_requests=require_positive_int(section, "concurrent_requests", path),
        retry_backoff_sec=require_positive_number(section, "retry_backoff_sec", path),
        max_retries=require_positive_int(section, "max_retries", path),
        queue_depth=require_positive_int(section, "queue_depth", path),
    )


def parse_world(raw: dict[str, Any]) -> WorldConfig:
    path = "world"
    section = require_dict(raw, path, "$")
    return WorldConfig(
        map_area=require_str(section, "map_area", path),
        hint_max_words=require_positive_int(section, "hint_max_words", path),
    )


def parse_pheromones(raw: dict[str, Any]) -> PheromoneConfig:
    path = "pheromones"
    section = require_dict(raw, path, "$")
    return PheromoneConfig(
        center_intensity=require_positive_number(section, "pheromone_center_intensity", path),
        decay=require_positive_number(section, "pheromone_decay", path),
        grid_size=require_positive_int(section, "pheromone_grid_size", path),
        min_center_intensity=require_positive_number(section, "pheromone_min_center_intensity", path),
    )
