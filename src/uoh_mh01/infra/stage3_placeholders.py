"""Stage-2 stand-ins for stage 3's real commit-reveal cryptography.

Kept in their own tiny module (rather than orchestrator.py) purely to keep
file sizes down. `tests/test_orchestrator.py::test_stage3_placeholders_still_present`
is the guard: it fails on purpose once these are removed without a real
replacement landing alongside the removal.
"""

from __future__ import annotations

from typing import Any

from ..domain.match import Action
from .protocol_response import MoveResponse


def commit(action: Action) -> dict[str, Any]:
    """Stand-in for stage 3's real SHA-256 commit-reveal. Passes the move
    through UNHASHED — there is nothing hidden yet, so "commit" here is only
    a shape, not a cryptographic commitment.

    TODO(stage-3): replace with a real hash commitment (hash(move + nonce)),
    sent to the opponent as its own message BEFORE the reveal, and remove
    this placeholder.
    """
    return {"unhashed_action": action}


def verify(commit_value: dict[str, Any], response: MoveResponse) -> bool:
    """Stand-in for stage 3's real reveal-matches-commit verification.
    Always verifies true — there is no hash to check against yet.

    TODO(stage-3): replace with a real hash-match check (does the revealed
    move hash to the same value that was committed earlier?) and remove this
    placeholder. See commit()'s docstring.
    """
    return True
