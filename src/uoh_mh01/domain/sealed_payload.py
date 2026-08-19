"""What actually goes inside a sealed commit-reveal record (PRD-03).

PRD-05 adds `hint` and `hint_is_true` to the sealed shape: the hint text
AND the sender's own self-declared truth/lie verdict on it are both inside
the same commit-reveal umbrella as everything else here, so a sender that
reveals either one differently from what it actually sent live is caught
by the EXISTING mutual-audit re-hash — "lying about whether you lied" is
not a new sanction path, just a consequence of sealing the verdict at all.
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


def build_move_payload(
    *,
    step: int,
    role: str,
    action_type: str,
    detail: str,
    state: str,
    smell_grid: dict[str, float] | None = None,
    hint: str = "",
    hint_is_true: bool | None = None,
) -> dict[str, Any]:
    # PRD-04: the scent field is part of the sealed record, not a side
    # channel — a grid that differs between what was actually sent live and
    # what gets revealed at audit is exactly the class of tampering
    # commit-reveal exists to catch. `None` (declare_terminal, or a stage-3
    # caller predating PRD-04) is normalized to `{}` so the sealed shape is
    # stable regardless of caller.
    return {
        "step": step,
        "role": role,
        "action_type": action_type,
        "detail": detail,
        "state": state,
        "smell_grid": smell_grid or {},
        "hint": hint,
        "hint_is_true": hint_is_true,
    }


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
