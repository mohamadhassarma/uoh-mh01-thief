"""`ProtocolError`, in its own module so both the legacy `MoveRequest` schema
(protocol.py) and the contract `TurnMessage` schema (turn_message.py) raise the
SAME class without an import cycle.

Two same-named exception classes in two modules would make
`pytest.raises(ProtocolError)` pass or fail depending on which one was imported
— a silent, confusing failure. Matches the existing `domain/config_errors.py`
and `shared/peer_config_errors.py` convention.
"""

from __future__ import annotations


class ProtocolError(Exception):
    """A malformed request/response payload — a wire-schema problem, not a
    game-rule illegality (domain.rules is what decides legality)."""
