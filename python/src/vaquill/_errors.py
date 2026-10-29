"""Error hierarchy.

Branch on ``code`` when present and fall back to the HTTP status, so the SDK works
against servers that predate the machine-code envelope. The code set is open: an
unknown code still produces the status-mapped class.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from ._config import REQUEST_ID_HEADER

__all__ = [
    "APIConnectionError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "DailyCapExceededError",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "IdempotencyKeyReusedError",
    "IdempotencyReplayUnavailableError",
    "InsufficientCreditsError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ResponseParseError",
    "SpendGuardExceeded",
    "UnprocessableEntityError",
    "VaquillError",
    "WebhookVerificationError",
    "make_status_error",
]

# Codes the server marks retryable (decision 3). Anything else is not retried.
RETRYABLE_CODES = frozenset(
    {
        "rate_limited",
        "idempotency_in_progress",
        "upstream_timeout",
        "service_unavailable",
        "internal_error",
    }
)
NEVER_RETRY_CODES = frozenset({"insufficient_credits", "daily_cap_exceeded"})


class VaquillError(Exception):
    """Base class for every error raised by this SDK."""


class SpendGuardExceeded(VaquillError):
    """The client-side ``max_credits`` cap was reached; no request was sent."""


class ResponseParseError(VaquillError):
    """A 2xx response could not be parsed into the expected model (bad JSON or wrong shape)."""

    def __init__(
        self, message: str, *, request_id: str | None = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id
        self.status_code = status_code

    @property
    def status(self) -> int | None:
        return self.status_code

    def __str__(self) -> str:
        return f"{self.message} (status={self.status_code}, request_id={self.request_id})"


class WebhookVerificationError(VaquillError):
    """A webhook delivery failed signature or timestamp verification."""


class APIConnectionError(VaquillError):
    """The request never produced an HTTP response."""

    def __init__(self, message: str = "Connection error.", *, request: httpx.Request) -> None:
        super().__init__(message)
        self.request = request


class APITimeoutError(APIConnectionError):
    def __init__(self, *, request: httpx.Request) -> None:
        super().__init__("Request timed out.", request=request)


class APIStatusError(VaquillError):
    """The server answered with a 4xx or 5xx status."""

    def __init__(self, message: str, *, response: httpx.Response, body: Any) -> None:
        super().__init__(message)
        envelope = _envelope(body)
        self.message = message
        self.response = response
        self.body: Any = body
        self.status_code = response.status_code
        self.request_id: str | None = _str(envelope.get("requestId")) or response.headers.get(
            REQUEST_ID_HEADER
        )
        self.code: str | None = _str(envelope.get("code"))
        retryable = envelope.get("retryable")
        self.retryable: bool | None = retryable if isinstance(retryable, bool) else None
        after = envelope.get("retryAfterSeconds")
        self.retry_after_seconds: float | None = (
            float(after) if isinstance(after, int | float) and not isinstance(after, bool) else None
        )
        # Legacy envelope members, unchanged by the server.
        self.detail: Any = envelope.get("detail")
        self.errors: list[Any] | None = (
            envelope["errors"] if isinstance(envelope.get("errors"), list) else None
        )

    @property
    def status(self) -> int:
        return self.status_code

    def __str__(self) -> str:
        return f"{self.message} (status={self.status_code}, request_id={self.request_id})"


def _envelope(body: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", body) if isinstance(body, dict) else {}


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class BadRequestError(APIStatusError): ...


class AuthenticationError(APIStatusError): ...


class InsufficientCreditsError(APIStatusError):
    """Out of credits (402). Never retried."""


class PermissionDeniedError(APIStatusError): ...


class NotFoundError(APIStatusError): ...


class ConflictError(APIStatusError): ...


class UnprocessableEntityError(APIStatusError): ...


class RateLimitError(APIStatusError):
    """429. ``retry_after_seconds`` is set when the server said how long to wait."""


class DailyCapExceededError(RateLimitError):
    """Per-key daily cap. Retrying cannot succeed until the cap resets."""


class InternalServerError(APIStatusError): ...


class IdempotencyConflictError(APIStatusError):
    """Base for the three idempotency codes."""


class IdempotencyKeyReusedError(IdempotencyConflictError, UnprocessableEntityError):
    """Same key sent with a different request."""


class IdempotencyInProgressError(IdempotencyConflictError, ConflictError):
    """The original request is still running. Retryable."""


class IdempotencyReplayUnavailableError(IdempotencyConflictError, ConflictError):
    """The original completed but its response is too large to replay.

    The call was not charged again. Check ``credits.balance()`` before retrying.
    """


_BY_CODE: dict[str, type[APIStatusError]] = {
    "insufficient_credits": InsufficientCreditsError,
    "daily_cap_exceeded": DailyCapExceededError,
    "idempotency_key_reused": IdempotencyKeyReusedError,
    "idempotency_in_progress": IdempotencyInProgressError,
    "idempotency_replay_unavailable": IdempotencyReplayUnavailableError,
}
_BY_STATUS: dict[int, type[APIStatusError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def _validation_summary(errors: Any) -> str | None:
    """First few `loc: msg` pairs of a 422 `errors` list, or None."""
    if not isinstance(errors, list):
        return None
    items = cast("list[Any]", errors)
    parts: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = cast("dict[str, Any]", raw)
        if not isinstance(item.get("msg"), str) or not item["msg"]:
            continue
        loc = item.get("loc")
        path: list[Any] = list(cast("list[Any]", loc)) if isinstance(loc, list) else []
        if len(path) > 1 and str(path[0]) in ("body", "query", "path", "header"):
            path = path[1:]
        where = ".".join(str(p) for p in path)
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    if not parts:
        return None
    shown = "; ".join(parts[:3])
    more = len(items) - min(len(parts), 3)
    return f"{shown} (+{more} more)" if more > 0 else shown


def _message(status: int, body: Any) -> str:
    env = _envelope(body)
    detail = env.get("detail")
    if isinstance(detail, str) and detail:
        why = _validation_summary(env.get("errors")) if status == 422 else None
        return f"{detail}: {why}" if why else detail
    title = env.get("title")
    if isinstance(title, str) and title:
        return title
    return f"HTTP {status}"


def make_status_error(response: httpx.Response, body: Any) -> APIStatusError:
    """Map a response to the most specific error class."""
    code = _envelope(body).get("code")
    cls = _BY_CODE.get(code) if isinstance(code, str) else None
    if cls is None:
        status = response.status_code
        cls = InternalServerError if status >= 500 else _BY_STATUS.get(status, APIStatusError)
    return cls(_message(response.status_code, body), response=response, body=body)
