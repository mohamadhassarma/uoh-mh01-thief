"""PRD-05: `resolve_strategy`'s brain-loading — falls back to the shipped
random baseline when no `[strategy]` class is configured, and loads the
right role's class when one is."""

from __future__ import annotations

from uoh_mh01.domain.brain_base import BrainBase, resolve_strategy
from uoh_mh01.domain.police_brain import ContainmentPoliceBrain


def test_no_configured_class_falls_back_to_random_baseline():
    strategy = resolve_strategy(None, seed=1)
    assert not isinstance(strategy, BrainBase)


def test_configured_class_is_loaded():
    strategy = resolve_strategy("uoh_mh01.domain.police_brain:ContainmentPoliceBrain", seed=1)
    assert isinstance(strategy, ContainmentPoliceBrain)
