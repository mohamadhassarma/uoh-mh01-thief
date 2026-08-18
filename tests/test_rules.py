import pytest

from uoh_mh01.domain.board import Board, Direction, Position, delta_for
from uoh_mh01.domain.rules import (
    destination_of,
    is_barrier_placement_legal,
    is_capture_state,
    is_move_legal,
    is_thief_trapped,
    legal_moves,
)


def test_direction_enum_has_no_diagonal_members():
    # Diagonal moves are rejected structurally: the move representation
    # itself has exactly five members and cannot express a diagonal.
    assert {d.value for d in Direction} == {"N", "S", "E", "W", "STAY"}
    with pytest.raises(ValueError):
        Direction("NE")


def test_deltas_are_never_diagonal():
    for direction in Direction:
        delta = delta_for(direction)
        assert delta.row == 0 or delta.col == 0, f"{direction} has a diagonal delta {delta}"


@pytest.mark.parametrize(
    "direction,expected",
    [
        (Direction.N, Position(1, 2)),
        (Direction.S, Position(3, 2)),
        (Direction.E, Position(2, 3)),
        (Direction.W, Position(2, 1)),
        (Direction.STAY, Position(2, 2)),
    ],
)
def test_each_move_from_mid_board(config, direction, expected):
    board = Board(grid_size=config.board.grid_size)
    pos = Position(2, 2)
    assert is_move_legal(board, pos, direction, config.movement)
    assert destination_of(pos, direction) == expected


def test_off_board_move_rejected(config):
    board = Board(grid_size=config.board.grid_size)
    corner = Position(0, 0)
    assert not is_move_legal(board, corner, Direction.N, config.movement)
    assert not is_move_legal(board, corner, Direction.W, config.movement)


def test_move_into_barrier_rejected(config):
    board = Board(grid_size=config.board.grid_size).with_barrier(Position(2, 3))
    pos = Position(2, 2)
    assert not is_move_legal(board, pos, Direction.E, config.movement)


def test_stay_is_legal_even_on_a_barrier_cell(config):
    pos = Position(2, 2)
    board = Board(grid_size=config.board.grid_size).with_barrier(pos)
    assert is_move_legal(board, pos, Direction.STAY, config.movement)


def test_legal_moves_excludes_illegal_directions(config):
    board = Board(grid_size=config.board.grid_size).with_barrier(Position(0, 1))
    moves = legal_moves(board, Position(0, 0), config.movement)
    assert Direction.E not in moves
    assert Direction.STAY in moves


@pytest.mark.parametrize("target", [Position(2, 2), Position(1, 2), Position(3, 2), Position(2, 1), Position(2, 3)])
def test_barrier_legal_on_own_cell_and_orthogonal_neighbours(config, target):
    board = Board(grid_size=config.board.grid_size)
    cop_pos = Position(2, 2)
    assert is_barrier_placement_legal(board, cop_pos, target, barriers_placed=0, movement=config.movement)


@pytest.mark.parametrize(
    "target",
    [
        Position(0, 2),  # distance 2
        Position(1, 1),  # diagonal
        Position(1, 3),  # diagonal
        Position(3, 1),  # diagonal
        Position(3, 3),  # diagonal
    ],
)
def test_barrier_illegal_at_range_and_diagonal(config, target):
    board = Board(grid_size=config.board.grid_size)
    cop_pos = Position(2, 2)
    assert not is_barrier_placement_legal(board, cop_pos, target, barriers_placed=0, movement=config.movement)


def test_barrier_quota_enforced(config):
    board = Board(grid_size=config.board.grid_size)
    cop_pos = Position(2, 2)
    assert not is_barrier_placement_legal(
        board, cop_pos, cop_pos, barriers_placed=config.movement.max_barriers, movement=config.movement
    )
    assert is_barrier_placement_legal(
        board, cop_pos, cop_pos, barriers_placed=config.movement.max_barriers - 1, movement=config.movement
    )


def test_barrier_cannot_be_placed_twice_on_same_cell(config):
    target = Position(1, 2)
    board = Board(grid_size=config.board.grid_size).with_barrier(target)
    assert not is_barrier_placement_legal(board, Position(2, 2), target, barriers_placed=1, movement=config.movement)


def test_capture_state_is_symmetric_coordinate_overlap():
    assert is_capture_state(Position(2, 2), Position(2, 2))
    assert not is_capture_state(Position(2, 2), Position(2, 3))


def test_thief_trapped_when_all_four_neighbours_blocked(config):
    thief = Position(2, 2)
    board = Board(grid_size=config.board.grid_size)
    for neighbour in board.orthogonal_neighbors(thief):
        board = board.with_barrier(neighbour)
    assert is_thief_trapped(board, thief, config.movement)


def test_thief_not_trapped_with_one_open_neighbour(config):
    thief = Position(2, 2)
    board = Board(grid_size=config.board.grid_size)
    neighbours = board.orthogonal_neighbors(thief)
    for neighbour in neighbours[:-1]:
        board = board.with_barrier(neighbour)
    assert not is_thief_trapped(board, thief, config.movement)


def test_entrapment_excludes_stay(config):
    # The subtle pitfall: STAY is always a legal move in isolation, so a
    # naive "does the thief have any legal move?" implementation would make
    # entrapment unreachable. The rulebook defines entrapment structurally
    # ("all orthogonally adjacent cells are barriers and/or board edges"),
    # independent of STAY — so both must be true at once here.
    thief = Position(2, 2)
    board = Board(grid_size=config.board.grid_size)
    for neighbour in board.orthogonal_neighbors(thief):
        board = board.with_barrier(neighbour)

    assert is_move_legal(board, thief, Direction.STAY, config.movement), "STAY must still be legal in isolation"
    assert is_thief_trapped(board, thief, config.movement), "but the thief must still be trapped"


def test_entrapment_by_board_corner(config):
    # A corner cell has only two orthogonal neighbours on the board at all;
    # the other two directions are off-board edges, which must count toward
    # entrapment exactly like barriers do.
    thief = Position(0, 0)
    board = Board(grid_size=config.board.grid_size)
    board = board.with_barrier(Position(0, 1)).with_barrier(Position(1, 0))
    assert is_thief_trapped(board, thief, config.movement)


def test_barrier_on_thief_cell_is_a_legal_placement_not_rejected(config):
    # Barrier legality never looks at the thief's position at all — only cop
    # adjacency, in-bounds, and quota. Landing on the thief is what makes the
    # placement a CAPTURE (see reducers.apply_barrier), not what makes it
    # illegal. A naive implementation might reject this as "occupied."
    thief_pos = Position(2, 3)
    cop_pos = Position(2, 2)
    board = Board(grid_size=config.board.grid_size)
    assert is_barrier_placement_legal(board, cop_pos, thief_pos, barriers_placed=0, movement=config.movement)
