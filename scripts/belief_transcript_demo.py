"""PRD-04 report artifact: a full sub-game transcript showing the belief
map sharpen over the real thief's own scent trail — at the REAL signed
contract values (grid_size=7, max_moves=35, survival_threshold=35,
pheromone params 0.9/0.1/5), not shrunk for speed.

Domain-level demonstration, not a shipped module: exercises exactly the
production functions (`domain.scent.emit`/`advance_field`,
`domain.belief.update_from_scent`) the real per-turn wire path calls
(`infra/turn_sender.py`, `infra/turn_receiver.py`), without the network/MCP
machinery around them — belief has no artifact or GUI hook yet (that is
stage 6's job), so this is how the property is shown for this stage's
report. The police's belief is fed ONLY the thief's own transmitted scent
field, exactly as the real wire does; the printed "true thief cell" column
is for this script's own verification output only, never fed back into the
belief update itself.

Also reports the argmax-accuracy baseline PRD-05 needs (its own "belief
ceiling" problem statement): what fraction of turns is the belief map's
argmax within 1 / within 2 cells (Manhattan distance — the game's own move
metric; there are no diagonal moves) of the thief's true cell. This is a
BASELINE for stage 5 to beat, not a target this stage claims to hit.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from uoh_mh01.domain.belief import initial_belief, reachable_cells, update_from_scent
from uoh_mh01.domain.board import Board, Direction, Position
from uoh_mh01.domain.config import parse_config
from uoh_mh01.domain.rules import legal_moves
from uoh_mh01.domain.scent import advance_field, emit

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    raw = json.loads((REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8"))
    config = parse_config(raw)
    rng = random.Random(7)

    board = Board(grid_size=config.board.grid_size)
    thief_pos = Position(*config.board.thief_start)
    thief_field: dict = {}
    belief = initial_belief(board)

    print(f"grid_size={config.board.grid_size} max_moves={config.movement.max_moves} "
          f"survival_threshold={config.movement.survival_threshold} "
          f"pheromones=(center={config.pheromones.center_intensity}, decay={config.pheromones.decay}, "
          f"field={config.pheromones.grid_size})")
    print(f"{'turn':>4}  {'thief_true':>10}  {'belief_argmax':>13}  {'p(argmax)':>9}  {'p(true_cell)':>12}  {'dist':>4}")

    within_1 = 0
    within_2 = 0
    total = config.movement.survival_threshold

    for turn in range(1, total + 1):
        # The thief takes one real, legal action (random walk among legal
        # moves) — the same domain.rules the actual engine's turn loop uses.
        options = legal_moves(board, thief_pos, config.movement)
        direction = rng.choice(list(options))
        if direction is not Direction.STAY:
            from uoh_mh01.domain.board import delta_for

            thief_pos = thief_pos + delta_for(direction)

        # The thief emits + decays its OWN trail — infra/turn_sender.py's
        # real per-own-turn cadence.
        deposit = emit(thief_pos, board, config.pheromones)
        thief_field = advance_field(thief_field, deposit, config.pheromones)

        # The police receives that transmitted field and folds it into
        # belief — infra/turn_receiver.py's real absorption step. The
        # police is NEVER given thief_pos itself.
        belief = update_from_scent(belief, thief_field, board)

        argmax_cell = max(reachable_cells(board), key=lambda p: belief[p])
        dist = abs(argmax_cell.row - thief_pos.row) + abs(argmax_cell.col - thief_pos.col)
        within_1 += dist <= 1
        within_2 += dist <= 2
        print(
            f"{turn:>4}  {str(thief_pos):>10}  {str(argmax_cell):>13}  "
            f"{belief[argmax_cell]:>9.4f}  {belief[thief_pos]:>12.4f}  {dist:>4}"
        )

    print(
        f"\nargmax within 1 cell of truth (Manhattan): {within_1}/{total} "
        f"({100 * within_1 / total:.1f}%)"
    )
    print(
        f"argmax within 2 cells of truth (Manhattan): {within_2}/{total} "
        f"({100 * within_2 / total:.1f}%)"
    )


if __name__ == "__main__":
    main()
