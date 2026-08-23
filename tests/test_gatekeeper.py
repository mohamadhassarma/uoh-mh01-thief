"""The Gatekeeper: token bucket, quota, DOS breaker, and the 429 rule.

The 429 cases matter most. Book §9 is explicit that a 429 is NOT a transient
fault and that resending straight into it can get the account suspended, so
these pin that a 429 is handled differently from every other failure rather
than falling into a generic retry path.

Clock and sleep are injected throughout — a backoff test that really slept
5 + 10 seconds would be skipped in practice, and a skipped test guards nothing.
"""

from __future__ import annotations

import pytest

from uoh_mh01.domain.config_models import GatekeeperConfig
from uoh_mh01.infra.gatekeeper import (
    BREAKER_THRESHOLD,
    DosDetector,
    GatekeeperRefusedError,
    QuotaExceededError,
    QuotaManager,
    TokenBucket,
)
from uoh_mh01.infra.gatekeeper_runner import Gatekeeper, is_rate_limited


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimitedError(Exception):
    def __init__(self) -> None:
        super().__init__("429 Too Many Requests")
        self.status_code = 429


def _config(**overrides) -> GatekeeperConfig:
    base = {
        "requests_per_minute": 30,
        "concurrent_requests": 2,
        "retry_backoff_sec": 5.0,
        "max_retries": 3,
        "queue_depth": 100,
    }
    return GatekeeperConfig(**{**base, **overrides})


def _gatekeeper(clock, slept: list[float], **overrides) -> Gatekeeper:
    return Gatekeeper(_config(**overrides), service="test", clock=clock, sleep=slept.append)


# --- token bucket ---------------------------------------------------------------


def test_the_bucket_allows_a_full_capacity_burst_then_refuses():
    clock = FakeClock()
    bucket = TokenBucket(3, clock=clock)
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]


def test_the_bucket_refills_at_capacity_per_minute():
    clock = FakeClock()
    bucket = TokenBucket(30, clock=clock)
    for _ in range(30):
        bucket.take()
    assert not bucket.take()
    clock.advance(2.0)  # 30/min == one token every 2s
    assert bucket.take()


def test_seconds_until_token_reports_the_real_wait():
    clock = FakeClock()
    bucket = TokenBucket(60, clock=clock)
    for _ in range(60):
        bucket.take()
    assert bucket.seconds_until_token() == pytest.approx(1.0)


# --- quota ----------------------------------------------------------------------


def test_the_quota_is_a_hard_ceiling_that_rolls_over():
    clock = FakeClock()
    quota = QuotaManager(2, clock=clock)
    quota.charge(2)
    assert quota.remaining() == 0
    clock.advance(61)
    assert quota.remaining() == 2


def test_a_429_burns_the_whole_window_not_just_one_call():
    clock = FakeClock()
    quota = QuotaManager(10, clock=clock)
    quota.charge()
    quota.burn_window()
    assert quota.remaining() == 0


# --- DOS detector ---------------------------------------------------------------


def test_the_breaker_opens_on_consecutive_failures_and_a_success_resets_it():
    dos = DosDetector()
    for _ in range(BREAKER_THRESHOLD):
        dos.record(ok=False)
    assert dos.open
    dos.record(ok=True)
    assert not dos.open


def test_an_open_breaker_refuses_locally_without_calling_out():
    clock, slept = FakeClock(), []
    gate = _gatekeeper(clock, slept)
    calls = []
    for _ in range(BREAKER_THRESHOLD):
        gate.dos.record(ok=False)
    with pytest.raises(GatekeeperRefusedError, match="circuit breaker open"):
        gate.execute(calls.append, "should never run")
    assert calls == [], "an open breaker must generate no traffic at all"


# --- 429 handling ---------------------------------------------------------------


def test_a_429_is_recognised_structurally_and_by_message():
    assert is_rate_limited(RateLimitedError())
    assert is_rate_limited(Exception("Too Many Requests"))
    assert not is_rate_limited(Exception("connection reset"))


def test_a_429_backs_off_exponentially_rather_than_resending_immediately():
    clock, slept = FakeClock(), []

    def always_limited():
        raise RateLimitedError()

    gate = _gatekeeper(clock, slept)
    with pytest.raises(QuotaExceededError):
        gate.execute(always_limited)
    # Three attempts, two waits between them: 5s then 10s. Never zero.
    assert slept == [5.0, 10.0]


def test_a_429_that_clears_succeeds_on_a_later_attempt():
    clock, slept = FakeClock(), []
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimitedError()
        return "ok"

    assert _gatekeeper(clock, slept).execute(flaky) == "ok"
    assert slept == [5.0]


def test_a_non_429_failure_is_re_raised_untouched_and_never_retried():
    clock, slept = FakeClock(), []
    attempts = []

    def broken():
        attempts.append(1)
        raise ValueError("malformed request")

    with pytest.raises(ValueError, match="malformed"):
        _gatekeeper(clock, slept).execute(broken)
    assert attempts == [1], "a bad request is not a rate limit; retrying it is pointless"
    assert slept == []


def test_an_exhausted_quota_refuses_before_the_call():
    clock, slept = FakeClock(), []
    gate = _gatekeeper(clock, slept, requests_per_minute=1)
    gate.quota.charge(1)
    calls = []
    with pytest.raises(QuotaExceededError, match="quota exhausted"):
        gate.execute(calls.append, "nope")
    assert calls == []


def test_a_successful_call_releases_its_queue_slot():
    clock, slept = FakeClock(), []
    gate = _gatekeeper(clock, slept, queue_depth=1)
    assert gate.execute(lambda: "a") == "a"
    assert gate.execute(lambda: "b") == "b", "queue slot leaked: a completed call still counted as queued"
