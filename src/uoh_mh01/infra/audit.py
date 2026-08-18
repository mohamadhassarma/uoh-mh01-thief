"""The mutual post-sub-game audit (PRD-03 / book ch.5.4): each side reveals
its own nonces; the OPPONENT re-hashes against the commit+payload it
already received LIVE during play — never against a copy the revealer
could rewrite after the fact (interop kit WARNINGS §5d: "audit against the
commitment that arrived, not the one in the record").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.crypto import verify


@dataclass(frozen=True)
class AuditResult:
    passed: bool
    verified_steps: int
    failed_steps: tuple[int, ...] = ()


@dataclass
class ReceivedCommitLog:
    """One side's own live-received (payload, commit) pairs, keyed by step —
    the archive `verify_revealed` audits the opponent's later reveal
    against. Populated as messages arrive, never edited afterwards."""

    by_step: dict[int, dict[str, Any]] = field(default_factory=dict)

    def record(self, step: int, payload: dict[str, Any], commit: str) -> None:
        self.by_step[step] = {"payload": payload, "commit": commit}


def verify_revealed(revealed: list[dict[str, Any]], received: ReceivedCommitLog) -> AuditResult:
    """`revealed` is the opponent's own list of `{"step": int, "nonce": str}`.
    A step we hold a live commit for but that was never revealed is also a
    failure — a disclosure that quietly drops a step is exactly as
    suspicious as one that fails to re-hash."""
    revealed_steps = {item["step"] for item in revealed}
    failed: list[int] = []
    verified = 0

    for item in revealed:
        step, nonce = item["step"], item["nonce"]
        entry = received.by_step.get(step)
        if entry is None or not verify(entry["payload"], nonce, entry["commit"]):
            failed.append(step)
        else:
            verified += 1

    missing = set(received.by_step) - revealed_steps
    failed.extend(sorted(missing))

    return AuditResult(passed=not failed, verified_steps=verified, failed_steps=tuple(sorted(set(failed))))
