"""Load and validate config/game.json — the single source of truth for every
quantitative game value. Nothing outside this module may read the raw JSON;
every other module receives values through the frozen `GameConfig` returned
by `load_config`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config_errors import ConfigError
from .config_models import (
    BoardConfig,
    GameConfig,
    MovementConfig,
    NetworkConfig,
    PheromoneConfig,
    ScoringConfig,
    WorldConfig,
)
from .config_parsers import (
    parse_board,
    parse_gatekeeper,
    parse_movement,
    parse_network,
    parse_pheromones,
    parse_scoring,
    parse_world,
)

__all__ = [
    "BoardConfig",
    "ConfigError",
    "GameConfig",
    "MovementConfig",
    "NetworkConfig",
    "PheromoneConfig",
    "ScoringConfig",
    "WorldConfig",
    "load_config",
    "parse_config",
]


def parse_config(raw: dict[str, Any]) -> GameConfig:
    """Validate an already-parsed JSON dict and build a frozen GameConfig."""
    if not isinstance(raw, dict):
        raise ConfigError(f"config/game.json: top level must be an object, got {type(raw).__name__}")
    return GameConfig(
        board=parse_board(raw),
        movement=parse_movement(raw),
        scoring=parse_scoring(raw),
        network=parse_network(raw),
        world=parse_world(raw),
        gatekeeper=parse_gatekeeper(raw),
        pheromones=parse_pheromones(raw),
    )


def load_config(path: str | Path) -> GameConfig:
    """Load and validate config/game.json from disk. Fails loudly on any problem."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config file at {path}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file at {path} is not valid JSON: {exc}") from exc

    return parse_config(raw)
