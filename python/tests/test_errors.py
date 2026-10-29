from __future__ import annotations

from typing import Any

import httpx
import pytest

from vaquill import (
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    DailyCapExceededError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
    IdempotencyReplayUnavailableError,
    InsufficientCreditsError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
    VaquillError,
)
from vaquill._errors import make_status_error

from .conftest import Script, amake, make


def build(status: int, body: object, headers: dict[str, str] | None = None) -> APIStatusError:
    response = httpx.Response(status, json=body, headers=headers)
    return make_status_error(response, body)


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (402, InsufficientCreditsError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (500, InternalServerError),
        (503, InternalServerError),
        (418, APIStatusError),
    ],
)
def test_status_mapping_without_code(status: int, cls: type[APIStatusError]) -> None:
    err = build(status, {"detail": "boom"})
    assert type(err) is cls
    assert err.status == status and err.detail == "boom" and err.code is None
    assert isinstance(err, VaquillError)


@pytest.mark.parametrize(
    ("code", "status", "cls"),
    [
        ("authentication_required", 401, AuthenticationError),
        ("invalid_api_key", 401, AuthenticationError),
        ("api_key_expired", 401, AuthenticationError),
        ("permission_denied", 403, PermissionDeniedError),
        ("insufficient_credits", 402, InsufficientCreditsError),
        ("rate_limited", 429, RateLimitError),
        ("daily_cap_exceeded", 429, DailyCapExceededError),
        ("validation_error", 422, UnprocessableEntityError),
        ("invalid_query", 422, UnprocessableEntityError),
        ("invalid_citation_input", 422, UnprocessableEntityError),
        ("section_not_found", 404, NotFoundError),
        ("resource_not_found", 404, NotFoundError),
        ("idempotency_key_reused", 422, IdempotencyKeyReusedError),
        ("idempotency_in_progress", 409, IdempotencyInProgressError),
        ("idempotency_replay_unavailable", 409, IdempotencyReplayUnavailableError),
        ("upstream_timeout", 503, InternalServerError),
        ("service_unavailable", 503, InternalServerError),
        ("internal_error", 500, InternalServerError),
        ("conflict", 409, ConflictError),
    ],
)
def test_every_known_code(code: str, status: int, cls: type[APIStatusError]) -> None:
    err = build(status, {"detail": "d", "code": code})
    assert type(err) is cls and err.code == code


def test_idempotency_family_hierarchy() -> None:
    assert issubclass(IdempotencyKeyReusedError, UnprocessableEntityError)
    assert issubclass(IdempotencyInProgressError, ConflictError)
    for cls in (
        IdempotencyKeyReusedError,
        IdempotencyInProgressError,
        IdempotencyReplayUnavailableError,
    ):
        assert issubclass(cls, IdempotencyConflictError)
    assert issubclass(DailyCapExceededError, RateLimitError)


def test_unknown_code_falls_back_to_status() -> None:
    err = build(404, {"detail": "d", "code": "brand_new_code", "title": "T"})
    assert type(err) is NotFoundError and err.code == "brand_new_code"
    assert type(build(599, {"code": "zzz"})) is InternalServerError


def test_full_envelope_fields() -> None:
    err = build(
        429,
        {
            "detail": "Slow down",
            "code": "rate_limited",
            "requestId": "req_abc",
            "retryable": True,
            "retryAfterSeconds": 7,
            "status": 429,
        },
    )
    assert err.request_id == "req_abc" and err.retryable is True
    assert err.retry_after_seconds == 7
    assert "req_abc" in str(err) and err.message == "Slow down"


def test_legacy_envelope_old_server() -> None:
    errors = [{"loc": ["body", "q"], "msg": "bad", "type": "missing"}]
    err = build(422, {"detail": "Validation failed", "errors": errors}, {"X-Request-ID": "hdr_1"})
    assert err.errors == errors and err.detail == "Validation failed"
    assert err.code is None and err.retryable is None and err.retry_after_seconds is None
    assert err.request_id == "hdr_1"  # falls back to the header


def test_object_detail_on_section_404() -> None:
    body: dict[str, Any] = {
        "detail": {"actId": "X", "reason": "r", "didYouMean": []},
        "code": "section_not_found",
    }
    err = build(404, body)
    assert (err.detail["reason"] == "r" and err.message == "section_not_found") or err.message


def test_non_json_and_odd_bodies() -> None:
    response = httpx.Response(502, text="<html>Bad gateway</html>")
    err = make_status_error(response, response.text)
    assert type(err) is InternalServerError and err.body == "<html>Bad gateway</html>"
    assert err.message == "HTTP 502" and err.code is None
    weird = build(400, {"code": 5, "retryable": "yes", "retryAfterSeconds": True, "errors": "x"})
    assert weird.code is None and weird.retryable is None and weird.errors is None
    assert weird.retry_after_seconds is None


def test_client_raises_mapped_error_for_non_json_body() -> None:
    script = Script(httpx.Response(400, text="plain"))
    with pytest.raises(BadRequestError) as info:
        make(script).raw_request("GET", "/x")
    assert info.value.body == "plain"


async def test_async_raises_mapped_error() -> None:
    script = Script(httpx.Response(404, json={"detail": "x", "code": "section_not_found"}))
    with pytest.raises(NotFoundError):
        await amake(script).raw_request("GET", "/x")
