"""The wire contract between the two peers' MCP tools.

Pure geometric data plus terminal-condition claims — no strategy, no
cryptography, no natural language, per PRD-02's scope. Both mcp_server.py
and mcp_client.py import these shapes so a client-side call and the
server-side handler can never silently drift apart from each other.

`action_type == "declare_terminal"` is a move-shaped message that carries NO
move: it is how a side declares a terminal condition it detected WITHOUT
taking an action (entrapment, the max_moves ceiling — see
domain.terminal_detect). It deliberately reuses the same tool and the same
request/response shape as an ordinary move rather than inventing a second
tool, mirroring how the official reference's thief reuses its capture-claim
vocabulary for a rule-46/47 ending instead of a new message type.

Named `declare_terminal`, not `concede`: entrapment and the max_moves
ceiling are not concessions — entrapment in particular is a CAPTURE
(`capture_cop`/`capture_thief` scoring applies, the thief is caught, not
surrendering), and a string that misdescribes the outcome would appear
verbatim in the audit log and the result artifact, where both a grader and
an opponent's own verifier read it. Neither the reference implementation
nor the interop kit's SPEC name a generic "concede"/"declare" action type of
their own (both instead reuse existing field-level vocabulary —
`claim_response`/`win_claim` — rather than an action_type string), so this
name is this project's own neutral choice, not adopted from either source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOOL_NAME = "receive_turn"

_ACTION_TYPES = frozenset({"move", "barrier", "declare_terminal"})


class ProtocolError(Exception):
    """A malformed request/response payload — a wire-schema problem, not a
    game-rule illegality (domain.rules is what decides legality)."""


@dataclass(frozen=True)
class MoveRequest:
    role: str  # the MOVER's role: "police" | "thief"
    turn_number: int
    action_type: str  # "move" | "barrier" | "declare_terminal"
    direction: str | None = None  # required if action_type == "move"
    target_row: int | None = None  # required if action_type == "barrier"
    target_col: int | None = None  # required if action_type == "barrier"
    # The sender's own local police_actions_taken/thief_actions_taken AFTER
    # this action (unchanged, for "declare_terminal"). The receiver
    # recomputes its own counters independently and rejects on any
    # mismatch — see infra.turn_receiver and PRD-02 "Stage 2 corrections" B2.
    police_actions_taken: int = 0
    thief_actions_taken: int = 0
    # The sender's own claim about whether this message ends the match:
    # a TerminalCondition value, domain.terminal_detect.UNDEFINED_CEILING,
    # or None ("play continues, as far as I can tell"). Never trusted
    # outright — the receiver always recomputes and reports agreement.
    claimed_condition: str | None = None
    claimed_offending_side: str | None = None
    # PRD-03: the SHA-256 commit hash sealing this message's own payload
    # (never the nonce — that stays secret until the post-sub-game mutual
    # audit). Empty string for stage-2-only tests that don't exercise
    # real crypto; a real peer always sends a non-empty commit.
    commit: str = ""
    # PRD-03: which sub-game of the series this move belongs to (interop kit
    # SPEC §7.2's pairing-declaration pattern, applied here to receive_turn
    # too). The two peers' series loops are not perfectly wall-clock
    # synchronized between sub-games — the receiver uses this to wait for
    # (rather than misattribute to the wrong sub-game, or flatly reject) a
    # message that legitimately arrived slightly early.
    sub_game_number: int = 1
    # PRD-04: this sender's own current scent field, `{"row,col": intensity}`
    # (domain/scent.py's `serialize_field`) — sent live alongside the move,
    # same as the direction/target fields, and sealed into the same commit
    # (domain/sealed_payload.py) so a grid that differs between what was
    # sent and what was later revealed is a tamper finding, not silently
    # accepted. Empty for declare_terminal (no position change to emit at).
    smell_grid: dict[str, float] | None = None
    # PRD-04: the mover's own free-language hint. Always a wire field from
    # this stage on (so stage 5 needs no protocol change to populate it),
    # but no strategy exists yet to generate one — see domain/belief.py's
    # HintClaim for why an empty/absent hint is never treated as truthful
    # silence, just as absence of a claim.
    hint: str = ""
    # PRD-05: the sender's OWN self-declared verdict on the hint above —
    # True if `hint` is truthful, False if it is a deliberate lie. Sealed
    # alongside `hint` (domain/sealed_payload.py) so a sender that reveals a
    # DIFFERENT verdict at audit than the one it actually sent live is
    # exactly the "lying about whether you lied" tamper case (PRD-05
    # section C) — caught by the existing commit-reveal re-hash, no new
    # mechanism needed. `None` only for declare_terminal (no hint sent).
    hint_is_true: bool | None = None

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "turn_number": self.turn_number,
            "action_type": self.action_type,
            "direction": self.direction,
            "target_row": self.target_row,
            "target_col": self.target_col,
            "police_actions_taken": self.police_actions_taken,
            "thief_actions_taken": self.thief_actions_taken,
            "claimed_condition": self.claimed_condition,
            "claimed_offending_side": self.claimed_offending_side,
            "commit": self.commit,
            "sub_game_number": self.sub_game_number,
            "smell_grid": self.smell_grid,
            "hint": self.hint,
            "hint_is_true": self.hint_is_true,
        }
