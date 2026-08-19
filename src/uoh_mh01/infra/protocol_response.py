"""The response half of the wire contract — split out of protocol.py to keep
files under the project's ~150-line budget. See protocol.py's module
docstring for the full context; this half is the RECEIVER's answer to a
`receive_turn` call, never the sender's own claim reflected back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TerminalInfo:
    condition: str
    police_score: int
    thief_score: int
    offending_side: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "police_score": self.police_score,
            "thief_score": self.thief_score,
            "offending_side": self.offending_side,
        }

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> TerminalInfo | None:
        if d is None:
            return None
        return TerminalInfo(
            condition=d["condition"],
            police_score=d["police_score"],
            thief_score=d["thief_score"],
            offending_side=d.get("offending_side"),
        )


@dataclass(frozen=True)
class MoveResponse:
    accepted: bool
    reason: str | None = None
    # The RECEIVER's own, independently-derived verdict — never a copy of
    # the sender's claim. `None` means "the receiver's own state says play
    # continues".
    terminal: TerminalInfo | None = None
    # None: the sender made no claim to agree or disagree with. True/False:
    # whether the receiver's own independent verdict matches the sender's
    # claimed_condition/claimed_offending_side. False is a genuine dispute —
    # see PRD-02 "Stage 2 corrections" B1 — never silently resolved.
    claim_agreement: bool | None = None
    # Set instead of an ordinary `reason` when the request was rejected
    # because the sender's claimed action counters didn't match the
    # receiver's own local counts (PRD-02 "Stage 2 corrections" B2).
    divergence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "terminal": self.terminal.to_dict() if self.terminal is not None else None,
            "claim_agreement": self.claim_agreement,
            "divergence": self.divergence,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> MoveResponse:
        return MoveResponse(
            accepted=d["accepted"],
            reason=d.get("reason"),
            terminal=TerminalInfo.from_dict(d.get("terminal")),
            claim_agreement=d.get("claim_agreement"),
            divergence=d.get("divergence"),
        )
