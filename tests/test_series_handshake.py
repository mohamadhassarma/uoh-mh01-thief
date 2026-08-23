"""The handshake runs PER SUB-GAME (interop kit `sparring/netplay.py:9`).

These pin the three things that make that safe: series identity survives
re-negotiation unchanged, BOTH peer shapes work (greets every sub-game /
greets once for the whole series), and a re-negotiation that contradicts the
series is refused rather than absorbed.
"""

from __future__ import annotations

import asyncio

import pytest

from uoh_mh01.domain.state import Side
from uoh_mh01.infra.inboxes import Inboxes
from uoh_mh01.infra.negotiation import (
    NegotiationRefusedError,
    build_negotiate_message,
    game_ids,
    verify_declared_uid,
)
from uoh_mh01.infra.series_handshake import negotiate_sub_game
from uoh_mh01.shared.peer_config import PeerConfig


def _peer_config(group_id: str = "alpha", port: int = 1) -> PeerConfig:
    return PeerConfig(
        role="police",
        group_id=group_id,
        group_name=f"Team {group_id}",
        my_port=port,
        opponent_url="http://127.0.0.1:9999/mcp",
        turn_timeout_seconds=30,
        members=("a", "b"),
        repos={"cop": "https://example.invalid"},
    )


class _Runtime:
    def __init__(self) -> None:
        self.inboxes = Inboxes()


@pytest.fixture
def fast_config(config_factory):
    """A watchdog short enough that the once-per-series FALLBACK path (which
    can only be reached by waiting the budget out) does not slow the suite."""
    return config_factory(watchdog_timeout_sec=0.5, response_timeout_sec=0.5)


@pytest.fixture
def no_send(monkeypatch):
    """The outbound push is not under test here; record it and drop it."""
    sent: list[dict] = []

    async def _capture(url, message, **kwargs):
        sent.append(message)

    monkeypatch.setattr("uoh_mh01.infra.series_handshake.send_negotiate", _capture)
    return sent


def _opponent_greeting(config, *, role: Side, sub_game_number: int, game_uid=None, group_id="bravo"):
    return build_negotiate_message(
        role, config, _peer_config(group_id, 2), sub_game_number=sub_game_number, game_uid=game_uid
    ).to_kwargs()


# --- item 0: series identity is invariant under re-negotiation ------------------


def test_game_uid_does_not_depend_on_anything_that_varies_between_negotiations(config):
    """The precondition for allowing re-negotiation at all. The derivation
    reads only the flat terms and the two sorted group ids — never the nonce,
    the signature, the role, or the sub_game_number, all four of which DO
    differ between two greetings of the same series."""
    a_mine = build_negotiate_message(Side.POLICE, config, _peer_config("alpha", 1), sub_game_number=1)
    a_theirs = build_negotiate_message(Side.THIEF, config, _peer_config("bravo", 2), sub_game_number=1)
    # Sub-game 2: fresh nonces, fresh signatures, SWAPPED roles, new index.
    b_mine = build_negotiate_message(Side.THIEF, config, _peer_config("alpha", 1), sub_game_number=2)
    b_theirs = build_negotiate_message(Side.POLICE, config, _peer_config("bravo", 2), sub_game_number=2)

    assert (a_mine.nonce, a_mine.signature, a_mine.role) != (b_mine.nonce, b_mine.signature, b_mine.role)
    assert game_ids(a_mine, a_theirs) == game_ids(b_mine, b_theirs)


def test_a_declared_uid_that_disagrees_with_our_derivation_is_refused():
    # SPAR-N10: the only moment a wrong-input uid can surface, because the uid
    # never crosses the wire during play.
    with pytest.raises(NegotiationRefusedError, match="game_uid mismatch"):
        verify_declared_uid("a" * 36, "b" * 36)


def test_a_peer_that_declares_no_uid_is_never_refused_for_it():
    verify_declared_uid("a" * 36, None)  # omission never refuses (SPEC §7.3)


# --- item 1/2: both peer shapes work -------------------------------------------


def test_a_peer_that_greets_every_sub_game_keeps_one_series_identity(fast_config, no_send):
    runtime = _Runtime()

    async def scenario():
        series = None
        seen = []
        for n, role in ((1, Side.POLICE), (2, Side.THIEF), (3, Side.POLICE)):
            runtime.inboxes.agreements.append(
                _opponent_greeting(fast_config, role=_other(role), sub_game_number=n)
            )
            series, mine, theirs = await negotiate_sub_game(
                runtime, n, role, fast_config, _peer_config(), series=series
            )
            seen.append((series.game_uid, mine.role, theirs.sub_game_number))
        return series, seen

    series, seen = asyncio.run(scenario())
    assert series.peer_renegotiates is True
    # One uid across all three, roles alternating, their index tracking ours.
    assert {uid for uid, _, _ in seen} == {series.game_uid}
    assert [role for _, role, _ in seen] == ["police", "thief", "police"]
    assert [n for _, _, n in seen] == [1, 2, 3]
    assert len(no_send) == 3


