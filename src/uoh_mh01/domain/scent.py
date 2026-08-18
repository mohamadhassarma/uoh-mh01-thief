"""The pheromone scent field: emission and multiplicative decay (PRD-04).

Book ch.4.3's own printed formula, verified directly against the PDF:
    tau(t+1) = max(0, (1 - rho) * tau(t) + delta_tau)
This is the `multiplicative_book_v1` registration the interop kit's SPEC
§5.1 promotes (vectors/scent_book_v3.json), which pins three details the
book's printed formula alone leaves under-specified — adopted here because
without them two honest implementations of "the book's formula" silently
diverge (kit SPEC §5.1's own closed-form-probe finding):

1. **The deposit kernel is a verbatim 5x5 lookup, not a derivable formula.**
   The printed figure-4 kernel *looks* like a radial Gaussian, but the
   sigma-squared window that reproduces it under round-to-2dp ([1.3178,
   1.3327]) is disjoint from the one that reproduces it under truncation
   ([1.3436, 1.3538]) — two teams each fitting "a Gaussian" in good faith
   would get different, silently-diverging fields. The 25 printed values are
   the only thing both can reach, so they are hard-coded here, not computed.
2. **An upper clamp at `center_intensity`.** The printed formula prints only
   `max(0, ...)`; without an upper bound a saturated cell that decays and is
   then redeposited on reaches `0.9*0.9 + 0.62 = 1.43`, outside the book's
   own declared tau range of [0, 0.9]. Documented here as a reasoned
   deviation from the printed (illustrative) formula, matching PRD-03's
   precedent for exactly this class of gap.
3. **Evaluation order is pinned**: `(1 - rho) * tau + delta`, not the
   algebraically-identical `tau - rho * tau + delta` — the two are different
   IEEE-754 doubles on ~14% of the kit's own probed inputs, and this model
   is never rounded, so the bit pattern is what a peer's own re-derivation
   must match turn over turn.

The kernel is a fixed constant valid only at App F's fixed pheromone values
(center_intensity=0.9, grid_size=5) — those three parameters are marked
`קבוע` (fixed, not negotiable) in App F table 16, so no scaling logic for a
different center intensity is implemented; `emit()` asserts the config
matches what the kernel was pinned for.
"""

from __future__ import annotations

from collections.abc import Mapping

from .board import Board, Position
from .config_models import PheromoneConfig

ScentField = dict[Position, float]

# Book v3.0.0 figure 4, printed values, verbatim (kit SPEC §5.1 / vectors/
# scent_book_v3.json `model.params.kernel`) — row/col offsets -2..2 from the
# emitting cell. NOT derived from a formula; see module docstring point 1.
_KERNEL: tuple[tuple[float, ...], ...] = (
    (0.04, 0.14, 0.20, 0.14, 0.04),
    (0.14, 0.42, 0.62, 0.42, 0.14),
    (0.20, 0.62, 0.90, 0.62, 0.20),
    (0.14, 0.42, 0.62, 0.42, 0.14),
    (0.04, 0.14, 0.20, 0.14, 0.04),
)
_KERNEL_RADIUS = 2  # (len(_KERNEL) - 1) // 2


def emit(center: Position, board: Board, pheromones: PheromoneConfig) -> ScentField:
    """The fresh deposit (`delta_tau`) a full turn's own move/stay/barrier
    action leaves around `center` — clipped to the board, per the kit's own
    "corner emission clipped to board bounds" vector case."""
    if pheromones.grid_size != len(_KERNEL) or pheromones.center_intensity != 0.9:
        raise ValueError(
            "the multiplicative_book_v1 kernel is a verbatim lookup pinned to "
            "App F's fixed grid_size=5, center_intensity=0.9 — it cannot be "
            f"reused for grid_size={pheromones.grid_size}, "
            f"center_intensity={pheromones.center_intensity}"
        )
    deposit: ScentField = {}
    for dr in range(-_KERNEL_RADIUS, _KERNEL_RADIUS + 1):
        for dc in range(-_KERNEL_RADIUS, _KERNEL_RADIUS + 1):
            pos = Position(center.row + dr, center.col + dc)
            if board.in_bounds(pos):
                deposit[pos] = _KERNEL[dr + _KERNEL_RADIUS][dc + _KERNEL_RADIUS]
    return deposit


def advance_field(existing: Mapping[Position, float], deposit: Mapping[Position, float], pheromones: PheromoneConfig) -> ScentField:
    """One full-turn decay-then-deposit step over every cell either side
    already knows about or is depositing on this turn:
    `tau' = clamp((1 - rho) * tau + delta, 0, center_intensity)`.

    Cells that decay to exactly 0 are dropped — "only value>0 crosses the
    wire" (kit SPEC §5), and there is nothing left to distinguish a decayed-
    to-zero cell from one never emitted on.
    """
    rho = pheromones.decay
    ceiling = pheromones.center_intensity
    result: ScentField = {}
    for pos in existing.keys() | deposit.keys():
        tau = existing.get(pos, 0.0)
        delta = deposit.get(pos, 0.0)
        raw = (1.0 - rho) * tau + delta
        clamped = min(max(raw, 0.0), ceiling)
        if clamped > 0.0:
            result[pos] = clamped
    return result


def serialize_field(field: Mapping[Position, float]) -> dict[str, float]:
    """Wire/sealed-payload form: `{"row,col": intensity}` — matching the
    interop kit's own vector convention exactly (no space after the comma,
    unlike `sealed_payload.state_str`'s barrier-list repr)."""
    return {f"{pos.row},{pos.col}": value for pos, value in field.items()}


def deserialize_field(wire: Mapping[str, float]) -> ScentField:
    result: ScentField = {}
    for key, value in wire.items():
        row_str, col_str = key.split(",")
        result[Position(int(row_str), int(col_str))] = value
    return result
