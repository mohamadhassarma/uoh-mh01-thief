"""One live connection per opponent, held for the series (infra/mcp_pool.py).

Not a performance nicety. Per-call connections tripped a real ngrok free-tier
edge's per-minute connection cap after 17 calls in 39 seconds, after which
every connection was refused for about a minute. An opponent behind a free
tunnel would be knocked offline by OUR churn, and the game would die looking
like their fault.
"""

from __future__ import annotations

import asyncio

import pytest

from uoh_mh01.infra import mcp_client, mcp_pool
from uoh_mh01.infra.inboxes import Inboxes
from uoh_mh01.infra.mcp_server import build_server
from uoh_mh01.infra.watchdog import OpponentUnresponsiveError


@pytest.fixture(autouse=True)
def _clean_pool():
    """The pool is process-global by design — it has to outlive every
    individual send — so each test starts and ends with it empty."""
    asyncio.run(mcp_pool.close_all())
    yield
    asyncio.run(mcp_pool.close_all())


def _server():
    return build_server(Inboxes(), name="pool-test")


def test_repeated_calls_to_one_opponent_open_exactly_one_connection(monkeypatch):
    server = _server()
    opened = []
    real_client = mcp_pool._client

    def counting(url, **kwargs):
        opened.append(url)
        return real_client(url, **kwargs)

    monkeypatch.setattr(mcp_pool, "_client", counting)
    # An in-memory server stands in for the opponent: the pooling logic is
    # transport-agnostic, and this keeps the test off the network.
    monkeypatch.setattr(mcp_pool, "_POOL", {})

    async def scenario():
        for i in range(10):
            await mcp_client._call(server, "receive_control", {"n": i}, response_timeout_sec=5)

    asyncio.run(scenario())
    assert len(opened) == 1, f"expected one connection for ten calls, opened {len(opened)}"


def test_two_different_opponents_get_their_own_connections(monkeypatch):
    a, b = _server(), _server()
    monkeypatch.setattr(mcp_pool, "_POOL", {})

    async def scenario():
        for target in (a, b, a, b):
            await mcp_client._call(target, "receive_control", {}, response_timeout_sec=5)
        return len(mcp_pool._POOL)

    assert asyncio.run(scenario()) == 2


def test_a_failed_call_retires_its_connection_so_the_next_one_reconnects(monkeypatch):
    """A pooled session can go stale through nobody's fault — a tunnel idle
    timeout, the far end restarting between sub-games. A stale session that is
    never retired would fail forever."""
    server = _server()
    monkeypatch.setattr(mcp_pool, "_POOL", {})

    async def scenario():
        await mcp_client._call(server, "receive_control", {}, response_timeout_sec=5)
        pooled = next(iter(mcp_pool._POOL.values()))

        async def boom(*args, **kwargs):
            raise RuntimeError("session went stale")

        monkeypatch.setattr(pooled, "call_tool", boom)
        # `call_with_timeout` normalizes every low-level failure to one type,
        # so the stale-session error surfaces as OpponentUnresponsiveError.
        with pytest.raises(OpponentUnresponsiveError):
            await mcp_client._call(server, "receive_control", {}, response_timeout_sec=5)
        assert mcp_pool._POOL == {}, "the dead connection must not stay pooled"

        # ...and the next call transparently reconnects.
        monkeypatch.undo()
        await mcp_client._call(server, "receive_control", {}, response_timeout_sec=5)
        return len(mcp_pool._POOL)

    assert asyncio.run(scenario()) == 1


def test_eviction_is_identity_guarded(monkeypatch):
    """A best-effort control send that fails must not tear down a connection
    some turn send has already replaced."""
    monkeypatch.setattr(mcp_pool, "_POOL", {})

    async def scenario():
        server = _server()
        await mcp_client._call(server, "receive_control", {}, response_timeout_sec=5)
        current = next(iter(mcp_pool._POOL.values()))
        stale = mcp_pool._client(server, response_timeout_sec=5)
        await mcp_pool.evict(server, stale)  # a loser racing to evict
        assert next(iter(mcp_pool._POOL.values())) is current

    asyncio.run(scenario())


def test_close_all_empties_the_pool():
    server = _server()

    async def scenario():
        await mcp_client._call(server, "receive_control", {}, response_timeout_sec=5)
        assert mcp_pool._POOL
        await mcp_pool.close_all()
        return mcp_pool._POOL

    assert asyncio.run(scenario()) == {}


def test_retry_backs_off_instead_of_hammering_a_refusing_edge(monkeypatch):
    """The failure a retry most often follows is a rate-limited edge, and a
    flat 1s cadence is what caused the outage in the first place."""
    slept: list[float] = []
    attempts = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    async def down_then_up(*args, **kwargs):
        attempts.append(1)
        if len(attempts) <= 5:
            raise OpponentUnresponsiveError("receive_turn", 1.0)

    monkeypatch.setattr(mcp_client.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(mcp_client, "_call", down_then_up)

    asyncio.run(
        mcp_client._call_with_retry(
            "http://x/mcp", "receive_turn", {}, response_timeout_sec=1, deadline_sec=600
        )
    )
    assert len(attempts) == 6
    # Doubling, then capped — not six one-second hammer blows.
    assert slept == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_retry_still_gives_up_at_the_deadline(monkeypatch):
    async def fake_sleep(seconds):
        pass

    async def always_down(*args, **kwargs):
        raise OpponentUnresponsiveError("receive_turn", 1.0)

    monkeypatch.setattr(mcp_client.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(mcp_client, "_call", always_down)
    with pytest.raises(OpponentUnresponsiveError):
        asyncio.run(
            mcp_client._call_with_retry(
                "http://x/mcp", "receive_turn", {}, response_timeout_sec=1, deadline_sec=0.0
            )
        )


def test_the_ngrok_interstitial_header_survived_the_split():
    client = mcp_pool._client("https://example.invalid/mcp", response_timeout_sec=5)
    assert client.transport.headers["ngrok-skip-browser-warning"] == "true"
