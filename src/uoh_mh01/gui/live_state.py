"""The live snapshot the running peer publishes and the viewer reads.

DELIBERATELY A FILE, NOT A CALLBACK OR A THREAD. The viewer is a separate
process that polls; the peer only ever writes. Two reasons, and the second is
the important one:

  * Tk wants the main thread and a `mainloop`; the peer is an asyncio server.
    Running both in one process means a thread bridge, which is exactly the
    kind of thing that works until the night it matters.
  * A COUNTED SERIES MUST NOT BE ENDANGERED BY THE VIEWER. A GUI that crashes,
    blocks on a redraw, or is closed mid-game cannot affect a game it is not
    part of. `publish` swallows everything for the same reason: no failure to
    draw a picture is worth forfeiting a game over.

Writes go to a temp file and are then replaced onto the real path, so a viewer
polling mid-write reads the previous complete snapshot rather than half of the
next one.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LIVE_STATE_NAME = "live_state.json"
SCHEMA_VERSION = "1.0"


def snapshot_of(runtime: Any, *, game_id: str = "", game_uid: str = "") -> dict[str, Any]:
    """Build the snapshot from a `PeerRuntime`. Reads only; changes nothing."""
    state = runtime.state
    board = state.board
    size = board.grid_size
    belief = getattr(runtime, "_belief", {}) or {}
    grid = [[0.0] * size for _ in range(size)]
    for pos, mass in belief.items():
        if 0 <= pos.row < size and 0 <= pos.col < size:
            grid[pos.row][pos.col] = float(mass)
    outcome = getattr(runtime, "outcome", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "game_id": game_id,
        "game_uid": game_uid,
        "sub_game_number": runtime.sub_game_number,
        "role": runtime.role.value,
        "group_id": runtime.peer_config.group_id,
        "step": state.step_number,
        "whose_turn": runtime.whose_turn.value,
        "grid_size": size,
        "own_pos": [state.own_pos.row, state.own_pos.col],
        "barriers": sorted([pos.row, pos.col] for pos in board.barriers),
        "belief": grid,
        "result": outcome.terminal_condition.value if outcome else None,
    }


class LiveStatePublisher:
    """Writes a snapshot when something a viewer would notice has changed."""

    def __init__(self, path: Path, *, game_id: str = "", game_uid: str = "") -> None:
        self.path = Path(path)
        self.game_id = game_id
        self.game_uid = game_uid
        self._last_key: tuple | None = None

    def publish(self, runtime: Any) -> None:
        try:
            snapshot = snapshot_of(runtime, game_id=self.game_id, game_uid=self.game_uid)
            # The match loop spins while polling for the opponent; without this
            # the file would be rewritten thousands of times a turn.
            key = (snapshot["sub_game_number"], snapshot["step"], snapshot["whose_turn"], snapshot["result"])
            if key == self._last_key:
                return
            self._last_key = key
            write(self.path, snapshot)
        except Exception:  # noqa: BLE001 - a viewer must never cost us a game
            logger.debug("could not publish live state", exc_info=True)


def write(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read(path: Path) -> dict[str, Any] | None:
    """The latest snapshot, or None if there is not a complete one yet."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
