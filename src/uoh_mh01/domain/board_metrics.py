"""Small pure geometry/graph helpers shared by the police and thief brains
(PRD-05): Manhattan distance (the game's own move metric — no diagonals), a
local belief-mass window sum (a smoothed argmax — PRD-05's own baseline
found a single-cell argmax right barely under half the time, so both
brains reason about a NEIGHBOURHOOD's mass, never a single point), and a
reachable-area flood fill used both for the police's containment-barrier
scoring and the thief's mobility-preserving move choice.
"""

from __future__ import annotations

from .belief import BeliefMap, reachable_cells
from .board import ORTHOGONAL_DIRECTIONS, Board, Position
from .config_models import MovementConfig
from .rules import destination_of


def manhattan_distance(a: Position, b: Position) -> int:
    return abs(a.row - b.row) + abs(a.col - b.col)


def local_belief_mass(belief: BeliefMap, center: Position, radius: int) -> float:
    return sum(v for pos, v in belief.items() if manhattan_distance(pos, center) <= radius)


def best_local_hotspot(belief: BeliefMap, board: Board, radius: int) -> tuple[Position, float]:
    """The reachable cell whose `radius`-neighbourhood carries the most
    belief mass, and that mass — a smoothed stand-in for a plain argmax."""
    best_cell, best_mass = None, -1.0
    for cell in reachable_cells(board):
        mass = local_belief_mass(belief, cell, radius)
        if mass > best_mass:
            best_cell, best_mass = cell, mass
    assert best_cell is not None  # reachable_cells is never empty (own cell always reachable)
    return best_cell, best_mass


def reachable_area(board: Board, start: Position, movement: MovementConfig) -> int:
    """Flood-fill: how many cells can be reached from `start` at all,
    through non-barrier in-bounds cells and legal move directions."""
    if not board.in_bounds(start) or board.is_barrier(start):
        return 0
    seen = {start}
    frontier = [start]
    while frontier:
        pos = frontier.pop()
        for d in ORTHOGONAL_DIRECTIONS:
            if d.value not in movement.move_set:
                continue
            dest = destination_of(pos, d)
            if board.in_bounds(dest) and not board.is_barrier(dest) and dest not in seen:
                seen.add(dest)
                frontier.append(dest)
    return len(seen)
