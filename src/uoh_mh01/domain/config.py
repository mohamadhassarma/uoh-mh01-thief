"""Load and validate config/game.json — the single source of truth for every
quantitative game value. Nothing outside this module may read the raw JSON;
every other module receives values through the frozen `GameConfig` returned
by `load_config`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when config/game.json is missing, malformed, or fails validation."""


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


@dataclass(frozen=True)
class BoardConfig:
    grid_size: int
    thief_start: tuple[int, int]
    cop_start: tuple[int, int]


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
class GameConfig:
    board: BoardConfig
    movement: MovementConfig
    scoring: ScoringConfig


def _require(d: dict[str, Any], key: str, path: str) -> Any:
    if key not in d:
        raise ConfigError(f"config/game.json: missing required field '{path}.{key}'")
    return d[key]


def _require_dict(d: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    value = _require(d, key, path)
    if not isinstance(value, dict):
        raise ConfigError(f"config/game.json: '{path}.{key}' must be an object, got {type(value).__name__}")
    return value


def _require_positive_int(d: dict[str, Any], key: str, path: str) -> int:
    value = _require(d, key, path)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a positive integer, got {value!r}")
    return value


def _require_nonneg_int(d: dict[str, Any], key: str, path: str) -> int:
    value = _require(d, key, path)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a non-negative integer, got {value!r}")
    return value


def _require_coord(d: dict[str, Any], key: str, path: str, grid_size: int) -> tuple[int, int]:
    value = _require(d, key, path)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a [row, col] integer pair, got {value!r}")
    row, col = value
    if not (0 <= row < grid_size and 0 <= col < grid_size):
        raise ConfigError(
            f"config/game.json: '{path}.{key}' = [{row}, {col}] is out of bounds for grid_size={grid_size}"
        )
    return (row, col)


def _parse_board(raw: dict[str, Any]) -> BoardConfig:
    path = "board_and_agents"
    section = _require_dict(raw, path, "$")

    grid_size = _require_positive_int(section, "grid_size", path)

    num_agents = _require_positive_int(section, "num_agents", path)
    if num_agents != 2:
        raise ConfigError(f"config/game.json: '{path}.num_agents' must be 2 (police + thief), got {num_agents}")

    origin = _require(section, "axis_origin_corner", path)
    if origin != _SUPPORTED_AXIS_ORIGIN_CORNER:
        raise ConfigError(
            f"config/game.json: '{path}.axis_origin_corner' = {origin!r} is a valid, negotiable value per the "
            f"mandatory parameter table, but this ENGINE BUILD does not yet implement it — only "
            f"{_SUPPORTED_AXIS_ORIGIN_CORNER!r} is implemented so far. This is an engine limitation, not an "
            "invalid config. Supporting other orientations requires implementation work in board.py's move "
            "deltas — see TODO.md 'Known limitations'."
        )

    start_index = _require(section, "axis_start_index", path)
    if start_index != _SUPPORTED_AXIS_START_INDEX:
        raise ConfigError(
            f"config/game.json: '{path}.axis_start_index' = {start_index!r} is a valid, negotiable value per "
            f"the mandatory parameter table, but this ENGINE BUILD does not yet implement it — only "
            f"{_SUPPORTED_AXIS_START_INDEX!r} is implemented so far. This is an engine limitation, not an "
            "invalid config. Supporting other orientations requires implementation work in board.py's move "
            "deltas — see TODO.md 'Known limitations'."
        )

    thief_start = _require_coord(section, "thief_start", path, grid_size)
    cop_start = _require_coord(section, "cop_start", path, grid_size)

    if thief_start == cop_start:
        raise ConfigError(
            f"config/game.json: '{path}.thief_start' and '{path}.cop_start' are both {thief_start} "
            "— agents cannot start on the same cell"
        )

    return BoardConfig(grid_size=grid_size, thief_start=thief_start, cop_start=cop_start)


def _parse_movement(raw: dict[str, Any]) -> MovementConfig:
    path = "movement_and_barriers"
    section = _require_dict(raw, path, "$")

    move_set_raw = _require(section, "move_set", path)
    if not isinstance(move_set_raw, list) or not all(isinstance(m, str) for m in move_set_raw):
        raise ConfigError(f"config/game.json: '{path}.move_set' must be a list of strings, got {move_set_raw!r}")
    move_set = frozenset(move_set_raw)
    if move_set != _SUPPORTED_MOVE_SET:
        raise ConfigError(
            f"config/game.json: '{path}.move_set' = {sorted(move_set)} does not match the engine's "
            f"supported move set {sorted(_SUPPORTED_MOVE_SET)}"
        )

    max_barriers = _require_positive_int(section, "max_barriers", path)
    max_moves = _require_positive_int(section, "max_moves", path)
    survival_threshold = _require_positive_int(section, "survival_threshold", path)

    return MovementConfig(
        move_set=move_set,
        max_barriers=max_barriers,
        max_moves=max_moves,
        survival_threshold=survival_threshold,
    )


def _parse_scoring(raw: dict[str, Any]) -> ScoringConfig:
    path = "scoring"
    section = _require_dict(raw, path, "$")

    return ScoringConfig(
        capture_cop=_require_nonneg_int(section, "capture_cop", path),
        capture_thief=_require_nonneg_int(section, "capture_thief", path),
        survival_cop=_require_nonneg_int(section, "survival_cop", path),
        survival_thief=_require_nonneg_int(section, "survival_thief", path),
        tie_score=_require_nonneg_int(section, "tie_score", path),
        technical_loss=_require_nonneg_int(section, "technical_loss", path),
    )


def parse_config(raw: dict[str, Any]) -> GameConfig:
    """Validate an already-parsed JSON dict and build a frozen GameConfig."""
    if not isinstance(raw, dict):
        raise ConfigError(f"config/game.json: top level must be an object, got {type(raw).__name__}")
    return GameConfig(
        board=_parse_board(raw),
        movement=_parse_movement(raw),
        scoring=_parse_scoring(raw),
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
