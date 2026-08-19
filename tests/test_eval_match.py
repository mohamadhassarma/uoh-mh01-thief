"""domain/eval_match.py: the headless belief-aware loop the evaluation
harness runs — deterministic given fixed strategies, and terminates with a
real terminal condition rather than hanging or raising."""

from __future__ import annotations

import random

from uoh_mh01.domain.eval_match import play_one_game
from uoh_mh01.domain.police_brain import ContainmentPoliceBrain
from uoh_mh01.domain.strategies import make_random_strategy
from uoh_mh01.domain.thief_brain import EvasiveThiefBrain


def test_random_vs_random_terminates_with_a_real_condition(config):
    result = play_one_game(config, make_random_strategy(random.Random(1)), make_random_strategy(random.Random(2)))
    assert result.terminal_condition in (
        "capture_landing",
        "capture_barrier",
        "capture_entrapment",
        "survival",
        "technical_loss",
        "undefined",
    )
    assert result.winner in ("police", "thief", None)


def test_deterministic_given_identical_seeds(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    r1 = play_one_game(config, ContainmentPoliceBrain(random.Random(9)), EvasiveThiefBrain(random.Random(11)))
    r2 = play_one_game(config, ContainmentPoliceBrain(random.Random(9)), EvasiveThiefBrain(random.Random(11)))
    assert r1 == r2


def test_barriers_used_never_exceeds_the_quota(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    result = play_one_game(config, ContainmentPoliceBrain(random.Random(3)), EvasiveThiefBrain(random.Random(4)))
    assert result.barriers_used <= config.movement.max_barriers


def test_police_argmax_distances_are_recorded_and_non_negative(config_factory):
    config = config_factory(grid_size=7, max_barriers=14, max_moves=35, survival_threshold=35)
    result = play_one_game(config, ContainmentPoliceBrain(random.Random(1)), EvasiveThiefBrain(random.Random(2)))
    assert len(result.police_argmax_distances) > 0
    assert all(d >= 0 for d in result.police_argmax_distances)
