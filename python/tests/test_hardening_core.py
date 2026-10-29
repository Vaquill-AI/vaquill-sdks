"""Transport hardening: retry edge cases, headers, query merge, spend guard, parse errors."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from vaquill import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    SpendGuardExceeded,
    Vaquill,
    VaquillError,
    _retry,
)
from vaquill._errors import ResponseParseError

from .conftest import KEY, Script, amake, err, make

OK = httpx.Response(200, json={"ok": True})
CHARGED_OK = httpx.Response(200, json={"ok": True, "creditsConsumed": 4})


# 1. Retry-After nan / inf


@pytest.mark.parametrize("header", ["retry-after", "retry-after-ms"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_non_finite_retry_after_is_ignored_sync(
    header: str, value: str, sleeps: list[float]
) -> None:
    script = Script(err(429, **{header: value}), OK)
    make(script).raw_request("GET", "/x")
    assert len(sleeps) == 1 and 0.375 <= sleeps[0] <= 0.5  # fell back to backoff


@pytest.mark.parametrize("header", ["retry-after", "retry-after-ms"])
async def test_non_finite_retry_after_is_ignored_async(header: str, sleeps: list[float]) -> None:
    script = Script(err(429, **{header: "nan"}), OK)
    await amake(script).raw_request("GET", "/x")
    assert len(sleeps) == 1 and sleeps[0] == sleeps[0] and sleeps[0] <= 0.5


def test_parse_retry_after_helpers() -> None:
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "nan"})) is None
    assert _retry.parse_retry_after(httpx.Headers({"retry-after-ms": "inf"})) is None
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "2"})) == 2.0


# 2. ambiguous transport errors


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH"])
@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("t"), httpx.ReadError("r"), httpx.WriteError("w")]
)
def test_ambiguous_error_not_retried_for_unsafe_methods_without_key(
    method: str, exc: Exception, sleeps: list[float]
) -> None:
    script = Script(exc, OK)
    with pytest.raises(APIConnectionError):
        make(script).raw_request(method, "/x", json={})
    assert len(script.requests) == 1 and sleeps == []


def test_remote_protocol_error_not_retried_for_post() -> None:
    script = Script(httpx.RemoteProtocolError("eof"), OK)
    with pytest.raises(APIConnectionError):
        make(script).raw_request("POST", "/x", json={})
    assert len(script.requests) == 1


def test_read_timeout_raises_timeout_error_for_delete(sleeps: list[float]) -> None:
    with pytest.raises(APITimeoutError):
        make(Script(httpx.ReadTimeout("t"), OK)).raw_request("DELETE", "/x")


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_ambiguous_error_retried_for_get_and_head(method: str, sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("t"), OK)
    make(script).raw_request(method, "/x")
    assert len(script.requests) == 2


def test_ambiguous_error_retried_for_post_with_idempotency_key(sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("t"), OK)
    make(script).raw_request("POST", "/x", json={}, idempotency_key="k" * 20)
    assert len(script.requests) == 2


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError("c"), httpx.ConnectTimeout("c"), httpx.PoolTimeout("p")],
)
@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_pure_connect_failures_retry_for_every_method(
    exc: Exception, method: str, sleeps: list[float]
) -> None:
    script = Script(exc, OK)
    make(script).raw_request(method, "/x", json={})
    assert len(script.requests) == 2


async def test_async_ambiguous_error_not_retried_for_post(sleeps: list[float]) -> None:
    script = Script(httpx.ReadTimeout("t"), OK)
    with pytest.raises(APITimeoutError):
        await amake(script).raw_request("POST", "/x", json={})
    assert len(script.requests) == 1


# 3. broad RequestError


@pytest.mark.parametrize(
    "exc",
    [
        httpx.DecodingError("bad gzip"),
        httpx.TooManyRedirects("loop"),
        httpx.UnsupportedProtocol("x"),
    ],
)
def test_any_request_error_becomes_connection_error(exc: Exception, sleeps: list[float]) -> None:
    with pytest.raises(APIConnectionError) as info:
        make(Script(exc), max_retries=0).raw_request("POST", "/x", json={})
    assert not isinstance(info.value, httpx.HTTPError)
    assert info.value.__cause__ is exc


async def test_async_decoding_error_becomes_connection_error() -> None:
    with pytest.raises(APIConnectionError):
        await amake(Script(httpx.DecodingError("bad")), max_retries=0).raw_request("GET", "/x")


# 4. protected headers


def test_headers_cannot_override_authorization_or_idempotency_key() -> None:
    script = Script(OK)
    client = make(
        script,
        default_headers={"AUTHORIZATION": "Bearer evil", "idempotency-key": "d" * 20, "X-A": "1"},
    )
    client.raw_request(
        "POST",
        "/x",
        json={},
        charged=True,
        headers={"authorization": "Bearer worse", "IDEMPOTENCY-KEY": "e" * 20, "X-B": "2"},
    )
    request = script.requests[0]
    assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
    keys = request.headers.get_list("idempotency-key")
    assert len(keys) == 1 and keys[0] not in ("d" * 20, "e" * 20)
    assert request.headers["x-a"] == "1" and request.headers["x-b"] == "2"


def test_extra_header_case_variants_do_not_duplicate() -> None:
    script = Script(OK)
    make(script, default_headers={"X-Thing": "a"}).raw_request(
        "GET", "/x", headers={"x-thing": "b"}
    )
    assert script.requests[0].headers.get_list("x-thing") == ["b"]


def test_default_idempotency_header_not_sent_on_uncharged_call() -> None:
    script = Script(OK)
    make(script, default_headers={"Idempotency-Key": "d" * 20}).raw_request("GET", "/x")
    assert "idempotency-key" not in script.requests[0].headers


# 5. query merge


def test_raw_request_merges_path_query_with_params() -> None:
    script = Script(OK, OK)
    client = make(script)
    client.raw_request("GET", "/x?a=1&b=2", params={"c": "3", "b": "9", "d": None})
    q = script.requests[0].url.params
    assert q["a"] == "1" and q["b"] == "9" and q["c"] == "3" and "d" not in q
    client.raw_request("GET", "/y?only=1")
    assert dict(script.requests[1].url.params) == {"only": "1"}
    assert script.requests[1].url.path == "/y"


async def test_async_raw_request_merges_path_query() -> None:
    script = Script(OK)
    await amake(script).raw_request("GET", "/x?a=1", params={"c": "3"})
    assert dict(script.requests[0].url.params) == {"a": "1", "c": "3"}


# 6. spend guard under concurrency


def test_spend_guard_is_exact_under_threads() -> None:
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.02)
        with lock:
            in_flight -= 1
        return httpx.Response(200, json={"creditsConsumed": 4})

    client = make(handler, max_credits=8)
    outcomes: list[str] = []

    def call() -> None:
        try:
            client.raw_request("POST", "/x", json={}, charged=True)
            outcomes.append("ok")
        except SpendGuardExceeded:
            outcomes.append("guard")

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 2 and outcomes.count("guard") == 6
    assert client.credits_spent == 8 and max_in_flight == 1


async def test_spend_guard_is_exact_under_asyncio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"creditsConsumed": 4})

    from vaquill import AsyncVaquill

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncVaquill(api_key=KEY, http_client=http, max_credits=8)
    results = await asyncio.gather(
        *[client.raw_request("POST", "/x", json={}, charged=True) for _ in range(6)],
        return_exceptions=True,
    )
    assert sum(isinstance(r, SpendGuardExceeded) for r in results) == 4
    assert client.credits_spent == 8


def test_uncapped_charged_calls_stay_concurrent() -> None:
    gate = threading.Barrier(3, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        gate.wait()  # only passes if three requests are in flight together
        return httpx.Response(200, json={"creditsConsumed": 1})

    client = make(handler)
    threads = [
        threading.Thread(
            target=client.raw_request, args=("POST", "/x"), kwargs={"json": {}, "charged": True}
        )
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert client.credits_spent == 3


def test_derived_client_shares_the_spend_lock() -> None:
    client = make(Script(CHARGED_OK), max_credits=100)
    assert client.with_options(max_credits=50)._spend is client._spend  # pyright: ignore[reportPrivateUsage]


# 7. API key hygiene


def test_key_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(OK, OK)
    http = httpx.Client(transport=httpx.MockTransport(script))
    Vaquill(api_key=f"  {KEY}\n", http_client=http).raw_request("GET", "/x")
    monkeypatch.setenv("VAQUILL_API_KEY", f"{KEY}\r\n")
    Vaquill(http_client=http).raw_request("GET", "/x")
    assert all(r.headers["authorization"] == f"Bearer {KEY}" for r in script.requests)


@pytest.mark.parametrize("bad", ["\x00", "\x07", "\x1b", "\x7f", "\n", "\t", " "])
def test_key_with_control_characters_rejected_without_echo(bad: str) -> None:
    secret = f"{KEY[:10]}{bad}{KEY[10:]}"
    with pytest.raises(ValueError) as info:
        Vaquill(api_key=secret)
    assert KEY[:10] not in str(info.value) and "vq_key_" not in str(info.value).replace(
        "Vaquill keys start with", ""
    )


def test_whitespace_only_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    with pytest.raises(VaquillError, match="No API key"):
        Vaquill(api_key="  \n")


# 8. 5xx on charged call without replay protection


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_on_charged_call_without_key_is_not_retried(status: int, sleeps: list[float]) -> None:
    script = Script(err(status, "internal_error" if status == 500 else None), OK)
    with pytest.raises(VaquillError):
        make(script, idempotency_keys=False).raw_request("POST", "/x", json={}, charged=True)
    assert len(script.requests) == 1


def test_5xx_on_charged_call_with_key_still_retried(sleeps: list[float]) -> None:
    script = Script(err(503), OK)
    make(script).raw_request("POST", "/x", json={}, charged=True)
    assert len(script.requests) == 2


def test_429_on_charged_call_without_key_still_retried(sleeps: list[float]) -> None:
    script = Script(err(429, "rate_limited"), OK)
    make(script, idempotency_keys=False).raw_request("POST", "/x", json={}, charged=True)
    assert len(script.requests) == 2


@pytest.mark.parametrize("code", [None, "internal_error", "service_unavailable"])
def test_501_is_never_retried(code: str | None, sleeps: list[float]) -> None:
    script = Script(err(501, code), OK)
    with pytest.raises(InternalServerError):
        make(script).raw_request("GET", "/x")
    assert len(script.requests) == 1


# 9. response parse errors


class Strict(BaseModel):
    count: int


def test_validation_error_becomes_response_parse_error() -> None:
    client = make(
        Script(httpx.Response(200, json={"count": "many"}, headers={"X-Request-ID": "rq9"}))
    )
    with pytest.raises(ResponseParseError) as info:
        client.request("GET", "/x", cast_to=Strict)
    assert isinstance(info.value, VaquillError)
    assert info.value.request_id == "rq9" and info.value.status_code == 200


def test_invalid_json_body_is_response_parse_error() -> None:
    client = make(Script(httpx.Response(200, content=b"<html>", headers={"X-Request-ID": "rq1"})))
    with pytest.raises(ResponseParseError) as info:
        client.raw_request("GET", "/x")
    assert info.value.request_id == "rq1"


async def test_async_validation_error_becomes_response_parse_error() -> None:
    client = amake(Script(httpx.Response(200, json={"count": "many"})))
    with pytest.raises(ResponseParseError):
        await client.request("GET", "/x", cast_to=Strict)


# 10. Deprecation / Sunset


def test_deprecation_logged_once_per_method_and_path(caplog: pytest.LogCaptureFixture) -> None:
    dep = {"Deprecation": "true", "Sunset": "Wed, 01 Jul 2027 00:00:00 GMT"}
    script = Script(*(httpx.Response(200, json={}, headers=dep) for _ in range(4)))
    client = make(script)
    with caplog.at_level(logging.WARNING, logger="vaquill"):
        client.raw_request("GET", "/old")
        client.raw_request("GET", "/old?x=1")
        client.raw_request("POST", "/old", json={})
        client.raw_request("GET", "/other")
    msgs = [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage()]
    assert len(msgs) == 3
    assert "Sunset: Wed, 01 Jul 2027 00:00:00 GMT" in msgs[0] and "GET /old" in msgs[0]


def test_no_deprecation_headers_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="vaquill"):
        make(Script(OK)).raw_request("GET", "/x")
    assert not caplog.records


def test_deprecation_warning_on_error_response_too(caplog: pytest.LogCaptureFixture) -> None:
    resp = err(404, **{"Sunset": "soon"})
    with caplog.at_level(logging.WARNING, logger="vaquill"), pytest.raises(VaquillError):
        make(Script(resp)).raw_request("GET", "/gone")
    assert any("Sunset: soon" in r.getMessage() for r in caplog.records)


_ = Any
