"""Turn SDK exceptions into short, actionable messages that never carry a key or a stack trace."""

import re
from typing import Iterable, Optional

from vaquill import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    DailyCapExceededError,
    IdempotencyConflictError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ResponseParseError,
    SpendGuardExceeded,
    UnprocessableEntityError,
    VaquillError,
)

__all__ = ["VaquillToolError", "describe_error", "sanitize"]

_SECRET_PATTERN = re.compile(r"vq_key_[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
_MAX_DETAIL_CHARS = 300


class VaquillToolError(RuntimeError):
    """Raised instead of returned when ``raise_on_error=True`` (and by the retriever).

    The message is already sanitized. The original exception is deliberately not chained, so no
    request object (and therefore no Authorization header) is reachable from a traceback.
    """


def sanitize(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove API keys and bearer tokens from ``text`` and cap its length."""
    cleaned = _SECRET_PATTERN.sub("[redacted]", text)
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > _MAX_DETAIL_CHARS:
        cleaned = cleaned[:_MAX_DETAIL_CHARS] + "..."
    return cleaned


def _suffix(exc: APIStatusError) -> str:
    return f" (request_id={exc.request_id})" if exc.request_id else ""


def describe_error(exc: BaseException, secrets: Iterable[str] = ()) -> str:
    """One or two sentences saying what went wrong and what to do next."""
    secret_list = [s for s in secrets if s]
    detail = ""
    if isinstance(exc, APIStatusError):
        detail = sanitize(exc.message, secret_list)
    message: Optional[str] = None
    if isinstance(exc, SpendGuardExceeded):
        message = (
            "Spend guard reached: the configured max_credits limit is used up. "
            "No request was sent. Raise max_credits or stop calling charged tools."
        )
    elif isinstance(exc, DailyCapExceededError):
        message = (
            "The daily credit cap for this API key is reached. Retrying will not help "
            "until it resets. Tell the user instead of retrying."
        )
    elif isinstance(exc, RateLimitError):
        wait = exc.retry_after_seconds
        hint = f"Wait about {wait:g} seconds" if wait else "Wait a little"
        message = f"Rate limited (429). {hint}, then retry once."
    elif isinstance(exc, InsufficientCreditsError):
        message = (
            "Out of credits (402). Ask the user to top up at https://www.vaquill.ai. "
            "get_credit_balance is free and shows what is left."
        )
    elif isinstance(exc, AuthenticationError):
        message = (
            "Vaquill rejected the API key (401). Check that VAQUILL_API_KEY is set to a "
            "valid key that starts with vq_key_."
        )
    elif isinstance(exc, PermissionDeniedError):
        message = "This API key may not use that endpoint (403). Ask the user to check the key's plan."
    elif isinstance(exc, NotFoundError):
        message = (
            f"Not found (404): {detail or 'no such record'}. Find the id first with "
            "search_statutes or resolve_citation, then retry."
        )
    elif isinstance(exc, IdempotencyConflictError):
        message = "A conflicting duplicate request was detected. Do not retry this exact call."
    elif isinstance(exc, (BadRequestError, UnprocessableEntityError)):
        message = f"The request was invalid: {detail or 'check the arguments'}. Fix the arguments and retry."
    elif isinstance(exc, InternalServerError):
        message = "Vaquill had a server error (5xx). Retry once later; if it persists, report the request id."
    elif isinstance(exc, APIStatusError):
        message = f"Vaquill answered with status {exc.status_code}: {detail or 'no detail'}."
    elif isinstance(exc, APITimeoutError):
        message = "The request to Vaquill timed out. Retry once, or narrow the query."
    elif isinstance(exc, APIConnectionError):
        message = "Could not reach the Vaquill API. Check the network and the base URL."
    elif isinstance(exc, ResponseParseError):
        message = (
            "Vaquill returned a response this integration could not read. "
            "Retry once; if it persists, upgrade the vaquill package."
        )
    elif isinstance(exc, ValueError):
        message = f"Invalid argument: {sanitize(str(exc), secret_list)}"
    elif isinstance(exc, VaquillError):
        message = sanitize(str(exc), secret_list)
    if message is None:
        message = f"Unexpected {type(exc).__name__}. The details are hidden on purpose; retry or report it."
    if isinstance(exc, APIStatusError):
        message += _suffix(exc)
    return f"Vaquill error: {message}"
