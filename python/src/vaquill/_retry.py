"""Retry policy: which failures are retried and how long to wait."""

from __future__ import annotations

import asyncio
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
            return max(float(ms) / 1000.0, 0.0)
        if (value := headers.get("retry-after")) is None:
            return None
        try:
            return max(float(value), 0.0)
        except ValueError:
            return max(parsedate_to_datetime(value).timestamp() - time.time(), 0.0)
    except (ValueError, TypeError):
        return None


def status_is_retryable(error: APIStatusError) -> bool:
    """Whether the server's answer is worth retrying. Keys on ``code``, falls back to status."""
    if error.code in NEVER_RETRY_CODES or error.retryable is False:
        return False
    if error.code in RETRYABLE_CODES:
        return True
    status = error.status_code
    return status in (408, 429) or status >= 500


def delay_for_status(error: APIStatusError, retries_done: int) -> float | None:
    """Seconds to wait before retrying this error, or None to raise it instead."""
    if not status_is_retryable(error):
        return None
    wait = parse_retry_after(error.response.headers)
    if wait is None and error.retry_after_seconds is not None:
        wait = error.retry_after_seconds
    if wait is None:
        return backoff_delay(retries_done)
    # A wait this long means "go away"; give the caller the error now.
    return None if wait > MAX_RETRY_AFTER_DELAY else wait


def connection_error_is_retryable(
    exc: httpx.TransportError, *, charged: bool, has_idempotency_key: bool
) -> bool:
    """Connect failures never reached the server, so they are always safe to retry.

    Any other transport failure is ambiguous (the request may have been processed). It is
    retried only when the call is free or carries an idempotency key.
    """
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout):
        return True
    return not charged or has_idempotency_key
