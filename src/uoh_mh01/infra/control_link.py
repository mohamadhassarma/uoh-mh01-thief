"""The optional `receive_control` channel (docs/WIRE.md §6), now PARTICIPATED
IN rather than acked and discarded.

Modelled on `ref_impl/src/police_thief/peer/control_link.py`. Two properties
make it safe to wire into a live game loop:

  * **Opt-in both ways.** The channel is ACTIVE only once both peers have sent
    `kind="enable"`. Omission never refuses — an opponent that implements none
    of this is completely unaffected, which is what SPEC §7.5 means by listing
    the tool OPTIONAL.
  * **Advisory only.** Nothing here is sealed, scored, or allowed to change a
    game outcome. Sends are best-effort with errors suppressed and reads are
    non-blocking, so a slow or departed opponent can never stall the turn loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

WAITING, THINKING, PLAYING = "WAITING", "THINKING", "PLAYING"
GAME_OVER, QUIT = "GAME_OVER", "QUIT"

_KINDS = frozenset({"enable", "status", "restart", "quit"})


def build_control_message(
    kind: str, sender: str, *, sub_game_number: int = 1, status: str = "", step_budget: float = 0.0
) -> dict[str, Any]:
    """The contract ControlMessage: `kind`/`sender` required, the rest
    optional (docs/WIRE.md §6)."""
    return {
        "kind": kind,
        "sender": sender,
        "sub_game_number": sub_game_number,
        "status": status,
        "step_budget": step_budget,
        "payload": None,
    }


@dataclass
class ControlLink:
    """One peer's side of the channel. Pure state plus message interpretation —
    no I/O, so it is fully unit-testable."""

    role: str
    i_enabled: bool = False
    peer_enabled: bool = False
    opponent: dict[str, Any] = field(default_factory=lambda: {"status": "-", "sub_game_number": None})
    opponent_quit: bool = False
    _last_status: str | None = None

    @property
    def active(self) -> bool:
        """True only once BOTH sides have opted in."""
        return self.i_enabled and self.peer_enabled

    def enable(self) -> dict[str, Any]:
        self.i_enabled = True
        return build_control_message("enable", self.role)

    def status_update(self, status: str, *, sub_game_number: int, step_budget: float = 0.0) -> dict[str, Any] | None:
        """A status message to send, or None if there is nothing new to say.
        Only-on-change, so the channel never spams the wire."""
        if not self.i_enabled or status == self._last_status:
            return None
        self._last_status = status
        return build_control_message(
            "status", self.role, sub_game_number=sub_game_number, status=status, step_budget=step_budget
        )

    def handle(self, message: dict[str, Any]) -> None:
        """Fold one inbound control message in. Unknown kinds are ignored, not
        refused — this channel must never be a reason a game fails."""
        kind = message.get("kind")
        if kind not in _KINDS:
            logger.debug("ignored unknown control kind %r", kind)
            return
        if kind == "enable":
            self.peer_enabled = True
        elif kind == "status":
            self.opponent = {
                "status": message.get("status", "-"),
                "sub_game_number": message.get("sub_game_number"),
                "step_budget": message.get("step_budget"),
            }
        elif kind == "quit":
            self.opponent["status"] = QUIT
            self.opponent_quit = True
        elif kind == "restart":
            # Auto-approved only when both sides enabled, matching the
            # reference. We record it; the series loop decides what to do.
            logger.info("opponent requested a restart (granted=%s)", self.active)
