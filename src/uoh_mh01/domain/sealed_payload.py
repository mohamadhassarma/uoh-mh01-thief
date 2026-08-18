"""What actually goes inside a sealed commit-reveal record (PRD-03).

Deliberately minimal compared to the reference's own richer record (hint,
verdict, prompt_discussion, tokens): stage 5's verbal layer does not exist
yet in this codebase, so this payload carries only what stage 3 actually
has — never a faked `intent`/`hint` field standing in for a layer that
isn't built. Extending this dict is stage 5's job, not stage 3's.
"""

from __future__ import annotations

from typing import Any

from .board import Position


def state_str(grid_size: int, position: Position, barriers: frozenset[Position]) -> str:
    """Self-only state string, matching the reference's own `_state_str`
    convention (`grid=NxN;self=[r, c];barriers=[...]`) — carries the acting
    side's OWN position, never the opponent's, so this shape stays correct
    once stage 4 introduces a real hidden-position model."""
    sorted_barriers = sorted([b.row, b.col] for b in barriers)
    return f"grid={grid_size}x{grid_size};self={[position.row, position.col]};barriers={sorted_barriers}"


def build_move_payload(*, step: int, role: str, action_type: str, detail: str, state: str) -> dict[str, Any]:
    return {"step": step, "role": role, "action_type": action_type, "detail": detail, "state": state}


def build_step_zero_payload(*, spec: dict[str, Any], code_version: str, group_name: str, sub_game_number: int) -> dict[str, Any]:
    """Rule #53 (verified against the book PDF, Table 12): the step-zero
    declaration seals the host spec AND the commit hash that was played,
    refreshed every sub-game — see PRD-03."""
    return {
        "step": 0,
        "type": "system_spec",
        "spec": spec,
        "code_version": code_version,
        "group_name": group_name,
        "sub_game_number": sub_game_number,
    }
