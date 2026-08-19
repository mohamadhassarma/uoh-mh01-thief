"""PRD-05 section C: hint generation/decoding, the word cap, and belief
fusion with a fixed, sender-verdict-independent trust weight."""

from __future__ import annotations

import random

from uoh_mh01.domain.belief import initial_belief
from uoh_mh01.domain.board import Board, Position
from uoh_mh01.domain.hints import (
    enforce_word_cap,
    fuse_hint_into_belief,
    generate_hint,
    parse_claimed_region,
    region_centroid,
    region_name,
)


def test_region_name_and_centroid_are_approximate_inverses():
    board = Board(grid_size=7)
    for pos in (Position(0, 0), Position(3, 3), Position(6, 6), Position(0, 6), Position(3, 0)):
        name = region_name(pos, board.grid_size)
        centroid = region_centroid(name, board.grid_size)
        # Not required to be the exact cell (a region covers many cells) —
        # but decoding the name it produced must land back in the SAME region.
        assert region_name(centroid, board.grid_size) == name


def test_region_centroid_of_unknown_name_is_none():
    assert region_centroid("nowhere", 7) is None


def test_generate_hint_truthful_names_the_true_region():
    rng = random.Random(1)
    true_pos = Position(0, 0)
    text, is_true = generate_hint(true_pos, 7, tell_truth=True, rng=rng)
    assert is_true is True
    assert region_name(true_pos, 7) in text


def test_generate_hint_lie_names_a_different_region():
    rng = random.Random(1)
    true_pos = Position(0, 0)
    text, is_true = generate_hint(true_pos, 7, tell_truth=False, rng=rng)
    assert is_true is False
    claimed = parse_claimed_region(text)
    assert claimed != region_name(true_pos, 7)


def test_enforce_word_cap_truncates_over_the_limit():
    text = "one two three four five six"
    assert enforce_word_cap(text, 3) == "one two three"


def test_enforce_word_cap_leaves_short_text_untouched():
    text = "I am near the center."
    assert enforce_word_cap(text, 15) == text


def test_fuse_hint_into_belief_shifts_mass_toward_the_claimed_region():
    board = Board(grid_size=7)
    belief = initial_belief(board)
    text, _is_true = generate_hint(Position(6, 6), 7, tell_truth=True, rng=random.Random(1))
    updated = fuse_hint_into_belief(belief, board, text)
    target = region_centroid(region_name(Position(6, 6), 7), 7)
    assert updated[target] > belief[target]
    assert abs(sum(updated.values()) - 1.0) < 1e-9  # still a valid distribution


def test_fuse_hint_into_belief_with_unparseable_text_is_a_no_op():
    board = Board(grid_size=7)
    belief = initial_belief(board)
    assert fuse_hint_into_belief(belief, board, "gibberish with no region words") == belief


def test_fuse_hint_into_belief_with_empty_text_is_a_no_op():
    board = Board(grid_size=7)
    belief = initial_belief(board)
    assert fuse_hint_into_belief(belief, board, "") == belief
