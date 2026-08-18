"""Timeout and freeze-detection layer (rulebook rules #6/#7).

Three distinct, non-conflated timeouts, each enforced at a different layer:

- response_timeout_sec (signed, game.json)  — one single network request.
  Enforced by `call_with_timeout` around one MCP client call.
- turn_timeout_seconds  (private, game.toml) — this peer's own wall-clock
  budget for ONE WHOLE TURN (local compute + the network exchange). Enforced
  by the orchestrator wrapping its per-turn coroutine in
  `call_with_timeout` as well, with the larger, private budget.
- watchdog_timeout_sec  (signed, game.json)  — freeze/crash detection across
  the WHOLE MATCH: if no phase transition has happened at all for this long,
  something is stuck regardless of which per-turn timeout should have caught
  it. `FreezeWatchdog` tracks this via explicit heartbeats and is checked
  independently of the per-turn timeouts, so a bug that bypasses those still
  gets caught.

An opponent that goes silent must not hang the process — every wait on the
network in this codebase goes through `call_with_timeout`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


class OpponentUnresponsiveError(Exception):
    """Raised when a network operation involving the opponent does not
    complete within its budget. FastMCP's own failure modes for a dead
    opponent are not one consistent exception type — a connect-phase
    failure surfaces as RuntimeError, an in-call failure as
    mcp.shared.exceptions.McpError, with varying messages — so this wraps
    ANY exception or timeout from the wrapped operation uniformly. See
    PRD-02 "Architecture decisions" for the actual behaviour observed.
    """

    def __init__(self, operation: str, timeout_sec: float, cause: BaseException | None = None):
        super().__init__(f"opponent did not complete '{operation}' within {timeout_sec}s")
        self.operation = operation
        self.timeout_sec = timeout_sec
        self.cause = cause


async def call_with_timeout(awaitable: Awaitable[T], *, operation: str, timeout_sec: float) -> T:
    """Await `awaitable`, raising OpponentUnresponsiveError uniformly on
    either an outright timeout or any exception from the underlying call —
    never letting a hang or an inconsistent low-level error type escape."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_sec)
    except TimeoutError as exc:
        raise OpponentUnresponsiveError(operation, timeout_sec, cause=exc) from exc
    except Exception as exc:
        raise OpponentUnresponsiveError(operation, timeout_sec, cause=exc) from exc


class FreezeDetected(Exception):
    """Raised when no progress (no state-machine transition) has been
    recorded for longer than watchdog_timeout_sec. Distinct from
    OpponentUnresponsiveError: this fires even if the code that's stuck
    never went through call_with_timeout at all — it's the outer safety net,
    not a per-request timeout."""

    def __init__(self, elapsed_sec: float, timeout_sec: float):
        super().__init__(f"no progress for {elapsed_sec:.1f}s (watchdog_timeout_sec={timeout_sec})")
        self.elapsed_sec = elapsed_sec
        self.timeout_sec = timeout_sec


class FreezeWatchdog:
    """Tracks wall-clock time since the last recorded heartbeat (rulebook
    rule #7: crash monitoring). The orchestrator calls `heartbeat()` after
    every successful state-machine transition; `assert_alive()` is checked
    at the top of every turn. If it raises, the caller is expected to do
    "controlled data extraction" — flush whatever match log exists so far —
    before terminating, rather than losing all data to a silent freeze.
    """

    def __init__(self, timeout_sec: float, clock=time.monotonic):
        self._timeout_sec = timeout_sec
        self._clock = clock
        self._last_heartbeat = clock()

    def heartbeat(self) -> None:
        self._last_heartbeat = self._clock()

    def seconds_since_heartbeat(self) -> float:
        return self._clock() - self._last_heartbeat

    def assert_alive(self) -> None:
        elapsed = self.seconds_since_heartbeat()
        if elapsed > self._timeout_sec:
            raise FreezeDetected(elapsed, self._timeout_sec)
