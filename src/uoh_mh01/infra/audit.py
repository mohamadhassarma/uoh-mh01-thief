"""The mutual post-sub-game audit (PRD-03 / book ch.5.4), reshaped to the
contract (docs/WIRE.md §5).

The opponent reveals its FULL sealed chain — `[{payload, nonce, commit}]` —
and we re-hash every record with our own serializer. The recomputed hash is
compared against **the commit that actually arrived live**, not against the
`commit` field inside the revealed record, which the revealer could have
rewritten after the fact (interop kit WARNINGS §5d).

This is a DELETION relative to the previous design. We used to reconstruct the
opponent's sealed payload ourselves, from our mirrored copy of their move, and
verify against that. With no mirror there is nothing to reconstruct — and
nothing needs reconstructing, because the payload now arrives in the reveal.
`receiver_helpers.sender_position` and the whole opponent-side payload
rebuild are gone with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.crypto import commit_of

# The disclosure-only spec record. Never transmitted as a turn, so it can only
# ever be checked for self-consistency — see verify_revealed.
STEP_ZERO = 0


@dataclass(frozen=True)
class AuditResult:
    passed: bool
    verified_steps: int
    failed_steps: tuple[int, ...] = ()
    # Why a verdict was reached, recorded in the log artifact. Only ever set
    # for a FAILURE — a pass needs no excuse.
    reason: str | None = None


@dataclass
class ReceivedCommitLog:
    """The opponent's live-received commits, keyed by their step number.

    Only the commit is stored: it is the one thing that crossed the wire
    during play and the one thing the reveal must be checked against."""

    by_step: dict[int, str] = field(default_factory=dict)

    def record(self, step: int, commit: str) -> None:
        self.by_step[step] = commit


def verify_revealed(
    revealed: list[dict[str, Any]],
    received: ReceivedCommitLog,
    *,
    steps_played: int | None = None,
) -> AuditResult:
    """`revealed` is the opponent's full chain: `[{payload, nonce, commit}]`.

    A record fails if its payload+nonce does not re-hash to the commit we saw
    live. A step we hold a live commit for but that was never revealed also
    fails — a disclosure that quietly drops a step is exactly as suspicious as
    one that fails to re-hash.

    THE VERDICT FLOOR (PRD-06 hardening). "No failures" is NOT sufficient for a
    pass. An audit that verified nothing at all trivially has no failures, and
    that is exactly what a broken peer produces: when `legal_actions` crashed on
    every turn, both sides sealed zero records, exchanged empty reveals, and
    each reported `passed=True, verified_steps=0` — a vacuous green that looked
    identical to a clean game. A pass now additionally requires:

      * `verified_steps > 0`, and
      * `verified_steps == steps_played` (defaulting to the number of steps we
        actually saw commits for), so a reveal that explains only some of the
        turns it played cannot pass either.
    """
    expected = len(received.by_step) if steps_played is None else steps_played
    failed: list[int] = []
    verified = 0
    revealed_steps: set[int] = set()

    for record in revealed:
        payload = record.get("payload")
        nonce = record.get("nonce")
        if not isinstance(payload, dict) or not isinstance(nonce, str):
            failed.append(int(record.get("step", -1)))
            continue
        step = int(payload.get("step", record.get("step", -1)))
        recomputed = commit_of(payload, nonce)

        if step == STEP_ZERO:
            # STEP 0 IS DISCLOSURE-ONLY. The sealed step-0 record (the host
            # spec / model declaration) is never transmitted as a turn — it is
            # revealed for the first time inside submit_audit
            # (interop kit SPEC §7.5 `not_on_this_wire`, vectors/turn_message.json).
            # So there is no live commit to compare it against and demanding
            # one is simply wrong: all that can be checked is that the record
            # is self-consistent. Found live against the kit's sparring peer,
            # which reveals a step 0 and which we were failing for it.
            if recomputed != record.get("commit"):
                failed.append(step)
            continue

        revealed_steps.add(step)
        live_commit = received.by_step.get(step)
        if live_commit is None or recomputed != live_commit:
            failed.append(step)
        else:
            verified += 1

    failed.extend(sorted(set(received.by_step) - revealed_steps))
    failed_steps = tuple(sorted(set(failed)))

    reason = None
    if failed_steps:
        reason = f"{len(failed_steps)} step(s) failed to verify: {list(failed_steps)}"
    elif verified == 0:
        reason = "no steps verified at all — an empty reveal cannot pass"
    elif verified != expected:
        reason = f"verified {verified} step(s) but {expected} were played"

    return AuditResult(
        passed=reason is None,
        verified_steps=verified,
        failed_steps=failed_steps,
        reason=reason,
    )
