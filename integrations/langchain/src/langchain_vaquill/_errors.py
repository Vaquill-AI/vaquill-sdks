"""Map SDK errors to a ToolException the model can act on. No stack traces, no keys."""

from __future__ import annotations

import re

from langchain_core.tools import ToolException
from vaquill import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
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

__all__ = ["redact", "to_tool_exception"]

_SECRETS = re.compile(
    r"(vq_(?:key|ws)_[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+|whsec_[A-Za-z0-9+/=_\-]+)"
)
_MAX_DETAIL = 400


def redact(text: str) -> str:
    """Strip anything shaped like a Vaquill key, bearer token or webhook secret."""
    return _SECRETS.sub("[redacted]", text)


def _detail(exc: APIStatusError) -> str:
    message = redact(str(getattr(exc, "message", "") or "")).strip()
    if len(message) > _MAX_DETAIL:
        message = message[:_MAX_DETAIL] + "..."
    return message


def _suffix(exc: APIStatusError) -> str:
    return f" (request id {exc.request_id})" if exc.request_id else ""


def _status_message(exc: APIStatusError) -> str:
    detail = _detail(exc)
    tail = _suffix(exc)
    if isinstance(exc, AuthenticationError):
        return (
            "Vaquill rejected the API key (401). This is a configuration problem the model "
            "cannot fix. Stop calling Vaquill tools and tell the user to check VAQUILL_API_KEY."
            + tail
        )
    if isinstance(exc, PermissionDeniedError):
        return f"This API key is not allowed to do that (403): {detail}. Do not retry.{tail}"
    if isinstance(exc, InsufficientCreditsError):
        return (
            "The Vaquill account is out of credits (402). Do not retry. Only free tools "
            "(vaquill_credit_balance, vaquill_statutes_coverage, extract_citations with "
            f"resolve=false) still work. Tell the user to add credits.{tail}"
        )
    if isinstance(exc, DailyCapExceededError):
        return (
            "The daily call cap for this key is used up (429). Retrying will not help until it "
            f"resets. Stop and tell the user.{tail}"
        )
    if isinstance(exc, RateLimitError):
        wait = exc.retry_after_seconds
        hint = (
            f"Wait about {wait:g} seconds, then retry once." if wait else "Wait, then retry once."
        )
        return f"Rate limited by Vaquill (429). {hint}{tail}"
    if isinstance(exc, NotFoundError):
        return (
            f"Not found (404): {detail}. The id or citation may be wrong. Use "
            "vaquill_resolve_citation or vaquill_search_statutes to find the exact actId, "
            f"then retry with that.{tail}"
        )
    if isinstance(exc, IdempotencyConflictError):
        return f"A duplicate or in-flight request was rejected ({exc.status_code}). Retry once with the same arguments.{tail}"
    if isinstance(exc, ConflictError):
        return f"Conflict ({exc.status_code}): {detail}.{tail}"
    if isinstance(exc, BadRequestError | UnprocessableEntityError):
        return (
            f"Vaquill rejected the arguments ({exc.status_code}): {detail}. "
            f"Fix the arguments and call again.{tail}"
        )
    if isinstance(exc, InternalServerError) or exc.status_code >= 500:
        return (
            f"Vaquill had a server error ({exc.status_code}). Retry once after a short wait.{tail}"
        )
    return f"Vaquill returned an error ({exc.status_code}): {detail}.{tail}"


def to_tool_exception(exc: BaseException) -> ToolException:
    """Translate any error raised while calling the SDK into a clean ToolException."""
    if isinstance(exc, ToolException):
        return exc
    message: str
    if isinstance(exc, SpendGuardExceeded):
        message = (
            "The credit limit set for this agent session has been reached, so no more paid "
            "Vaquill calls will be sent. Do not retry. Answer with what you already have, or "
            "tell the user the limit was hit."
        )
    elif isinstance(exc, APIStatusError):
        message = _status_message(exc)
    elif isinstance(exc, APITimeoutError):
        message = "The Vaquill request timed out. Retry once; if it fails again, tell the user."
    elif isinstance(exc, APIConnectionError):
        message = "Could not reach the Vaquill API (network error). Retry once, then tell the user."
    elif isinstance(exc, ResponseParseError):
        message = "Vaquill returned a response this client could not read. Do not retry."
    elif isinstance(exc, VaquillError):
        message = "Vaquill client error: " + redact(str(exc))
    elif isinstance(exc, ValueError):
        message = "Invalid argument: " + redact(str(exc))
    else:
        message = f"Unexpected {type(exc).__name__} while calling Vaquill. Do not retry."
    return ToolException(message)
