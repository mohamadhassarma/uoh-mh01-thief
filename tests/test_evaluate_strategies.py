"""scripts/evaluate_strategies.py: determinism given a seed list, and the
summary aggregation math."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "evaluate_strategies.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evaluate_strategies", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluate_strategies = _load_module()


def test_same_seed_list_reproduces_identical_results(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    seeds = [1, 2, 3, 4, 5]
    r1 = evaluate_strategies.run(config, "random", "random", seeds)
    r2 = evaluate_strategies.run(config, "random", "random", seeds)
    assert r1 == r2


def test_different_seeds_are_not_trivially_identical(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    r1 = evaluate_strategies.run(config, "random", "random", [1, 2, 3])
    r2 = evaluate_strategies.run(config, "random", "random", [101, 102, 103])
    assert r1 != r2


def test_summarize_win_rates_sum_to_one_minus_other(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    results = evaluate_strategies.run(config, "random", "random", list(range(1, 11)))
    summary = evaluate_strategies.summarize(results)
    assert abs(summary["police_win_rate"] + summary["thief_win_rate"] + summary["other_rate"] - 1.0) < 1e-9
    assert summary["games"] == 10


def test_named_brains_are_loaded_via_dotted_path(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    results = evaluate_strategies.run(
        config,
        "uoh_mh01.domain.police_brain:ContainmentPoliceBrain",
        "uoh_mh01.domain.thief_brain:EvasiveThiefBrain",
        [1, 2],
    )
    assert len(results) == 2
