"""The startup/shutdown log noise filter.

A five-frame ERROR traceback printed right after a series everyone watched
succeed reads as a crash, and it is the last thing on screen before the
result - so it is what a screenshot catches. These tests pin both that the
noise goes and, more importantly, that nothing else does.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from uoh_mh01.infra.server_noise import (
    UVICORN_ERROR_LOGGER,
    ShutdownCancellationFilter,
    silence_lifespan_cancellation,
)

# What starlette formats and hands to uvicorn as a plain string. Trimmed, but
# the shape - and crucially the final line - is verbatim from a real run.
REAL_NOISE = """Traceback (most recent call last):
  File "...\\starlette\\routing.py", line 655, in lifespan
    await receive()
  File "...\\uvicorn\\lifespan\\on.py", line 137, in receive
    return await self.receive_queue.get()
  File "...\\asyncio\\queues.py", line 186, in get
    await getter
asyncio.exceptions.CancelledError"""


@pytest.fixture
def captured():
    """Records what survives the filter on uvicorn's own logger."""
    logger = logging.getLogger(UVICORN_ERROR_LOGGER)
    kept = []

    class _Sink(logging.Handler):
        def emit(self, record):
            kept.append(record.getMessage())

    sink = _Sink()
    logger.addHandler(sink)
    filters_before = list(logger.filters)
    silence_lifespan_cancellation()
    yield logger, kept
    logger.removeHandler(sink)
    logger.filters = filters_before


def test_the_lifespan_cancellation_traceback_is_dropped(captured):
    logger, kept = captured
    logger.error(REAL_NOISE)
    assert kept == []


def test_it_is_dropped_even_though_it_carries_no_exception(captured):
    """The obvious filter - match on `exc_info` - does nothing here. Starlette
    sends the traceback as a STRING and uvicorn logs it with no exception
    attached, so the message text is the only thing there is to match on."""
    logger, kept = captured
    record = logger.makeRecord(UVICORN_ERROR_LOGGER, logging.ERROR, "f", 1, REAL_NOISE, None, None)
    assert record.exc_info is None
    assert not ShutdownCancellationFilter().filter(record)


def test_a_cancellation_passed_as_a_real_exception_is_also_dropped(captured):
    """Belt and braces, in case a future uvicorn reports it properly."""
    logger, kept = captured
    try:
        raise asyncio.CancelledError()
    except asyncio.CancelledError:
        logger.error("Exception in 'lifespan' protocol", exc_info=True)
    assert kept == []


def test_a_genuine_uvicorn_error_still_prints(captured):
    """The one thing worse than noise is a silenced server."""
    logger, kept = captured
    logger.error("Application startup failed. Exiting.")
    logger.error("[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8801)")
    assert len(kept) == 2


def test_a_real_failure_inside_the_lifespan_still_prints(captured):
    """Mentioning the lifespan is not on its own a reason to hide something."""
    logger, kept = captured
    logger.error(REAL_NOISE.replace("asyncio.exceptions.CancelledError", "RuntimeError: the port is in use"))
    assert len(kept) == 1


def test_a_cancellation_somewhere_that_is_not_the_lifespan_still_prints(captured):
    """Ending in CancelledError is not on its own a reason either - a
    cancellation in the middle of real work is worth seeing."""
    logger, kept = captured
    logger.error('Traceback:\n  File "app.py", line 3, in handler\nasyncio.exceptions.CancelledError')
    assert len(kept) == 1


def test_installing_twice_does_not_stack_filters():
    logger = logging.getLogger(UVICORN_ERROR_LOGGER)
    before = list(logger.filters)
    try:
        first = silence_lifespan_cancellation()
        second = silence_lifespan_cancellation()
        assert first is second
        assert sum(isinstance(f, ShutdownCancellationFilter) for f in logger.filters) == 1
    finally:
        logger.filters = before


def test_the_series_runner_installs_it():
    """A filter nothing installs silences nothing."""
    import inspect

    from uoh_mh01.infra import series

    assert "silence_lifespan_cancellation()" in inspect.getsource(series.run_series)
