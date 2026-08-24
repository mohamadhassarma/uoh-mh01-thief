"""Silencing one specific uvicorn log record: the lifespan CancelledError.

WHAT IT LOOKS LIKE. Every clean run ends with uvicorn logging, at ERROR level
and with a full traceback, an `asyncio.exceptions.CancelledError` raised inside
`starlette.routing.lifespan` at `await receive()`. It happens because this
project runs the MCP server as an asyncio task it cancels itself once the
series is over (infra/series.py's `finally`), and cancelling a task that is
parked on a queue is what cancellation IS. Nothing failed.

WHY IT MATTERS ENOUGH TO FIX. A five-frame traceback labelled ERROR, printed
immediately after a series everyone watched succeed, reads as a crash. It is
the last thing on screen before the result, so it is also the thing a
screenshot catches. Noise that looks like a failure trains people to ignore
output that might one day be a real failure.

IT ARRIVES AS TEXT, NOT AS AN EXCEPTION. The obvious filter - "drop records
whose `exc_info` is a CancelledError" - does nothing here, which cost a while
to work out. Starlette catches the cancellation, formats it with
`traceback.format_exc()` and sends the STRING to the server as a
`lifespan.shutdown.failed` message (starlette/routing.py); uvicorn then logs
that string with no `exc_info` at all (uvicorn/lifespan/on.py). So the only
signal available is the message text, and matching on it is not laziness here
but the only thing there is to match on. Both forms are handled anyway, in
case a future uvicorn passes the exception properly.

DELIBERATELY NARROW. A record is dropped only if it is a traceback that ENDS
in a CancelledError and mentions the lifespan protocol, and only on uvicorn's
own logger. A genuine uvicorn error still prints, because the one thing worse
than noise is a silenced server.
"""

from __future__ import annotations

import asyncio
import logging

UVICORN_ERROR_LOGGER = "uvicorn.error"


class ShutdownCancellationFilter(logging.Filter):
    """Drops the lifespan-cancelled record, in either form it can arrive in."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, asyncio.CancelledError):
            return False
        return not _is_lifespan_cancellation(record.getMessage())


def _is_lifespan_cancellation(message: str) -> bool:
    """A formatted traceback that ends in CancelledError inside the lifespan.

    Both conditions matter. Ending in CancelledError alone would also swallow a
    cancellation that happened somewhere real; mentioning the lifespan alone
    would swallow a genuine lifespan failure, which is exactly the sort of
    thing that must stay visible.
    """
    text = message.strip()
    return text.endswith("CancelledError") and "lifespan" in text


def silence_lifespan_cancellation(logger_name: str = UVICORN_ERROR_LOGGER) -> logging.Filter:
    """Install the filter once; returns it so a caller can remove it."""
    logger = logging.getLogger(logger_name)
    existing = next((f for f in logger.filters if isinstance(f, ShutdownCancellationFilter)), None)
    if existing is not None:
        return existing
    installed = ShutdownCancellationFilter()
    logger.addFilter(installed)
    return installed
