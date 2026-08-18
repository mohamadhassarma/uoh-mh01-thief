"""PRD-04: the belief map is always a valid probability distribution and
never carries mass on a barrier or off-board cell — both invariants are
asserted structurally here, not just spot-checked."""

from __future__ import annotations

from uoh_mh01.domain.belief import (
    HintClaim,
    apply_hint,
    decay_confidence,
    initial_belief,
    reachable_cells,
    update_from_scent,
)
from uoh_mh01.domain.board import Board, Position
from uoh_mh01.domain.scent import emit


def _assert_valid_distribution(belief, board):
    reachable = set(reachable_cells(board))
    assert set(belief.keys()) == reachable
    assert all(v >= 0.0 for v in belief.values())
    assert abs(sum(belief.values()) - 1.0) < 1e-9
    for barrier in board.barriers:
        assert barrier not in belief


def test_initial_belief_is_uniform_over_reachable_cells():
    board = Board(grid_size=5).with_barrier(Position(2, 2))
    belief = initial_belief(board)
    _assert_valid_distribution(belief, board)
    values = set(belief.values())
    assert len(values) == 1  # every reachable cell carries exactly the same mass


def test_belief_never_lands_on_a_barrier_or_off_board_cell():
    board = Board(grid_size=5).with_barrier(Position(1, 1)).with_barrier(Position(3, 3))
    belief = initial_belief(board)
    scent = emit(Position(1, 1), board, _pheromones())  # deposits ON a barrier cell too
    updated = update_from_scent(belief, scent, board)
    _assert_valid_distribution(updated, board)


def test_update_from_scent_shifts_mass_toward_the_scented_region():
    board = Board(grid_size=7)
    belief = initial_belief(board)
    scent = emit(Position(5, 5), board, _pheromones())
    updated = update_from_scent(belief, scent, board)
    _assert_valid_distribution(updated, board)
    assert updated[Position(5, 5)] > updated[Position(0, 0)]


def test_decay_confidence_erodes_toward_uniform_but_stays_valid():
    board = Board(grid_size=5)
    belief = initial_belief(board)
    scent = emit(Position(0, 0), board, _pheromones())
    sharpened = update_from_scent(belief, scent, board)
    peak_before = sharpened[Position(0, 0)]
    decayed = decay_confidence(sharpened, board)
    _assert_valid_distribution(decayed, board)
    assert decayed[Position(0, 0)] < peak_before  # confidence eroded, not frozen


def test_no_cell_is_ever_permanently_ruled_out():
    # A cell driven toward (but never exactly to) zero by repeated
    # no-scent updates must still be able to recover once scent returns —
    # decay_confidence's uniform blend is what prevents a permanent zero.
    board = Board(grid_size=5)
    belief = initial_belief(board)
    empty_scent: dict = {}
    for _ in range(20):
        belief = update_from_scent(belief, empty_scent, board)
    assert belief[Position(4, 4)] > 0.0
    scent = emit(Position(4, 4), board, _pheromones())
    recovered = update_from_scent(belief, scent, board)
    assert recovered[Position(4, 4)] > belief[Position(4, 4)]


def test_apply_hint_with_zero_weight_is_a_no_op():
    board = Board(grid_size=5)
    belief = initial_belief(board)
    claim = HintClaim(text="I am near the plaza", weight=0.0)
    assert apply_hint(belief, claim, Position(2, 2), board) == belief


def test_apply_hint_with_no_claimed_cell_is_a_no_op():
    board = Board(grid_size=5)
    belief = initial_belief(board)
    claim = HintClaim(text="ambiguous, unparsed", weight=0.8)
    assert apply_hint(belief, claim, None, board) == belief


def test_apply_hint_with_positive_weight_nudges_toward_the_claimed_cell():
    board = Board(grid_size=5)
    belief = initial_belief(board)
    claim = HintClaim(text="I am near the plaza", weight=0.5)
    nudged = apply_hint(belief, claim, Position(2, 2), board)
    _assert_valid_distribution(nudged, board)
    assert nudged[Position(2, 2)] > belief[Position(2, 2)]


def test_apply_hint_with_negative_weight_can_invert_a_suspected_bluff():
    # A future strategy that suspects deception may pass a negative weight
    # to discount the claimed cell instead of boosting it — this module
    # does not decide which; it only folds in whatever the caller supplies.
    board = Board(grid_size=5)
    belief = initial_belief(board)
    claim = HintClaim(text="I am near the plaza", weight=-0.5)
    inverted = apply_hint(belief, claim, Position(2, 2), board)
    _assert_valid_distribution(inverted, board)
    assert inverted[Position(2, 2)] < belief[Position(2, 2)]


def _pheromones():
    from uoh_mh01.domain.config_models import PheromoneConfig

    return PheromoneConfig(center_intensity=0.9, decay=0.1, grid_size=5)
