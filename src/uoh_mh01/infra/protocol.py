"""The wire schema import site.

`MoveRequest` is DELETED. It was this engine's own invented message shape —
`action_type`/`direction`/`target_row`/`target_col` plus action counters — and
it put the mover's move on the wire in the clear, which the contract
explicitly does not (docs/WIRE.md §2.1). Everything it fed went with it:
`protocol_builders`, `protocol_response` (`MoveResponse`/`TerminalInfo`) and
`turn_resolver`, none of which has a counterpart once every tool is ack-only.

What remains is the contract shape, re-exported here so `infra.protocol` stays
the single import site for it.
"""

from __future__ import annotations

from .protocol_errors import ProtocolError
from .turn_message import TurnMessage, validate_turn_message

TOOL_NAME = "receive_turn"

__all__ = ["TOOL_NAME", "ProtocolError", "TurnMessage", "validate_turn_message"]
