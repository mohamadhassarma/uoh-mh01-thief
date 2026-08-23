"""Per-step commit-reveal sealing (PRD-03/PRD-04/PRD-05). Split out of
orchestrator.py purely to keep that file under the project's ~150-line
budget — a mixin, not a standalone class, so `PeerRuntime` keeps a single
ordinary method-call surface (`self._seal_own_record(...)`) even though the
implementation lives here.
"""

from __future__ import annotations

from .. import __version__
from ..domain.crypto import seal
from ..domain.hints import enforce_word_cap
from ..domain.scent import advance_field, emit, serialize_field
from ..domain.sealed_payload import build_move_payload, build_step_zero_payload, state_str
from ..shared.sysinfo import collect_spec


class _SealingMixin:
    def seal_step_zero(self) -> dict:
        """Seal the step-0 host-spec declaration (rule #53 / book Table 12),
        refreshed every sub-game. Called ONCE per sub-game, before the first
        move.

        DISCLOSURE-ONLY, and that is the whole subtlety: this record is never
        transmitted as a turn, so the opponent sees it for the first time
        inside `submit_audit` and can only ever check it for self-consistency
        (infra/audit.py `STEP_ZERO`, kit SPEC §7.5 `not_on_this_wire`). It
        joins `own_sealed_records` and therefore the reveal — which is the
        point: a declaration nobody can re-hash is not a declaration.

        `build_step_zero_payload` has existed since PRD-03 and was never
        called. The gap was invisible from inside — our own audits passed
        without it because neither side emitted one — and surfaced only from
        the outside, when the kit's sparring peer revealed a step 0 we had no
        live commit for.
        """
        payload = build_step_zero_payload(
            spec=collect_spec(),
            code_version=__version__,
            group_name=self.peer_config.group_name,
            sub_game_number=self.sub_game_number,
        )
        sealed = seal(payload)
        record = {"step": 0, "payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]}
        self.own_sealed_records.append(record)
        return record

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
            state=state_str(self.state.board.grid_size, self.state.own_pos, self.state.board.barriers),
            smell_grid=smell_grid,
            hint=hint,
            hint_is_true=hint_is_true,
        )
        sealed = seal(payload)
        self.own_sealed_records.append({"step": step, "payload": payload, "nonce": sealed["nonce"], "commit": sealed["commit"]})
        return sealed["commit"]

    def _seal_step(self, entry, hint_override: str | None = None) -> tuple[str, dict, str, bool | None]:
        """Deposit my scent, seal this step, and return what goes on the wire."""
        deposit = emit(self.state.own_pos, self.state.board, self.config.pheromones)
        self._own_scent_field = advance_field(self._own_scent_field, deposit, self.config.pheromones)
        smell_grid = serialize_field(self._own_scent_field)
        hint_text, hint_is_true = getattr(self._strategy, "last_hint", ("", None))
        if hint_override is not None:
            hint_text, hint_is_true = hint_override, True
        hint_text = enforce_word_cap(hint_text, self.config.world.hint_max_words)
        commit = self._seal_own_record(
            step=entry.step,
            action_type=entry.action_type.value,
            detail=entry.detail,
            smell_grid=smell_grid,
            hint=hint_text,
            hint_is_true=hint_is_true,
        )
        return commit, smell_grid, hint_text, hint_is_true
