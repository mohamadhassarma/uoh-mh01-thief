"""Per-step commit-reveal sealing (PRD-03/PRD-04/PRD-05). Split out of
orchestrator.py purely to keep that file under the project's ~150-line
budget — a mixin, not a standalone class, so `PeerRuntime` keeps a single
ordinary method-call surface (`self._seal_own_record(...)`) even though the
implementation lives here.
"""

from __future__ import annotations

from typing import Any

from ..domain.crypto import seal
from ..domain.sealed_payload import build_move_payload, state_str
from ..domain.state import Side


class _SealingMixin:
    def _my_position(self) -> Any:
        return self.state.cop_pos if self.role is Side.POLICE else self.state.thief_pos

    def _seal_own_record(
        self,
        *,
        step: int,
        action_type: str,
        detail: str,
        smell_grid: dict[str, float] | None = None,
        hint: str = "",
        hint_is_true: bool | None = None,
    ) -> str:
        """Build this step's payload (self-only position, matching the
        book/reference `state` convention), seal it (PRD-03), and stash the
        full record locally for the post-sub-game audit reveal. Returns only
        the commit hash — the one thing that may go out on the wire now.

        `smell_grid` (PRD-04) and `hint`/`hint_is_true` (PRD-05) are sealed
        alongside the move so the opponent's audit re-hash catches any of
        them being quietly altered between what went out live and what
        gets revealed."""
        payload = build_move_payload(
            step=step,
            role=self.role.value,
            action_type=action_type,
            detail=detail,
            state=state_str(self.state.board.grid_size, self._my_position(), self.state.board.barriers),
            smell_grid=smell_grid,
            hint=hint,
            hint_is_true=hint_is_true,
        )
        sealed = seal(payload)
        self.own_sealed_records.append({"step": step, "payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]})
        return sealed["commit"]
