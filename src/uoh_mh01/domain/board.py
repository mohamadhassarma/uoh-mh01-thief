"""Grid mechanics: coordinates, bounds, barriers, adjacency.

No player positions and no turn logic live here — this module only knows about
the physical board. It is immutable: placing a barrier returns a new Board.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class Position(NamedTuple):
    row: int
    col: int

    def __add__(self, other: "Position") -> "Position":  # type: ignore[override]
        return Position(self.row + other.row, self.col + other.col)


class Direction(str, Enum):
    """The five moves in the signed contract's move_set.

    Deltas are geometric facts of the validated 'top-left origin, row grows
    downward' orientation (config.py rejects any other orientation) — not
    game-tunable values, so they are not read from game.json.
    """

    N = "N"
    S = "S"
    E = "E"
    W = "W"
    STAY = "STAY"


_DELTAS: dict[Direction, Position] = {
    Direction.N: Position(-1, 0),
    Direction.S: Position(1, 0),
    Direction.E: Position(0, 1),
    Direction.W: Position(0, -1),
    Direction.STAY: Position(0, 0),
}

# The four orthogonal directions, excluding STAY — used for adjacency and for
# entrapment detection (a STAY option never rescues the thief from entrapment;
# see rules.py).
ORTHOGONAL_DIRECTIONS: tuple[Direction, ...] = (Direction.N, Direction.S, Direction.E, Direction.W)


def delta_for(direction: Direction) -> Position:
    return _DELTAS[direction]


@dataclass(frozen=True)
class Board:
    grid_size: int
    barriers: frozenset[Position] = field(default_factory=frozenset)

    def in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.row < self.grid_size and 0 <= pos.col < self.grid_size

    def is_barrier(self, pos: Position) -> bool:
        return pos in self.barriers

    def orthogonal_neighbors(self, pos: Position) -> tuple[Position, ...]:
        return tuple(pos + delta_for(d) for d in ORTHOGONAL_DIRECTIONS)

    def with_barrier(self, pos: Position) -> "Board":
        return Board(grid_size=self.grid_size, barriers=self.barriers | {pos})
