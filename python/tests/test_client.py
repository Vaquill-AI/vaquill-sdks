from __future__ import annotations

import logging

import httpx
import pytest

from vaquill import SpendGuardExceeded, Vaquill, VaquillError, VaquillModel, __version__
from vaquill._response import ResponseModel

from .conftest import KEY, Script, amake, make

OK = httpx.Response(200, json={"hello": "world", "creditsConsumed": 4})


def test_user_agent_and_auth() -> None:
    script = Script(OK)
    make(script).raw_request("GET", "/x")
    req = script.requests[0]
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["user-agent"].startswith(f"vaquill-python/{__version__} python/3.")


def test_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAQUILL_API_KEY", KEY)
    monkeypatch.setenv("VAQUILL_BASE_URL", "https://example.test/")
    client = Vaquill()
    assert client.base_url == "https://example.test"
    assert Vaquill(api_key=KEY, base_url="https://other.test").base_url == "https://other.test"


def test_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_BASE_URL", raising=False)
    assert Vaquill(api_key=KEY).base_url == "https://api.vaquill.ai"


def test_missing_and_malformed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    with pytest.raises(VaquillError, match="No API key"):
        Vaquill()
    with pytest.raises(VaquillError, match="vq_key_") as info:
        Vaquill(api_key="sk-secret-value")
    assert "sk-secret-value" not in str(info.value)


def test_key_never_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="vaquill")
    client = make(Script(OK))
    client.raw_request("POST", "/x", json={}, charged=True)
    assert KEY not in repr(client)
    assert KEY not in caplog.text
    assert "Request POST" in caplog.text


def test_default_headers_cannot_override_authorization() -> None:
    script = Script(OK)
    make(script, default_headers={"X-Team": "a", "Authorization": "Bearer evil"}).raw_request(
        "GET", "/x"
    )
    assert script.requests[0].headers["x-team"] == "a"
    assert script.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_none_params_dropped_and_path_joined() -> None:
    script = Script(OK)
    make(script, base_url="https://h.test").raw_request("GET", "x", params={"a": 1, "b": None})
    assert str(script.requests[0].url) == "https://h.test/x?a=1"


def test_with_options_shares_spend_and_http() -> None:
    script = Script(OK, OK)
    client = make(script)
    derived = client.with_options(max_retries=0, default_headers={"X-A": "1"})
    derived.raw_request("POST", "/x", json={}, charged=True)
    assert client.credits_spent == 4
    assert derived.max_retries == 0 and client.max_retries == 2
    assert script.requests[0].headers["x-a"] == "1"
    derived.close()  # shared client is not owned by the copy
    client.raw_request("GET", "/x")


def test_context_manager_closes_owned_client() -> None:
    with Vaquill(api_key=KEY) as client:
        assert not client._http.is_closed  # pyright: ignore[reportPrivateUsage]
    assert client._http.is_closed  # pyright: ignore[reportPrivateUsage]


def test_injected_client_not_closed() -> None:
    http = httpx.Client(transport=httpx.MockTransport(Script()))
    with Vaquill(api_key=KEY, http_client=http):
        pass
    assert not http.is_closed


class Thing(ResponseModel):
    hello: str


def test_cast_to_model_extra_fields_and_metering() -> None:
    script = Script(
        httpx.Response(
            200,
            json={"hello": "w", "creditsConsumed": 4, "brandNew": 1},
            headers={"X-Request-ID": "req_9"},
        )
    )
    thing = make(script).request("GET", "/x", cast_to=Thing)
    assert thing.hello == "w"
    assert thing.credits_consumed == 4
    assert thing.request_id == "req_9"
    assert thing.model_extra == {"brandNew": 1}


def test_models_are_camel_aliased_and_lenient() -> None:
    class Inner(VaquillModel):
        act_id: str

    assert Inner.model_validate({"actId": "a", "x": 1}).act_id == "a"


def test_spend_guard() -> None:
    script = Script(OK, OK, OK)
    client = make(script, max_credits=8)
    client.raw_request("POST", "/x", json={}, charged=True)
    client.raw_request("POST", "/x", json={}, charged=True)
    with pytest.raises(SpendGuardExceeded):
        client.raw_request("POST", "/x", json={}, charged=True)
    assert len(script.requests) == 2
    client.raw_request("GET", "/credits/balance")  # free calls still work


def test_replay_does_not_count_towards_spend() -> None:
    replay = httpx.Response(
        200, json={"creditsConsumed": 4}, headers={"Idempotent-Replayed": "true"}
    )
    client = make(Script(replay), max_credits=100)
    resp = client.raw_request("POST", "/x", json={}, charged=True)
    assert resp.idempotent_replayed and resp.credits_charged_this_call == 0
    assert client.credits_spent == 0


def test_with_raw_response_metadata() -> None:
    script = Script(
        httpx.Response(
            200,
            json={"hello": "w", "creditsConsumed": 2},
            headers={
                "X-Request-ID": "req_1",
                "X-RateLimit-Limit": "60",
                "X-RateLimit-Remaining": "59",
                "X-RateLimit-Reset": "12.5",
                "X-RateLimit-Limit-Day": "1000",
                "X-RateLimit-Remaining-Day": "990",
            },
        )
    )
    raw = make(script).with_raw_response.request("GET", "/x", cast_to=Thing)
    assert raw.request_id == "req_1"
    assert raw.credits_consumed == 2
    assert (raw.rate_limit.limit, raw.rate_limit.remaining, raw.rate_limit.reset) == (60, 59, 12.5)
    assert (raw.rate_limit.limit_day, raw.rate_limit.remaining_day) == (1000, 990)
    assert raw.rate_limit.reset_day is None
    assert raw.parse().hello == "w"


def test_invalid_json_success_raises() -> None:
    with pytest.raises(VaquillError, match="not valid JSON"):
        make(Script(httpx.Response(200, content=b"<html>"))).raw_request("GET", "/x")


async def test_async_parity_and_context_manager() -> None:
    async with amake(Script(OK)) as client:
        resp = await client.raw_request("GET", "/x")
        assert resp.credits_consumed == 4
