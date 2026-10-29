"""Retry policy: which failures are retried and how long to wait."""

from __future__ import annotations

import asyncio
import math
import random
import time
from email.utils import parsedate_to_datetime

import httpx

from ._config import INITIAL_RETRY_DELAY, MAX_RETRY_AFTER_DELAY, MAX_RETRY_DELAY
from ._errors import NEVER_RETRY_CODES, RETRYABLE_CODES, APIStatusError

# Indirection so tests can replace real sleeping.
sleep = time.sleep
asleep = asyncio.sleep


def backoff_delay(retries_done: int) -> float:
    """0.5 s doubling to an 8 s cap, scaled down by 0 to 25 percent jitter."""
    base = min(INITIAL_RETRY_DELAY * 2.0**retries_done, MAX_RETRY_DELAY)
    return base * (1 - 0.25 * random.random())


def parse_retry_after(headers: httpx.Headers) -> float | None:
    """Seconds to wait: ``retry-after-ms``, then ``retry-after`` seconds, then an HTTP date."""
    try:
        if (ms := headers.get("retry-after-ms")) is not None:
            wait = float(ms) / 1000.0
            # nan and inf are not waits: ignore the header rather than crash or hang.
            return max(wait, 0.0) if math.isfinite(wait) else None
        if (value := headers.get("retry-after")) is None:
            return None
        try:
            wait = float(value)
        except ValueError:
            wait = parsedate_to_datetime(value).timestamp() - time.time()
        return max(wait, 0.0) if math.isfinite(wait) else None
    except (ValueError, TypeError, OverflowError):
        return None


def status_is_retryable(error: APIStatusError) -> bool:
    """Whether the server's answer is worth retrying. Keys on ``code``, falls back to status."""
    if error.status_code == 501:
        return False  # Not Implemented never becomes implemented by waiting.
    if error.code in NEVER_RETRY_CODES or error.retryable is False:
        return False
    if error.code in RETRYABLE_CODES:
        return True
    status = error.status_code
    return status in (408, 429) or status >= 500


def delay_for_status(
    error: APIStatusError, retries_done: int, *, replay_safe: bool = True
) -> float | None:
    """Seconds to wait before retrying this error, or None to raise it instead.

    ``replay_safe`` is False for a charged call sent without an idempotency key: a 5xx there
    may have been processed (and billed) already, so it is raised instead of replayed.
    """
    if not status_is_retryable(error):
        return None
    if not replay_safe and error.status_code >= 500:
        return None
    wait = parse_retry_after(error.response.headers)
    if (
        wait is None
        and error.retry_after_seconds is not None
        and math.isfinite(error.retry_after_seconds)
    ):
        wait = error.retry_after_seconds
    if wait is None:
        return backoff_delay(retries_done)
    # A wait this long means "go away"; give the caller the error now.
    return None if wait > MAX_RETRY_AFTER_DELAY else wait


_SAFE_METHODS = frozenset({"GET", "HEAD"})


def connection_error_is_retryable(
    exc: httpx.RequestError,
    *,
    method: str = "GET",
    has_idempotency_key: bool = False,
    charged: bool = False,
) -> bool:
    """Connect failures never reached the server, so they are always safe to retry.

    Any other transport failure is ambiguous (the request may have been processed). It is
    retried only for GET and HEAD, or when the call carries an idempotency key. ``charged`` is
    accepted for older callers and no longer matters.
    """
    del charged
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout):
        return True
    return method.upper() in _SAFE_METHODS or has_idempotency_key
