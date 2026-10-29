from __future__ import annotations

from typing import Any

import httpx
import pytest

from vaquill import (
    APIConnectionError,
    APITimeoutError,
    DailyCapExceededError,
    IdempotencyInProgressError,
    InsufficientCreditsError,
    InternalServerError,
    RateLimitError,
    _retry,
)

from .conftest import Script, amake, err, make

OK = httpx.Response(200, json={"ok": True})


def req(**kw: Any) -> dict[str, Any]:
    return {"json": {}, "charged": True, **kw}


def test_backoff_constants() -> None:
    for n in range(8):
        base = min(0.5 * 2**n, 8.0)
        assert 0.75 * base <= _retry.backoff_delay(n) <= base


def test_retries_5xx_then_succeeds(sleeps: list[float]) -> None:
    script = Script(err(500, "internal_error"), err(503), OK)
    make(script).raw_request("GET", "/x")
    assert len(script.requests) == 3
    assert len(sleeps) == 2 and 0.375 <= sleeps[0] <= 0.5 and 0.75 <= sleeps[1] <= 1.0


def test_exhausted_retries_raise_last_error(sleeps: list[float]) -> None:
    script = Script(err(500), err(500), err(500, "internal_error"))
    with pytest.raises(InternalServerError) as info:
        make(script).raw_request("GET", "/x")
    assert info.value.code == "internal_error" and len(script.requests) == 3


def test_max_retries_zero_and_per_call_override(sleeps: list[float]) -> None:
    with pytest.raises(InternalServerError):
        make(Script(err(500)), max_retries=0).raw_request("GET", "/x")
    script = Script(err(500), OK)
    make(script, max_retries=0).raw_request("GET", "/x", max_retries=1)
    assert len(script.requests) == 2


