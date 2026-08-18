"""Static check: game-tuning values must be read from GameConfig, never
hard-coded. See PRD-01's "no magic numbers" constraint.
"""

import ast
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "uoh_mh01" / "domain"

# Distinctive game-tuning values from config/game.json (grid_size,
# max_barriers, max_moves / survival_threshold, capture_cop, survival_thief).
# 0, 1 and 2 are deliberately excluded: they are common, legitimate
# structural constants (move deltas, "two agents", list indices) that would
# produce false positives unrelated to config leakage. tie_score (2) and
# technical_loss (0) are therefore not covered by this static check — they
# are covered instead by the explicit score-pair assertions in
# test_scoring.py.
FORBIDDEN_LITERALS = {5, 7, 10, 14, 20, 35}

# config.py is the loader: it legitimately validates against a couple of
# supported literal values (axis_start_index == 0, num_agents == 2), neither
# of which are game-tuning numbers. It is exercised directly by
# test_config.py, so it is out of scope for this leakage check.
EXCLUDED_FILES = {"config.py", "__init__.py"}

SOURCE_FILES = sorted(p for p in SRC_DIR.glob("*.py") if p.name not in EXCLUDED_FILES)


def _int_literals(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            yield node.value


@pytest.mark.parametrize("path", SOURCE_FILES, ids=[p.name for p in SOURCE_FILES])
def test_no_hardcoded_game_constants(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = sorted(set(_int_literals(tree)) & FORBIDDEN_LITERALS)
    assert not found, (
        f"{path.name} contains literal(s) {found} matching config/game.json values — "
        "read them from GameConfig instead of hard-coding them"
    )


def test_forbidden_literal_set_is_non_empty():
    # Guard against this test silently becoming a no-op.
    assert FORBIDDEN_LITERALS
    assert SOURCE_FILES
