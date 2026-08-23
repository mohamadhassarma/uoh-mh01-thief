"""The in-game turn-exchange message — the contract in `docs/WIRE.md` §2/§3.

Ten keys, six required, extracted from the professor's reference implementation
(`ref_impl/src/police_thief/domain/protocol.py:12-40`, authoritative) and
cross-checked against the interop kit's `vectors/turn_message.json`.

THE MOVE IS NOT ON THIS WIRE. Position, direction and verdict are sealed inside
`commit` and disclosed only at the end-of-game audit (reference `protocol.py:16-18`).
Whatever this project's internal engine needs is a separate concern; nothing may
leak into `to_wire()`.

Strictness is deliberately ASYMMETRIC (`docs/WIRE.md` §4):

- **Emitting** is exact: `to_wire()` produces those ten keys and nothing else,
  with a real non-empty timestamp.
- **Receiving** is tolerant: `from_wire()` ignores unknown keys, and
  `validate_turn_message(..., strict=False)` accepts an empty timestamp.
  Each tolerance is justified inline against the source line it deviates from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .protocol_errors import ProtocolError

REQUIRED_FIELDS = ("step", "sender", "hint", "smell_grid", "commit", "timestamp")
OPTIONAL_FIELDS = ("barrier_placed", "capture_claim", "claim_response", "win_claim")
WIRE_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

_SENDERS = frozenset({"police", "thief"})
_COMMIT_RE = re.compile(r"^[0-9a-f]{64}$")
_CELL_RE = re.compile(r"^\d+,\d+$")

__all__ = ["WIRE_FIELDS", "ProtocolError", "TurnMessage", "now_iso", "validate_turn_message"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class TurnMessage:
    step: int
    sender: str
    hint: str
    smell_grid: dict[str, float]
    commit: str
    timestamp: str
    barrier_placed: list[int] | None = None
    capture_claim: list[int] | None = None
    claim_response: dict[str, Any] | None = None
    win_claim: dict[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        """Exactly the ten contract keys, nulls explicit — matching the
        reference's `asdict()` output shape (`ref_impl` `protocol.py:31-32`)
        and the kit's "nulls explicit" accept case."""
        return {name: getattr(self, name) for name in WIRE_FIELDS}


def _fail(field: str, requirement: str) -> None:
    raise ProtocolError(f"{field}: {requirement}")


def _check_cell(field: str, value: Any) -> None:
    if value is None:
        return
    ok = (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(c, int) and not isinstance(c, bool) for c in value)
    )
    if not ok:
        _fail(field, "required [row, col] pair of ints, or null")


def validate_turn_message(message: Any, *, strict: bool = True) -> None:
    """Raise `ProtocolError` unless `message` satisfies the contract.

    Runs BEFORE any state change: an inbound turn is adversarial input and a
    partially applied bad turn cannot be rolled back (kit
    `vectors/turn_message.json` -> `validate_before_applying`).

    `strict=False` applies the documented receive-side tolerance — see
    `docs/WIRE.md` §4 and the `timestamp` branch below.
    """
    if not isinstance(message, dict):
        _fail("message", f"required object, got {type(message).__name__}")

    missing = [name for name in REQUIRED_FIELDS if name not in message]
    if missing:
        # Never defaulted: "a defaulted commit is a move the sender never
        # sealed" (kit vectors/turn_message.json, validation case 4).
        _fail(", ".join(missing), "required, and never defaulted")

    step = message["step"]
    if not isinstance(step, int) or isinstance(step, bool) or step < 0:
        _fail("step", "required non-negative int")

    if message["sender"] not in _SENDERS:
        _fail("sender", "required 'police' or 'thief'")

    if not isinstance(message["hint"], str):
        _fail("hint", "required str (may be empty, and may be a lie)")

    grid = message["smell_grid"]
    if not isinstance(grid, dict):
        _fail("smell_grid", "required dict of 'r,c' -> number")
    for key, value in grid.items():
        # A stringified intensity survives JSON and poisons the physics check
        # (kit validation case 6), so numbers are enforced, not coerced.
        if not isinstance(key, str) or not _CELL_RE.match(key):
            _fail("smell_grid", f"key {key!r} must be 'row,col'")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("smell_grid", f"value for {key!r} must be a number, got {type(value).__name__}")

    commit = message["commit"]
    # Compared as a string, so case is a divergence: uppercase hex is refused
    # (kit validation case 5).
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        _fail("commit", "required 64-char lowercase hex")

    timestamp = message["timestamp"]
    if not isinstance(timestamp, str):
        _fail("timestamp", "required str")
    if strict and not timestamp.strip():
        # TOLERANCE (receive side, strict=False): the contract refuses an empty
        # timestamp (kit validation case 3) — but that fixture also records that
        # the kit's OWN sparring peer emits `timestamp: ""`, so a strict
        # receiver rejects every one of its turns. We refuse it when emitting
        # and when validating our own output, and accept it inbound so a real
        # opponent is not unplayable over a decorative field. Deviates from:
        # interop_kit/vectors/turn_message.json validation case 3.
        _fail("timestamp", "required non-empty str")

    _check_cell("barrier_placed", message.get("barrier_placed"))
    _check_cell("capture_claim", message.get("capture_claim"))
    for name in ("claim_response", "win_claim"):
        value = message.get(name)
        if value is not None and not isinstance(value, dict):
            _fail(name, "required object, or null")
