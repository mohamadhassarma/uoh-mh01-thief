"""Small dotted-path validators shared by config.py's per-section parsers.

Split out purely to keep config.py under the project's ~150-line budget.
"""

from __future__ import annotations

from typing import Any

from .config_errors import ConfigError


def require(d: dict[str, Any], key: str, path: str) -> Any:
    if key not in d:
        raise ConfigError(f"config/game.json: missing required field '{path}.{key}'")
    return d[key]


def require_dict(d: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    value = require(d, key, path)
    if not isinstance(value, dict):
        raise ConfigError(f"config/game.json: '{path}.{key}' must be an object, got {type(value).__name__}")
    return value


def require_positive_int(d: dict[str, Any], key: str, path: str) -> int:
    value = require(d, key, path)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a positive integer, got {value!r}")
    return value


def require_nonneg_int(d: dict[str, Any], key: str, path: str) -> int:
    value = require(d, key, path)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a non-negative integer, got {value!r}")
    return value


def require_positive_number(d: dict[str, Any], key: str, path: str) -> float:
    value = require(d, key, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a positive number, got {value!r}")
    return value


def require_str(d: dict[str, Any], key: str, path: str) -> str:
    value = require(d, key, path)
    if not isinstance(value, str):
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a string, got {value!r}")
    return value


def require_coord(d: dict[str, Any], key: str, path: str, grid_size: int) -> tuple[int, int]:
    value = require(d, key, path)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        raise ConfigError(f"config/game.json: '{path}.{key}' must be a [row, col] integer pair, got {value!r}")
    row, col = value
    if not (0 <= row < grid_size and 0 <= col < grid_size):
        raise ConfigError(f"config/game.json: '{path}.{key}' = [{row}, {col}] is out of bounds for grid_size={grid_size}")
    return (row, col)
