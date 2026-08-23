"""The handshake, run ONCE PER SUB-GAME (interop kit `sparring/netplay.py:9`:
"The handshake runs per sub-game").

WHY THIS MOVED. This project used to negotiate once, at series start, and then
play all `num_games` sub-games off that single agreement. Against the kit's
sparring peer that produced a clean sub-game 1 and then `SPAR-N09: handshake
budget exhausted; our counterpart never arrived` for sub-game 2 — they were
waiting for a greeting we were never going to send. Nothing in our own suite
could see it: both of our peers negotiated once, so both agreed.

WHAT IS PINNED AND WHAT IS NOT. Series identity is fixed by the FIRST
agreement and never re-derived (`SeriesIdentity`). What legitimately varies
per sub-game is only `role` (alternation) and `sub_game_number`. Re-negotiated
terms that DIFFER from the pinned ones are mid-series drift, which is a
protocol violation rather than a renegotiation, and are refused — see
`_pin_or_refuse`.

Both shapes must work (standing tolerance rule): a peer that greets every
sub-game, and a peer that greets only once for the whole series.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ..domain.state import Side
from .inboxes import poll
from .mcp_client import send_negotiate
from .negotiation import (
    NegotiateMessage,
    NegotiationRefusedError,
    build_negotiate_message,
    game_ids,
    verify_declared_uid,
    verify_peer_message,
)

logger = logging.getLogger(__name__)

_AGREEMENT_POLL_INTERVAL_SEC = 0.25


@dataclass
class SeriesIdentity:
    """Everything about a series that must NOT change once sub-game 1 agreed.

    `game_uid` is safe to pin because its derivation reads only the flat
    negotiated terms and the two sorted group ids — never the nonce, the
    signature, the role, or the sub-game number (domain/game_ids.py). Two
    negotiations of identical terms between the same two groups therefore
    produce a byte-identical uid, which is exactly what makes re-negotiation
    safe to allow at all. `game_id` is a pure function of the same sorted group
    ids, so it cannot vary per sub-game either, and is pinned for the same
    reason.
    """

    game_id: str
    game_uid: str
    terms: dict[str, Any]
    opponent_group_id: str
    my_first_msg: NegotiateMessage
    their_first_msg: NegotiateMessage
    # None until sub-game 2 answers the question. Once a peer is known NOT to
    # re-greet, later sub-games skip the wait instead of burning a full
    # watchdog budget apiece on a message that is never coming.
    peer_renegotiates: bool | None = None


async def negotiate_sub_game(
    runtime, sub_game_number: int, role: Side, config, peer_config, *, series: SeriesIdentity | None
) -> tuple[SeriesIdentity, NegotiateMessage, NegotiateMessage]:
    """Greet for one sub-game. Returns `(series, mine, theirs)` — `theirs` is
    the pinned first agreement when this peer does not re-greet."""
    mine = build_negotiate_message(
        role, config, peer_config, sub_game_number=sub_game_number, game_uid=series.game_uid if series else None
    )
    await send_negotiate(
        peer_config.opponent_url,
        mine.to_kwargs(),
        response_timeout_sec=config.network.response_timeout_sec,
        watchdog_timeout_sec=config.network.watchdog_timeout_sec,
    )

    raw = None
    if series is None or series.peer_renegotiates is not False:
        raw = await _poll_agreement(
            runtime, sub_game_number=sub_game_number, timeout=config.network.watchdog_timeout_sec
        )

    if raw is None:
        if series is None:
            raise NegotiationRefusedError("the opponent never sent its signed agreement within watchdog_timeout_sec")
        # TOLERATED, not a fault: a peer that negotiates once per series is a
        # legal shape (it is what THIS project did until now). Fall back to the
        # pinned series agreement and stop waiting on later sub-games.
        if series.peer_renegotiates is None:
            logger.info(
                "opponent did not re-greet for sub-game %s — treating it as a once-per-series peer", sub_game_number
            )
        series.peer_renegotiates = False
        return series, mine, series.their_first_msg

    theirs = NegotiateMessage.from_dict(raw)
    verify_peer_message(mine, theirs)
    return _pin_or_refuse(series, mine, theirs, sub_game_number)


def _pin_or_refuse(
    series: SeriesIdentity | None, mine: NegotiateMessage, theirs: NegotiateMessage, sub_game_number: int
) -> tuple[SeriesIdentity, NegotiateMessage, NegotiateMessage]:
    game_id, game_uid = game_ids(mine, theirs)
    opponent = theirs.identity.get("group_id")
    verify_declared_uid(game_uid, theirs.game_uid)
    if series is None:
        logger.info("handshake agreed: game_id=%s game_uid=%s", game_id, game_uid)
        return (
            SeriesIdentity(
                game_id=game_id,
                game_uid=game_uid,
                terms=mine.terms,
                opponent_group_id=opponent,
                my_first_msg=mine,
                their_first_msg=theirs,
            ),
            mine,
            theirs,
        )

    # A RE-negotiation may only re-affirm the series. Anything else is drift.
    if theirs.terms != series.terms:
        diff = sorted(k for k in set(series.terms) | set(theirs.terms) if series.terms.get(k) != theirs.terms.get(k))
        raise NegotiationRefusedError(
            f"sub-game {sub_game_number}: re-negotiated terms differ from the terms this series was "
            f"opened on, in {diff}. That is not a renegotiation, it is mid-series drift: the pinned "
            "game_uid, every config artifact already written, and every commit already sealed were "
            "all derived from the original terms, so continuing would silently produce a series "
            "whose artifacts do not describe the games that were played"
        )
    if opponent != series.opponent_group_id:
        raise NegotiationRefusedError(
            f"sub-game {sub_game_number}: a DIFFERENT group ({opponent!r}) answered a series opened "
            f"with {series.opponent_group_id!r}. Identical signed terms make a bystander's greeting "
            "pass every other check, so without this pin its sub-games would be aggregated into the "
            "first opponent's artifact set under the first opponent's game_uid"
        )
    series.peer_renegotiates = True
    return series, mine, theirs


async def _poll_agreement(runtime, *, sub_game_number: int, timeout: float) -> dict[str, Any] | None:
    """Poll my own agreements inbox for a greeting naming THIS sub-game.

    A greeting for a different sub-game is set aside and restored, never
    consumed-and-refused: the two peers do not reach a sub-game boundary at the
    same instant, so the opponent's greeting for sub-game N+1 can legitimately
    land while this side is still settling N. The kit treats the same mismatch
    as retryable rather than fatal (`negotiate.py` SPAR-N06) for this reason.
    """
    clock = asyncio.get_event_loop().time
    deadline = clock() + timeout
    deferred: list[dict[str, Any]] = []
    try:
        while True:
            remaining = deadline - clock()
            if remaining <= 0:
                return None
            raw = await poll(runtime.inboxes.agreements, timeout=remaining, poll_interval=_AGREEMENT_POLL_INTERVAL_SEC)
            if raw is None:
                return None
            if raw.get("sub_game_number", sub_game_number) == sub_game_number:
                return raw
            deferred.append(raw)
    finally:
        runtime.inboxes.agreements.extendleft(reversed(deferred))
