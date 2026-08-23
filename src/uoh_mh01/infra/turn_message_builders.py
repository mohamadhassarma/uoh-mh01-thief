"""Build and parse the contract `TurnMessage` (`docs/WIRE.md` §2/§4).

Split from turn_message.py purely to keep both files under the project's
~150-line budget. This is where the asymmetric strictness actually lives:
`build_turn_message` emits exactly the contract, `parse_turn_message` is
deliberately forgiving about what it accepts.
"""

from __future__ import annotations

from typing import Any

from .turn_message import (
    WIRE_FIELDS,
    ProtocolError,
    TurnMessage,
    now_iso,
    validate_turn_message,
)


def build_turn_message(
    *,
    step: int,
    sender: str,
    hint: str,
    smell_grid: dict[str, float],
    commit: str,
    timestamp: str | None = None,
    barrier_placed: list[int] | None = None,
    capture_claim: list[int] | None = None,
    claim_response: dict[str, Any] | None = None,
    win_claim: dict[str, Any] | None = None,
) -> TurnMessage:
    """EMIT side — exactly the contract, nothing extra.

    `timestamp` defaults to a real ISO-8601 stamp rather than the empty string:
    the kit's own sparring peer emits `""` and is refused by any strict
    receiver, and we decline to reproduce that bug on the way out. The result
    is validated STRICTLY before it can reach the wire, so a violation is
    caught here rather than by the opponent.
    """
    message = TurnMessage(
        step=step,
        sender=sender,
        hint=hint,
        smell_grid=dict(smell_grid or {}),
        commit=commit,
        timestamp=timestamp if timestamp is not None else now_iso(),
        barrier_placed=list(barrier_placed) if barrier_placed is not None else None,
        capture_claim=list(capture_claim) if capture_claim is not None else None,
        claim_response=claim_response,
        win_claim=win_claim,
    )
    validate_turn_message(message.to_wire(), strict=True)
    return message


def parse_turn_message(data: Any, *, strict: bool = False) -> TurnMessage:
    """RECEIVE side — tolerant by design.

    Two documented tolerances, each deviating from a named source line:

    1. UNKNOWN KEYS ARE IGNORED. Built by explicit field selection, never
       `cls(**data)`. The reference does use `cls(**data)`
       (ref_impl `domain/protocol.py:40`) and therefore REJECTS any unknown
       key; the kit's spec calls tolerance "the extension seam" and marks the
       unknown-key case `accept`
       (interop_kit/vectors/turn_message.json, validation case 2). This is the
       one place we deliberately follow the KIT over the reference: rejecting
       unknown keys cannot be extended without a flag day, and tolerating them
       costs us nothing since we read only the fields we know.

    2. EMPTY `timestamp` IS ACCEPTED (`strict=False`, the default here) —
       see the timestamp branch in turn_message.validate_turn_message for the
       full reasoning and the source line it deviates from.
    """
    if not isinstance(data, dict):
        raise ProtocolError(f"message: required object, got {type(data).__name__}")
    validate_turn_message(data, strict=strict)
    known = {name: data.get(name) for name in WIRE_FIELDS}
    return TurnMessage(**known)