def test_from_sub_game_two_onward_we_declare_the_pinned_uid(fast_config, no_send):
    runtime = _Runtime()

    async def scenario():
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))
        series, *_ = await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.POLICE, sub_game_number=2))
        await negotiate_sub_game(runtime, 2, Side.THIEF, fast_config, _peer_config(), series=series)
        return series

    series = asyncio.run(scenario())
    # First contact cannot declare a uid — the derivation needs THEIR group id,
    # which first contact is what supplies. Sub-game 2 onward must declare it.
    assert "game_uid" not in no_send[0]
    assert no_send[1]["game_uid"] == series.game_uid


def test_a_peer_that_greets_only_once_per_series_is_tolerated(fast_config, no_send):
    """The shape THIS project itself had until now. Silence at a later
    sub-game boundary falls back to the pinned agreement — it is not a fault."""
    runtime = _Runtime()

    async def scenario():
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))
        series, *_ = await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)
        # Nothing enqueued for sub-game 2: they greeted once and moved on.
        series, mine, theirs = await negotiate_sub_game(runtime, 2, Side.THIEF, fast_config, _peer_config(), series=series)
        return series, mine, theirs

    series, mine, theirs = asyncio.run(scenario())
    assert series.peer_renegotiates is False
    assert theirs is series.their_first_msg  # fell back to the pinned agreement
    assert mine.role == "thief"  # ...but MY greeting still carried this sub-game's role
    assert len(no_send) == 2  # and we still pushed ours, which costs nothing


def test_a_known_once_per_series_peer_is_not_waited_for_again(fast_config, no_send, monkeypatch):
    """Having learned the answer at sub-game 2, sub-games 3..6 must not each
    burn a full watchdog budget waiting for a greeting that never comes."""
    polls = []
    real = __import__("uoh_mh01.infra.series_handshake", fromlist=["_poll_agreement"])._poll_agreement

    async def counting(runtime, **kwargs):
        polls.append(kwargs["sub_game_number"])
        return await real(runtime, **kwargs)

    monkeypatch.setattr("uoh_mh01.infra.series_handshake._poll_agreement", counting)
    runtime = _Runtime()

    async def scenario():
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))
        series = None
        for n, role in ((1, Side.POLICE), (2, Side.THIEF), (3, Side.POLICE), (4, Side.THIEF)):
            series, *_ = await negotiate_sub_game(runtime, n, role, fast_config, _peer_config(), series=series)

    asyncio.run(scenario())
    assert polls == [1, 2], "sub-games 3 and 4 should not have waited at all"


def test_a_greeting_for_another_sub_game_is_deferred_not_consumed(fast_config, no_send):
    """The opponent greets for N+1 as soon as ITS N settles, which is routinely
    before this side has finished N's audit. That greeting must survive."""
    runtime = _Runtime()
    runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.POLICE, sub_game_number=2))
    runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))

    async def scenario():
        return await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)

    series, _, theirs = asyncio.run(scenario())
    assert theirs.sub_game_number == 1
    # The early one is still there for the sub-game that actually wants it.
    assert [g["sub_game_number"] for g in runtime.inboxes.agreements] == [2]
    assert series.game_uid


# --- item 3: a re-negotiation that contradicts the series is a violation --------


def test_re_negotiated_terms_that_differ_from_the_series_are_refused(fast_config, config_factory, no_send):
    runtime = _Runtime()
    drifted = config_factory(grid_size=9, watchdog_timeout_sec=0.5, response_timeout_sec=0.5)

    async def scenario():
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))
        series, *_ = await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)
        # Sub-game 2: they re-greet with DIFFERENT terms. Both sides' configs
        # drifted together, so `mine == theirs` still holds and only the pin
        # against the SERIES terms can catch it.
        runtime.inboxes.agreements.append(_opponent_greeting(drifted, role=Side.POLICE, sub_game_number=2))
        await negotiate_sub_game(runtime, 2, Side.THIEF, drifted, _peer_config(), series=series)

    with pytest.raises(NegotiationRefusedError, match="mid-series drift"):
        asyncio.run(scenario())


def test_a_different_group_answering_mid_series_is_refused(fast_config, no_send):
    """Identical signed terms make a bystander pass every other check —
    including the uid check, which derives from terms plus the group ids THEY
    supply. Only the series pin catches it."""
    runtime = _Runtime()

    async def scenario():
        runtime.inboxes.agreements.append(_opponent_greeting(fast_config, role=Side.THIEF, sub_game_number=1))
        series, *_ = await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)
        runtime.inboxes.agreements.append(
            _opponent_greeting(fast_config, role=Side.POLICE, sub_game_number=2, group_id="charlie")
        )
        await negotiate_sub_game(runtime, 2, Side.THIEF, fast_config, _peer_config(), series=series)

    with pytest.raises(NegotiationRefusedError, match="DIFFERENT group"):
        asyncio.run(scenario())


def test_the_first_handshake_still_hard_fails_on_silence(fast_config, no_send):
    runtime = _Runtime()

    async def scenario():
        await negotiate_sub_game(runtime, 1, Side.POLICE, fast_config, _peer_config(), series=None)

    with pytest.raises(NegotiationRefusedError, match="never sent its signed agreement"):
        asyncio.run(scenario())


def _other(role: Side) -> Side:
    return Side.THIEF if role is Side.POLICE else Side.POLICE
