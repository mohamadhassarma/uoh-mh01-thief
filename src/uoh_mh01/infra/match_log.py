"""Builds logs/<role>_match.json for stage 6's replay viewer.

Deliberately kept separate from domain.state.LogEntry: the domain log entry
is pure and replay-deterministic (no wall-clock data, since replay must be
able to reconstruct the SAME entries from the SAME move sequence). Real
timestamps are inherently non-deterministic wall-clock data, so they live
only in this infra-level wrapper, never in domain/. "Deterministic" here
means the STRUCTURE and CONTENT (every action, every phase transition, the
final terminal condition and score) is complete and unambiguous — not that
two runs produce byte-identical files, which no timestamped log ever could.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..domain.own_state import OwnStepEntry  # noqa: F401  (documents the entry shape record_action expects)
from .state_machine import Phase


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class MatchLogRecorder:
    role: str
    group_id: str
    started_at: str = field(default_factory=_now_iso)
    moves: list[dict[str, Any]] = field(default_factory=list)
    phase_transitions: list[dict[str, Any]] = field(default_factory=list)
    finished_at: str | None = None
    terminal: dict[str, Any] | None = None
    undefined_outcome: str | None = None
    disputed: dict[str, Any] | None = None
    unconfirmed_claim: str | None = None

    def record_action(self, entry, actor) -> None:
        """Records one of MY OWN steps. `own_pos` only: this peer never holds
        the opponent's position, so there is nothing else it could honestly
        write here (docs/WIRE.md §2.1)."""
        self.moves.append(
            {
                "timestamp": _now_iso(),
                "step": entry.step,
                "actor": actor.value,
                "action_type": entry.action_type.value,
                "detail": entry.detail,
                "own_pos": [entry.resulting_own_pos.row, entry.resulting_own_pos.col],
                "barrier_placed": (
                    [entry.barrier_placed.row, entry.barrier_placed.col] if entry.barrier_placed else None
                ),
            }
        )

    def record_phase(self, phase: Phase) -> None:
        self.phase_transitions.append({"timestamp": _now_iso(), "phase": phase.value})

    def finalize(
        self,
        *,
        condition: str | None,
        police_score: int | None,
        thief_score: int | None,
        offending_side: str | None = None,
        undefined_outcome: str | None = None,
        disputed: dict[str, Any] | None = None,
        unconfirmed_claim: str | None = None,
    ) -> None:
        self.finished_at = _now_iso()
        self.undefined_outcome = undefined_outcome
        self.disputed = disputed
        self.unconfirmed_claim = unconfirmed_claim
        if condition is not None:
            self.terminal = {
                "condition": condition,
                "police_score": police_score,
                "thief_score": thief_score,
                "offending_side": offending_side,
            }

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "group_id": self.group_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "moves": self.moves,
            "phase_transitions": self.phase_transitions,
            "terminal": self.terminal,
            "undefined_outcome": self.undefined_outcome,
            "disputed": self.disputed,
            "unconfirmed_claim": self.unconfirmed_claim,
        }

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
