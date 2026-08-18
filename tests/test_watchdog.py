import asyncio

import pytest

from uoh_mh01.infra.watchdog import (
    FreezeDetected,
    FreezeWatchdog,
    OpponentUnresponsiveError,
    call_with_timeout,
)


async def _sleeps_forever():
    await asyncio.sleep(9999)


async def _raises(exc: Exception):
    raise exc


async def _returns(value):
    return value


@pytest.mark.asyncio
async def test_call_with_timeout_returns_value_on_success():
    result = await call_with_timeout(_returns(42), operation="test", timeout_sec=1)
    assert result == 42


@pytest.mark.asyncio
async def test_call_with_timeout_on_a_silent_opponent_raises_not_hangs():
    with pytest.raises(OpponentUnresponsiveError) as excinfo:
        await call_with_timeout(_sleeps_forever(), operation="submit_move", timeout_sec=0.05)
    assert excinfo.value.operation == "submit_move"
    assert excinfo.value.timeout_sec == 0.05


@pytest.mark.asyncio
async def test_call_with_timeout_wraps_any_exception_uniformly():
    with pytest.raises(OpponentUnresponsiveError) as excinfo:
        await call_with_timeout(_raises(RuntimeError("connection refused")), operation="connect", timeout_sec=1)
    assert isinstance(excinfo.value.cause, RuntimeError)


class _FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_freeze_watchdog_does_not_trip_before_timeout():
    clock = _FakeClock()
    watchdog = FreezeWatchdog(timeout_sec=10, clock=clock)
    clock.advance(9)
    watchdog.assert_alive()  # must not raise


def test_freeze_watchdog_trips_after_timeout_with_no_heartbeat():
    clock = _FakeClock()
    watchdog = FreezeWatchdog(timeout_sec=10, clock=clock)
    clock.advance(10.1)
    with pytest.raises(FreezeDetected) as excinfo:
        watchdog.assert_alive()
    assert excinfo.value.timeout_sec == 10


def test_freeze_watchdog_heartbeat_resets_the_clock():
    clock = _FakeClock()
    watchdog = FreezeWatchdog(timeout_sec=10, clock=clock)
    clock.advance(9)
    watchdog.heartbeat()
    clock.advance(9)
    watchdog.assert_alive()  # still must not raise — heartbeat reset the window