@pytest.mark.parametrize("status", [408, 429, 502])
def test_retryable_statuses_without_code(status: int, sleeps: list[float]) -> None:
    script = Script(err(status), OK)
    make(script).raw_request("GET", "/x")
    assert len(script.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_not_retried(status: int, sleeps: list[float]) -> None:
    script = Script(err(status), OK)
    with pytest.raises(Exception, match="nope"):
        make(script).raw_request("GET", "/x")
    assert len(script.requests) == 1 and sleeps == []


def test_409_retried_only_for_idempotency_in_progress(sleeps: list[float]) -> None:
    script = Script(err(409, "idempotency_in_progress", **{"Retry-After": "2"}), OK)
    make(script).raw_request("POST", "/x", **req())
    assert len(script.requests) == 2 and sleeps == [2.0]
    with pytest.raises(Exception, match="nope"):
        make(Script(err(409, "conflict"), OK)).raw_request("POST", "/x", **req())
    with pytest.raises(Exception, match="nope"):
        make(Script(err(409), OK)).raw_request("POST", "/x", **req())


def test_in_progress_exhausted_raises_typed(sleeps: list[float]) -> None:
    script = Script(*[err(409, "idempotency_in_progress")] * 3)
    with pytest.raises(IdempotencyInProgressError):
        make(script).raw_request("POST", "/x", **req())


def test_retry_after_ms_beats_retry_after(sleeps: list[float]) -> None:
    script = Script(err(429, "rate_limited", **{"retry-after-ms": "1500", "retry-after": "9"}), OK)
    make(script).raw_request("GET", "/x")
    assert sleeps == [1.5]


def test_retry_after_seconds_and_http_date(sleeps: list[float]) -> None:
    make(Script(err(429, "rate_limited", **{"Retry-After": "3"}), OK)).raw_request("GET", "/x")
    assert sleeps == [3.0]
    assert (
        _retry.parse_retry_after(httpx.Headers({"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}))
        == 0
    )
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "junk"})) is None
    assert _retry.parse_retry_after(httpx.Headers()) is None


def test_retry_after_beyond_cap_raises_immediately(sleeps: list[float]) -> None:
    script = Script(err(429, "rate_limited", **{"Retry-After": "600"}), OK)
    with pytest.raises(RateLimitError) as info:
        make(script).raw_request("GET", "/x")
    assert len(script.requests) == 1 and sleeps == []
    assert info.value.code == "rate_limited"


def test_insufficient_credits_never_retried(sleeps: list[float]) -> None:
    for resp in (err(402, "insufficient_credits"), err(402)):
        script = Script(resp, OK)
        with pytest.raises(InsufficientCreditsError):
            make(script).raw_request("POST", "/x", **req())
        assert len(script.requests) == 1
    # Even if some server sends the code with a retryable status.
    script = Script(err(429, "insufficient_credits"), OK)
    with pytest.raises(InsufficientCreditsError):
        make(script).raw_request("POST", "/x", **req())
    assert len(script.requests) == 1


def test_daily_cap_never_retried(sleeps: list[float]) -> None:
    script = Script(err(429, "daily_cap_exceeded"), OK)
    with pytest.raises(DailyCapExceededError) as info:
        make(script).raw_request("GET", "/x")
    assert isinstance(info.value, RateLimitError) and len(script.requests) == 1


def test_server_retryable_false_is_respected(sleeps: list[float]) -> None:
    body = {"detail": "x", "code": "future_code", "retryable": False}
    script = Script(httpx.Response(503, json=body), OK)
    with pytest.raises(InternalServerError):
        make(script).raw_request("GET", "/x")
    assert len(script.requests) == 1


# idempotency and charged semantics


def test_key_generated_once_and_reused_across_retries(sleeps: list[float]) -> None:
    script = Script(err(500, "internal_error"), httpx.ReadTimeout("t"), OK)
    make(script).raw_request("POST", "/x", **req())
    keys = {r.headers["idempotency-key"] for r in script.requests}
    assert len(script.requests) == 3 and len(keys) == 1
    assert len(next(iter(keys))) == 36


def test_new_key_per_logical_call() -> None:
    script = Script(OK, OK)
    client = make(script)
    client.raw_request("POST", "/x", **req())
    client.raw_request("POST", "/x", **req())
    assert (
        script.requests[0].headers["idempotency-key"]
        != script.requests[1].headers["idempotency-key"]
    )


def test_caller_key_wins_and_is_validated() -> None:
    script = Script(OK)
    make(script).raw_request("POST", "/x", **req(idempotency_key="my-own-key-0123456"))
    assert script.requests[0].headers["idempotency-key"] == "my-own-key-0123456"
    with pytest.raises(Exception, match="16 to 255"):
        make(Script(OK)).raw_request("POST", "/x", **req(idempotency_key="short"))


def test_uncharged_calls_get_no_key() -> None:
    script = Script(OK)
    make(script).raw_request("GET", "/credits/balance")
    assert "idempotency-key" not in script.requests[0].headers


def test_charged_post_without_key_not_retried_after_ambiguous_timeout(sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("slow"), OK)
    client = make(script, idempotency_keys=False)
    with pytest.raises(APITimeoutError):
        client.raw_request("POST", "/x", **req())
    assert len(script.requests) == 1
    assert "idempotency-key" not in script.requests[0].headers


def test_charged_post_without_key_not_retried_after_read_error(sleeps: list[float]) -> None:
    script = Script(httpx.RemoteProtocolError("reset"), OK)
    with pytest.raises(APIConnectionError):
        make(script, idempotency_keys=False).raw_request("POST", "/x", **req())
    assert len(script.requests) == 1


def test_charged_post_without_key_still_retries_connect_failure_and_5xx(
    sleeps: list[float],
) -> None:
    script = Script(httpx.ConnectError("refused"), err(500, "internal_error"), OK)
    make(script, idempotency_keys=False).raw_request("POST", "/x", **req())
    assert len(script.requests) == 3


def test_charged_post_with_caller_key_retries_even_when_auto_keys_off(sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("slow"), OK)
    key = "caller-key-0123456789"
    make(script, idempotency_keys=False).raw_request("POST", "/x", **req(idempotency_key=key))
    assert len(script.requests) == 2


def test_uncharged_get_retries_timeout(sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("slow"), OK)
    make(script).raw_request("GET", "/x")
    assert len(script.requests) == 2


def test_connection_error_after_retries(sleeps: list[float]) -> None:
    script = Script(*[httpx.ConnectError("down")] * 3)
    with pytest.raises(APIConnectionError) as info:
        make(script).raw_request("GET", "/x")
    assert not isinstance(info.value, APITimeoutError) and len(script.requests) == 3


# async parity


async def test_async_retry_key_reuse_and_no_retry(sleeps: list[float]) -> None:
    script = Script(
        err(429, "rate_limited", **{"retry-after-ms": "250"}), httpx.ReadTimeout("t"), OK
    )
    await amake(script).raw_request("POST", "/x", **req())
    assert sleeps[0] == 0.25 and len(script.requests) == 3
    assert len({r.headers["idempotency-key"] for r in script.requests}) == 1

    script = Script(httpx.ReadTimeout("t"), OK)
    with pytest.raises(APITimeoutError):
        await amake(script, idempotency_keys=False).raw_request("POST", "/x", **req())
    assert len(script.requests) == 1


async def test_async_insufficient_credits_and_spend_guard(sleeps: list[float]) -> None:
    script = Script(err(402, "insufficient_credits"), OK)
    with pytest.raises(InsufficientCreditsError):
        await amake(script).raw_request("POST", "/x", **req())
    assert len(script.requests) == 1
