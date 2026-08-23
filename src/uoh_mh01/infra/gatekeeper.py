"""The Gatekeeper in front of every outbound third-party API call (PRD-07).

Three separate jobs, deliberately not collapsed into one "rate limiter":

  * **Token bucket** — shapes the ordinary call rate to the signed
    `requests_per_minute`, with a `queue_depth` ceiling so a backlog is
    refused rather than silently growing without bound.
  * **Quota manager** — the HARD per-window ceiling. A bucket smooths bursts;
    a quota says "no more this window, at all". They are different guarantees
    and a 429 must be able to consume the quota without touching the bucket.
  * **DOS detector** — a circuit breaker on the caller's own behaviour. The
    book's stated answer to a runaway agent loop is a mechanism, not human
    review: once tripped it refuses locally and stops generating traffic at all.

WHY A 429 IS NOT AN ORDINARY ERROR. Book §9, "כללי ברזל": a 429 "אינה תקלה
חולפת" — it is not a transient fault. Insisting and immediately resending can
get the ACCOUNT SUSPENDED by the provider. So a 429 is handled differently
from every other failure here: it burns the remaining quota window, backs off
exponentially, and counts toward the breaker. A generic "retry on error" path
that treats 429 like a timeout is the specific mistake the book calls out.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

WINDOW_SEC = 60.0
# Consecutive failures before the breaker opens. Not configurable in the
# signed section, so it lives here as a named constant rather than a literal.
BREAKER_THRESHOLD = 5


class GatekeeperRefusedError(Exception):
    """The call never left this process: bucket empty and queue full, quota
    exhausted, or the breaker open. Distinct from a provider error — nothing
    was sent, so nothing needs to be undone."""


class QuotaExceededError(GatekeeperRefusedError):
    """The provider said 429, or our own window ceiling was reached."""


@dataclass
class TokenBucket:
    """Classic leaky bucket: `capacity` tokens, refilled at `capacity/60` per
    second. `clock` is injectable so tests never sleep."""

    capacity: int
    clock: Callable[[], float] = time.monotonic
    _tokens: float = field(init=False)
    _last: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.capacity / WINDOW_SEC)
        self._last = now

    def take(self) -> bool:
        self._refill()
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def seconds_until_token(self) -> float:
        self._refill()
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) * WINDOW_SEC / self.capacity


@dataclass
class QuotaManager:
    """A hard ceiling of `limit` calls per rolling `WINDOW_SEC`."""

    limit: int
    clock: Callable[[], float] = time.monotonic
    _stamps: deque[float] = field(default_factory=deque, init=False)

    def _evict(self) -> None:
        cutoff = self.clock() - WINDOW_SEC
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    def remaining(self) -> int:
        self._evict()
        return max(0, self.limit - len(self._stamps))

    def charge(self, calls: int = 1) -> None:
        now = self.clock()
        for _ in range(calls):
            self._stamps.append(now)

    def burn_window(self) -> None:
        """A provider 429 means the window is gone regardless of what we
        counted. Fill it so nothing else leaves until it rolls over."""
        self._stamps.clear()
        self.charge(self.limit)


@dataclass
class DosDetector:
    """Circuit breaker on consecutive failures — protection against OUR OWN
    runaway loop, not against an attacker."""

    threshold: int = BREAKER_THRESHOLD
    consecutive_failures: int = 0

    @property
    def open(self) -> bool:
        return self.consecutive_failures >= self.threshold

    def record(self, *, ok: bool) -> None:
        self.consecutive_failures = 0 if ok else self.consecutive_failures + 1
