"""Turning a game snapshot into things to draw - with no Tk in sight.

Everything that decides what the viewer LOOKS like lives here as plain data,
so it can be asserted in tests on a machine with no display. `tk_app.py` is
then a thin painter: it may not compute a colour or a label of its own.

WHY THE HEAT IS NORMALISED AGAINST THE PEAK. A belief map is a probability
distribution over every reachable cell, so on a 10x10 board a typical cell
carries about 0.01 and the most-suspected cell might carry 0.04. Painted as
absolute probability the whole board is a uniform near-black smear and the
picture says nothing. Scaling against the current maximum shows the SHAPE of
the belief - which is the thing worth looking at - at the cost of the picture
not being comparable between frames. `peak` is drawn in the HUD so the reader
can see the absolute number the colours are relative to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Dark ground, so a bright cell reads as "hot" rather than "lit".
BACKGROUND = "#0e0e13"
GRID_LINE = "#2a2a36"
BARRIER = "#5a5f6e"
OWN_POLICE = "#4aa3ff"
OWN_THIEF = "#ffd24a"
HEAT_COLD = (24, 24, 32)
HEAT_HOT = (219, 58, 52)
TEXT = "#e8e8ef"
TEXT_DIM = "#8a8a9a"


@dataclass(frozen=True)
class CellPaint:
    row: int
    col: int
    fill: str
    barrier: bool = False
    own: bool = False
    peak: bool = False


@dataclass(frozen=True)
class Scene:
    grid_size: int
    cells: tuple[CellPaint, ...]
    hud: tuple[tuple[str, str], ...] = ()
    title: str = ""
    footer: str = ""
    legend: tuple[tuple[str, str], ...] = field(default=())


def heat_colour(intensity: float) -> str:
    """`intensity` in [0, 1] -> a hex colour reddening with intensity."""
    t = 0.0 if intensity < 0.0 else (1.0 if intensity > 1.0 else intensity)
    channels = (round(cold + t * (hot - cold)) for cold, hot in zip(HEAT_COLD, HEAT_HOT, strict=True))
    return "#" + "".join(f"{c:02x}" for c in channels)


def _belief_grid(snapshot: dict, grid_size: int) -> list[list[float]]:
    raw = snapshot.get("belief") or []
    grid = [[0.0] * grid_size for _ in range(grid_size)]
    for r, row in enumerate(raw[:grid_size]):
        for c, value in enumerate(row[:grid_size]):
            grid[r][c] = float(value)
    return grid


def build_scene(snapshot: dict) -> Scene:
    """A snapshot (see `live_state.py`) -> everything the viewer draws."""
    grid_size = int(snapshot.get("grid_size", 0))
    belief = _belief_grid(snapshot, grid_size)
    barriers = {tuple(cell) for cell in snapshot.get("barriers", [])}
    own = tuple(snapshot.get("own_pos") or ()) or None
    role = snapshot.get("role", "?")

    flat = [belief[r][c] for r in range(grid_size) for c in range(grid_size) if (r, c) not in barriers]
    peak = max(flat, default=0.0)
    peak_cells = {(r, c) for r in range(grid_size) for c in range(grid_size) if peak > 0 and belief[r][c] == peak}

    cells = []
    for r in range(grid_size):
        for c in range(grid_size):
            is_barrier = (r, c) in barriers
            # A barrier can hold no belief mass by construction (domain/belief.py),
            # so it is painted as structure, never as heat.
            fill = BARRIER if is_barrier else heat_colour(belief[r][c] / peak if peak > 0 else 0.0)
            cells.append(
                CellPaint(
                    row=r,
                    col=c,
                    fill=fill,
                    barrier=is_barrier,
                    own=own is not None and (r, c) == tuple(own),
                    peak=not is_barrier and (r, c) in peak_cells,
                )
            )
    return Scene(
        grid_size=grid_size,
        cells=tuple(cells),
        hud=_hud(snapshot, peak, len(barriers)),
        title=str(snapshot.get("game_id", "")),
        footer=_footer(snapshot),
        legend=(
            ("own position", OWN_POLICE if role == "police" else OWN_THIEF),
            ("barrier", BARRIER),
            (f"{snapshot.get('heat_label', 'belief')}: cold", heat_colour(0.0)),
            ("hot", heat_colour(1.0)),
        ),
    )


def _hud(snapshot: dict, peak: float, barriers: int) -> tuple[tuple[str, str], ...]:
    turn = snapshot.get("whose_turn")
    role = snapshot.get("role", "?")
    mine = "MY TURN" if turn == role else "waiting for opponent"
    label = snapshot.get("heat_label", "belief")
    rows = [
        ("sub-game", str(snapshot.get("sub_game_number", "?"))),
        ("my role", role),
        ("turn", f"step {snapshot.get('step', '?')} - {mine}"),
        ("my position", str(tuple(snapshot["own_pos"])) if snapshot.get("own_pos") else "-"),
        ("barriers", str(barriers)),
        (f"{label} peak", f"{peak:.3f}"),
    ]
    if snapshot.get("action"):
        rows.append(("action", str(snapshot["action"])))
    return tuple(rows)


def _footer(snapshot: dict) -> str:
    result = snapshot.get("result")
    if result:
        return f"FINISHED - {result}"
    # Said plainly, because a viewer that looked like it knew where the
    # opponent was would misrepresent the entire protocol.
    label = snapshot.get("heat_label", "belief")
    return f"opponent position is NOT known - the heatmap is this agent's {label}"
