"""The pre-game handshake (PRD-03): exchange mutual signatures over the
shared `terms`, agree `sub_game_number`/`role` for the sub-game about to be
played (interop kit SPEC §7.2, a PROMOTED behaviour with real evidence
behind it — a peer that skips this can desync its sub-game index from its
opponent's and neither side would otherwise notice), and derive the shared
`game_id`/`game_uid`. A terms mismatch refuses to play — it must not start
and then fail.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from ..domain.crypto import commit_of
from ..domain.game_ids import derive_game_ids
from ..domain.state import Side
from ..shared.locked_model import scent_model_sha256
from ..shared.peer_config import PeerConfig
from ..shared.sysinfo import collect_spec
from ..shared.terms import terms_from_config

NONCE_BYTES = 16


class NegotiationRefusedError(Exception):
    """Raised when the opponent's negotiate message disagrees with mine on
    anything that must match — terms, sub_game_number, or role. Per PRD-03:
    must not start play and then fail; this is checked before the first
    move of the sub-game."""


@dataclass(frozen=True)
class NegotiateMessage:
    terms: dict[str, Any]
    nonce: str
    signature: str
    identity: dict[str, Any]
    scent_model_sha256: str
    sub_game_number: int
    role: str

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "terms": self.terms,
            "nonce": self.nonce,
            "signature": self.signature,
            "identity": self.identity,
            "scent_model_sha256": self.scent_model_sha256,
            "sub_game_number": self.sub_game_number,
            "role": self.role,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> NegotiateMessage:
        return NegotiateMessage(
            terms=d["terms"],
            nonce=d["nonce"],
            signature=d["signature"],
            identity=d["identity"],
            scent_model_sha256=d["scent_model_sha256"],
            sub_game_number=d["sub_game_number"],
            role=d["role"],
        )


def build_negotiate_message(
    role: Side, config, peer_config: PeerConfig, *, sub_game_number: int
) -> NegotiateMessage:
    terms = terms_from_config(config)
    nonce = secrets.token_hex(NONCE_BYTES)
    identity = {
        "group_id": peer_config.group_id,
        "group_name": peer_config.group_name,
        "members": list(peer_config.members),
        "repos": dict(peer_config.repos),
        "hardware": collect_spec(),
    }
    return NegotiateMessage(
        terms=terms,
        nonce=nonce,
        signature=commit_of(terms, nonce),
        identity=identity,
        scent_model_sha256=scent_model_sha256(),
        sub_game_number=sub_game_number,
        role=role.value,
    )


def verify_peer_message(mine: NegotiateMessage, theirs: NegotiateMessage) -> None:
    """Raise NegotiationRefusedError on any mismatch mine and theirs must agree
    on. Never resolved silently — refusing before the first move is the
    whole point."""
    if theirs.terms != mine.terms:
        raise NegotiationRefusedError(f"terms mismatch: mine={mine.terms} theirs={theirs.terms}")
    if commit_of(theirs.terms, theirs.nonce) != theirs.signature:
        raise NegotiationRefusedError("opponent's signature does not verify over the terms it sent")
    if theirs.sub_game_number != mine.sub_game_number:
        raise NegotiationRefusedError(
            f"sub_game_number mismatch: mine={mine.sub_game_number} theirs={theirs.sub_game_number} "
            "— the two peers have desynced which sub-game of the series they believe they are playing"
        )
    if theirs.role == mine.role:
        raise NegotiationRefusedError(f"both sides claim role {mine.role!r} for this sub-game — roles must be complementary")
    if mine.scent_model_sha256 != theirs.scent_model_sha256:
        raise NegotiationRefusedError(
            f"scent model hash mismatch: mine={mine.scent_model_sha256} theirs={theirs.scent_model_sha256} "
            "— PRD-03 item 12: the pheromone emission/decay model must be agreed before the series begins"
        )


def game_ids(mine: NegotiateMessage, theirs: NegotiateMessage) -> tuple[str, str]:
    """Derive (game_id, game_uid) — call only after verify_peer_message has
    not raised. Order-independent: sorts the two group ids internally."""
    return derive_game_ids(mine.terms, mine.identity["group_id"], theirs.identity["group_id"])
