"""One live MCP connection per opponent URL, held for the whole series.

WHY THIS EXISTS. The outbound half used to build a fresh `Client` for every
single tool call, so one turn cost a full TCP connect + TLS handshake + MCP
`initialize` round-trip. That is not merely slow, it is a COMPATIBILITY
defect. Measured against a real ngrok free-tier edge: at game pace our calls
tripped its per-minute connection cap after 17 calls in 39 seconds, after
which every subsequent connection was refused outright for about a minute;
the same number of calls paced at 10/min all succeeded. An opponent sitting
behind a free tunnel would have their edge knocked out by OUR connection
churn, and the game would die with a `ConnectError` that reads like their
fault. This pool is what keeps a league game playable against a peer whose
hosting we do not control.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

logger = logging.getLogger(__name__)

# Sent on every outbound HTTP call. ngrok's free tier answers an UNRECOGNIZED
# client with an interstitial HTML warning page instead of proxying the
# request, which reaches an MCP client as `text/html` where it expects JSON —
# a parse error that looks nothing like "your opponent is behind a tunnel".
# This header opts out of the interstitial and is ignored by every other host,
# so it is sent unconditionally rather than sniffed for from the URL: which
# side of a league game sits behind which tunnel provider is not something
# this peer can know, and getting it wrong is a forfeited game.
_OUTBOUND_HEADERS = {"ngrok-skip-browser-warning": "true"}


# The live connections, one per opponent URL, held for the whole series.
_POOL: dict[str, Client] = {}
_POOL_LOCK = asyncio.Lock()


def _client(opponent_url, *, response_timeout_sec: float) -> Client:
    """Build (not connect) a client. HTTP(S) opponents get an explicit transport
    so `_OUTBOUND_HEADERS` can ride along; anything else — an in-memory
    `FastMCP` server, which the tests pass here instead of a URL — keeps
    FastMCP's own transport inference."""
    if isinstance(opponent_url, str) and opponent_url.startswith(("http://", "https://")):
        transport = StreamableHttpTransport(opponent_url, headers=_OUTBOUND_HEADERS)
        return Client(transport, timeout=response_timeout_sec)
    return Client(opponent_url, timeout=response_timeout_sec)


async def acquire(opponent_url: str, *, response_timeout_sec: float) -> Client:
    """The pooled, already-connected client for this opponent, connecting one
    if there is no live one.

    `Client` is reference-counted and reentrant, so holding a single
    `__aenter__` open for the life of the series keeps the session alive;
    individual calls then reuse it with no handshake at all.
    """
    client = _POOL.get(opponent_url)
    if client is not None and client.is_connected():
        return client
    async with _POOL_LOCK:
        # Re-check under the lock: another turn may have reconnected already,
        # and two connections per opponent is the thing being avoided.
        client = _POOL.get(opponent_url)
        if client is not None and client.is_connected():
            return client
        if client is not None:
            await evict(opponent_url, client)
        client = _client(opponent_url, response_timeout_sec=response_timeout_sec)
        await client.__aenter__()
        _POOL[opponent_url] = client
        logger.debug("opened a pooled MCP connection to %s", opponent_url)
        return client


async def evict(opponent_url: str, client: Client | None = None) -> None:
    """Drop a connection so the next call rebuilds it.

    Identity-guarded: a best-effort control send that fails must not tear down
    a connection some turn send has already replaced.
    """
    pooled = _POOL.get(opponent_url)
    if pooled is None or (client is not None and pooled is not client):
        return
    _POOL.pop(opponent_url, None)
    with contextlib.suppress(Exception):
        await pooled.__aexit__(None, None, None)


async def close_all() -> None:
    """Close every pooled connection. Called once, at series end."""
    for url in list(_POOL):
        await evict(url)
