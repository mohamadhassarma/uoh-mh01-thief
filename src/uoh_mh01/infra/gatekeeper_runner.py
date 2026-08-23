"""`Gatekeeper.execute` — the one door every outbound third-party call goes
through. Split from gatekeeper.py (which holds the three independent
mechanisms) purely to keep both files inside the project's ~150-line budget.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..domain.config_models import GatekeeperConfig
from .gatekeeper import DosDetector, GatekeeperRefusedError, QuotaExceededError, QuotaManager, TokenBucket

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_rate_limited(exc: BaseException) -> bool:
    """Recognise a provider 429 without importing googleapiclient here.

    Checked structurally (`status`/`resp.status`) before falling back to the
    string, so a library that reports the code properly is never matched by
    accident on some unrelated message containing "429".
    """
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
    if status is not None:
        return int(status) == 429
    return "429" in str(exc) or "Too Many Requests" in str(exc)


class Gatekeeper:
    """Rate-limits, quota-checks and breaker-guards a callable.

    `sleep` and `clock` are injected so the whole retry ladder is testable
    without a real wall clock — a backoff test that actually slept 5, 10 and
    20 seconds would simply not be run often enough to catch anything.
    """

    def __init__(
        self,
        config: GatekeeperConfig,
        *,
        service: str = "api",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.service = service
        self._sleep = sleep
        self.bucket = TokenBucket(config.requests_per_minute, clock=clock)
        self.quota = QuotaManager(config.requests_per_minute, clock=clock)
        self.dos = DosDetector()
        self._queued = 0

    def execute(self, call: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run `call` under the full policy. Raises `GatekeeperRefusedError` if it
        never left this process; re-raises the provider's own exception if the
        call was made and failed for a non-retryable reason."""
        self._admit()
        delay = self.config.retry_backoff_sec
        last: BaseException | None = None
        for attempt in range(1, self.config.max_retries + 1):
            self._wait_for_token()
            self.quota.charge()
            try:
                result = call(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - classified immediately below
                last = exc
                self.dos.record(ok=False)
                if not is_rate_limited(exc):
                    self._queued -= 1
                    raise
                # BOOK §9: a 429 is not a transient fault. Do not resend into
                # the same window — burn it, back off, and wait for the next.
                self.quota.burn_window()
                logger.warning(
                    "%s: provider returned 429 (attempt %s/%s); backing off %.1fs",
                    self.service, attempt, self.config.max_retries, delay,
                )
                if attempt < self.config.max_retries:
                    self._sleep(delay)
                    delay *= 2
                continue
            else:
                self.dos.record(ok=True)
                self._queued -= 1
                return result
        self._queued -= 1
        raise QuotaExceededError(
            f"{self.service}: still rate-limited after {self.config.max_retries} attempts"
        ) from last

    def _admit(self) -> None:
        if self.dos.open:
            raise GatekeeperRefusedError(
                f"{self.service}: circuit breaker open after {self.dos.consecutive_failures} "
                "consecutive failures — refusing locally rather than generating more traffic"
            )
        if self._queued >= self.config.queue_depth:
            raise GatekeeperRefusedError(f"{self.service}: queue depth {self.config.queue_depth} reached")
        if self.quota.remaining() <= 0:
            raise QuotaExceededError(f"{self.service}: per-minute quota exhausted")
        self._queued += 1

    def _wait_for_token(self) -> None:
        while not self.bucket.take():
            self._sleep(max(self.bucket.seconds_until_token(), 0.01))
