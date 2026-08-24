"""Rebuilding viewer frames from a finished sub-game log.

A sealed record carries `state` ("grid=7x7;self=[1, 0];barriers=[[2, 1]]") and
the `smell_grid` this agent transmitted that turn, so a played sub-game can be
redrawn from the artifact alone - the same picture the live viewer draws, from
a series that really happened.

THE HEAT LAYER IS NOT THE SAME QUANTITY IN BOTH MODES, and the frames say so
rather than quietly reusing the word "belief". Live, it is this agent's belief
about where the OPPONENT is. In a replay it is this agent's OWN transmitted
scent field, because that is what the log contains: belief is internal state
and was never sealed, so no replay can honestly claim to show it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STATE_PATTERN = re.compile(r"grid=(\d+)x(\d+);self=(\[[^\]]*\]);barriers=(\[.*\])\s*$")
HEAT_LABEL = "own scent"


def parse_state(state: str) -> dict[str, Any] | None:
    """`grid=7x7;self=[1, 0];barriers=[[2, 1]]` -> its parts, or None."""
    match = STATE_PATTERN.match(state.strip())
    if match is None:
        return None
    try:
        own = json.loads(match.group(3))
        barriers = json.loads(match.group(4))
    except ValueError:
        return None
    return {"grid_size": int(match.group(1)), "own_pos": own, "barriers": barriers}


def _heat_grid(smell: dict[str, float] | None, size: int) -> list[list[float]]:
    grid = [[0.0] * size for _ in range(size)]
    for key, value in (smell or {}).items():
        try:
            row, col = (int(part) for part in key.split(","))
        except ValueError:
            continue
        if 0 <= row < size and 0 <= col < size:
            grid[row][col] = float(value)
    return grid


def frames_from_log(log: dict[str, Any]) -> list[dict[str, Any]]:
    """Every playable turn in this sub-game, oldest first.

    Step 0 produces no frame: it is the host-spec declaration, carries no
    position and was never a turn (infra/audit.py). It is still verified by the
    replay verifier - it is simply not something to draw.
    """
    summary = log.get("summary", {})
    frames = []
    for record in log.get("records", []):
        payload = record.get("payload", {})
        parsed = parse_state(payload.get("state", "")) if isinstance(payload.get("state"), str) else None
        if parsed is None:
            continue
        size = parsed["grid_size"]
        frames.append(
            {
                "schema_version": "1.0",
                "game_id": log.get("game_id", ""),
                "game_uid": log.get("game_uid", ""),
                "sub_game_number": summary.get("sub_game_number", 0),
                "role": payload.get("role", summary.get("role", "?")),
                "group_id": summary.get("group_id", "?"),
                "step": payload.get("step", 0),
                # A replay is a record of MY turns only, so every frame is one.
                "whose_turn": payload.get("role", summary.get("role", "?")),
                "grid_size": size,
                "own_pos": parsed["own_pos"],
                "barriers": parsed["barriers"],
                "belief": _heat_grid(payload.get("smell_grid"), size),
                "heat_label": HEAT_LABEL,
                "action": f"{payload.get('action_type', '?')} {payload.get('detail', '')}".strip(),
                "result": None,
            }
        )
    if frames:
        frames[-1]["result"] = summary.get("result")
    return frames


def load_frames(logs_dir: Path, game_id: str, sub_game_number: int) -> list[dict[str, Any]]:
    path = Path(logs_dir) / f"log_{game_id}_g{sub_game_number:02d}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no sub-game log at {path}")
    return frames_from_log(json.loads(path.read_text(encoding="utf-8")))
