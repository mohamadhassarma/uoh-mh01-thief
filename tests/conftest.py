from pathlib import Path
from typing import Any

import pytest

from uoh_mh01.domain.config import GameConfig, parse_config

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG_PATH = REPO_ROOT / "config" / "game.json"


def make_raw_config(
    *,
    grid_size: int = 5,
    thief_start: tuple[int, int] = (3, 3),
    cop_start: tuple[int, int] = (0, 0),
    max_barriers: int = 4,
    max_moves: int = 1000,
    survival_threshold: int = 100,
    capture_cop: int = 20,
    capture_thief: int = 5,
    survival_cop: int = 5,
    survival_thief: int = 10,
    tie_score: int = 2,
    technical_loss: int = 0,
    response_timeout_sec: float = 30,
    watchdog_timeout_sec: float = 60,
) -> dict[str, Any]:
    return {
        "schema_version": "1.2",
        "agreed_between": ["test-group", "opponent-tbd"],
        "board_and_agents": {
            "grid_size": grid_size,
            "num_agents": 2,
            "thief_start": list(thief_start),
            "cop_start": list(cop_start),
            "axis_origin_corner": "top-left",
            "axis_start_index": 0,
        },
        "world": {"map_area": "Test City", "hint_max_words": 15},
        "movement_and_barriers": {
            "move_set": ["N", "S", "E", "W", "STAY"],
            "max_barriers": max_barriers,
            "max_moves": max_moves,
            "survival_threshold": survival_threshold,
        },
        "scoring": {
            "capture_cop": capture_cop,
            "capture_thief": capture_thief,
            "survival_cop": survival_cop,
            "survival_thief": survival_thief,
            "tie_score": tie_score,
            "technical_loss": technical_loss,
        },
        "network_and_league": {
            "response_timeout_sec": response_timeout_sec,
            "watchdog_timeout_sec": watchdog_timeout_sec,
        },
    }


def make_config(**kwargs: Any) -> GameConfig:
    return parse_config(make_raw_config(**kwargs))


@pytest.fixture
def config_factory():
    return make_config


@pytest.fixture
def config() -> GameConfig:
    return make_config()
