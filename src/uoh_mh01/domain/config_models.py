"""The frozen dataclasses `parse_config` builds. Split out of config.py
purely to keep that file under the project's ~150-line budget.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardConfig:
    grid_size: int
    thief_start: tuple[int, int]
    cop_start: tuple[int, int]
    axis_origin_corner: str
    axis_start_index: int


@dataclass(frozen=True)
class MovementConfig:
    move_set: frozenset[str]
    max_barriers: int
    max_moves: int
    survival_threshold: int


@dataclass(frozen=True)
class ScoringConfig:
    capture_cop: int
    capture_thief: int
    survival_cop: int
    survival_thief: int
    tie_score: int
    technical_loss: int


@dataclass(frozen=True)
class WorldConfig:
    # world.* — part of the signed terms (PRD-03): both sides must agree on
    # the setting used for hints and the hint word cap, even though neither
    # is consumed by any code until stage 5's verbal layer.
    map_area: str
    hint_max_words: int


@dataclass(frozen=True)
class PheromoneConfig:
    # pheromones.* — part of the signed terms (PRD-03 item 12): the VALUES
    # must be agreed and signed now, even though the emission/decay MODEL
    # that consumes them is stage 4 (PRD-04). Field names kept close to
    # config/game.json's own keys.
    center_intensity: float
    decay: float
    grid_size: int


@dataclass(frozen=True)
class NetworkConfig:
    response_timeout_sec: float
    watchdog_timeout_sec: float
    num_games: int


@dataclass(frozen=True)
class GameConfig:
    board: BoardConfig
    movement: MovementConfig
    scoring: ScoringConfig
    network: NetworkConfig
    world: WorldConfig
    pheromones: PheromoneConfig
