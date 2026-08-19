"""PRD-05: a role-alternating series must resolve a FRESH, role-correct
brain for each sub-game — not reuse one strategy resolved once from this
process's natural role, which would silently run the wrong brain (or carry
stale state) whenever role alternation swaps this process onto the other
side (infra/series_subgame.py's `_strategy_for_sub_game`)."""

from __future__ import annotations

from dataclasses import replace

from uoh_mh01.domain.brain_base import BrainBase
from uoh_mh01.domain.police_brain import ContainmentPoliceBrain
from uoh_mh01.domain.state import Side
from uoh_mh01.domain.thief_brain import EvasiveThiefBrain
from uoh_mh01.infra.series_subgame import _strategy_for_sub_game
from uoh_mh01.shared.peer_config import PeerConfig


def _peer_config(**overrides) -> PeerConfig:
    return PeerConfig(
        role="police",
        group_id="g",
        group_name="G",
        my_port=1,
        opponent_url="http://x",
        turn_timeout_seconds=30,
        police_class="uoh_mh01.domain.police_brain:ContainmentPoliceBrain",
        thief_class="uoh_mh01.domain.thief_brain:EvasiveThiefBrain",
        **overrides,
    )


def test_picks_the_police_brain_when_this_sub_game_plays_police():
    strategy = _strategy_for_sub_game(_peer_config(), Side.POLICE, seed=1, sub_game_number=1)
    assert isinstance(strategy, ContainmentPoliceBrain)


def test_picks_the_thief_brain_when_this_sub_game_plays_thief():
    # Same process, same peer_config — only the ROLE for this sub-game
    # differs, exactly the role-alternation case PRD-03 requires.
    strategy = _strategy_for_sub_game(_peer_config(), Side.THIEF, seed=1, sub_game_number=2)
    assert isinstance(strategy, EvasiveThiefBrain)


def test_falls_back_to_random_baseline_when_no_class_configured():
    peer_config = replace(_peer_config(), police_class=None)
    strategy = _strategy_for_sub_game(peer_config, Side.POLICE, seed=1, sub_game_number=1)
    assert not isinstance(strategy, BrainBase)


def test_different_sub_games_get_independent_but_deterministic_rng():
    a1 = _strategy_for_sub_game(_peer_config(), Side.POLICE, seed=7, sub_game_number=1)
    a2 = _strategy_for_sub_game(_peer_config(), Side.POLICE, seed=7, sub_game_number=1)
    b = _strategy_for_sub_game(_peer_config(), Side.POLICE, seed=7, sub_game_number=3)
    # Same (seed, sub_game_number) reproduces the same RNG stream...
    assert a1.rng.random() == a2.rng.random()
    # ...but a different sub_game_number does not collide with it.
    assert a1.rng.random() != b.rng.random()
