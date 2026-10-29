"""Error mapping: SDK exceptions become ToolExceptions a model can act on."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from conftest import KEY
from langchain_core.tools import ToolException
from vaquill import APIConnectionError, APITimeoutError, ResponseParseError, VaquillError
from vaquill._errors import make_status_error

from langchain_vaquill import VaquillToolkit
from langchain_vaquill._errors import redact, to_tool_exception

CASES = [
    (401, {"detail": "bad key"}, {}, "check VAQUILL_API_KEY"),
    (402, {"detail": "no credits", "code": "insufficient_credits"}, {}, "out of credits"),
    (403, {"detail": "nope"}, {}, "not allowed"),
    (404, {"detail": "no such section"}, {}, "vaquill_resolve_citation"),
    (400, {"detail": "limit too big"}, {}, "Fix the arguments"),
    (422, {"detail": "Validation error"}, {}, "Fix the arguments"),
    (409, {"detail": "busy"}, {}, "Conflict"),
    (429, {"detail": "slow down", "retryAfterSeconds": 7}, {}, "about 7 seconds"),
    (429, {"detail": "cap", "code": "daily_cap_exceeded"}, {}, "daily call cap"),
    (500, {"detail": "boom"}, {}, "server error"),
    (418, {"detail": "teapot"}, {}, "(418)"),
    (409, {"detail": "x", "code": "idempotency_in_progress"}, {}, "in-flight"),
]


@pytest.mark.parametrize(("status", "body", "headers", "expected"), CASES)
def test_status_errors_map_to_actionable_messages(
    status: int,
    body: Any,
    headers: dict[str, str],
    expected: str,
    tools: dict[str, Any],
    server: Any,
) -> None:
    server.override("get_section", status, body, headers)
    tool = tools["vaquill_get_statute_section"]
    with pytest.raises(ToolException) as info:
        tool._run(act_id="X")
    message = str(info.value)
    assert expected in message
    assert "Traceback" not in message and KEY not in message
    # Through invoke the model receives the same text instead of an exception.
    assert tool.invoke({"act_id": "X"}) == message


async def test_async_errors_map_too(tools: dict[str, Any], server: Any) -> None:
    server.override("get_credit_balance", 402, {"detail": "x", "code": "insufficient_credits"})
    out = await tools["vaquill_credit_balance"].ainvoke({})
    assert "out of credits" in out


def test_request_id_is_included(tools: dict[str, Any], server: Any) -> None:
    server.override("get_section", 500, {"detail": "boom", "requestId": "req_123"})
    assert "req_123" in tools["vaquill_get_statute_section"].invoke({"act_id": "X"})


def test_server_text_cannot_leak_a_key(tools: dict[str, Any], server: Any) -> None:
    server.override("get_section", 400, {"detail": f"bad Bearer {KEY} and {KEY}"})
    out = tools["vaquill_get_statute_section"].invoke({"act_id": "X"})
    assert KEY not in out and "[redacted]" in out


def test_long_server_message_is_cut(tools: dict[str, Any], server: Any) -> None:
    server.override("get_section", 400, {"detail": "z" * 5000})
    assert len(tools["vaquill_get_statute_section"].invoke({"act_id": "X"})) < 700


def test_unparseable_response(tools: dict[str, Any], server: Any) -> None:
    server.override("get_credit_balance", 200, {"unexpected": True})
    assert "could not read" in tools["vaquill_credit_balance"].invoke({})


def test_connection_error_when_server_is_gone(provider_kwargs: dict[str, Any]) -> None:
    kwargs = {**provider_kwargs, "base_url": "http://127.0.0.1:1"}
    tool = {t.name: t for t in VaquillToolkit(**kwargs).get_tools()}["vaquill_credit_balance"]
    assert "Could not reach" in tool.invoke({})


def test_invalid_path_argument_is_a_clean_message(tools: dict[str, Any]) -> None:
    out = tools["vaquill_get_statute_section"].invoke({"act_id": ".."})
    assert out.startswith("Invalid argument")


def test_direct_mapping_of_transport_errors() -> None:
    req = httpx.Request("GET", "http://x")
    assert "timed out" in str(to_tool_exception(APITimeoutError(request=req)))
    assert "network" in str(to_tool_exception(APIConnectionError(request=req)))
    assert "could not read" in str(to_tool_exception(ResponseParseError("bad")))
    assert "client error" in str(to_tool_exception(VaquillError(f"oops {KEY}")))
    assert KEY not in str(to_tool_exception(VaquillError(f"oops {KEY}")))
    assert "Unexpected KeyError" in str(to_tool_exception(KeyError("k")))
    existing = ToolException("already")
    assert to_tool_exception(existing) is existing


def test_make_status_error_roundtrip_has_no_stack() -> None:
    resp = httpx.Response(402, json={"detail": "x"}, request=httpx.Request("GET", "http://x"))
    message = str(to_tool_exception(make_status_error(resp, {"detail": "x"})))
    assert "\n" not in message


def test_redact() -> None:
    assert redact("a vq_key_abc123 b") == "a [redacted] b"
    assert redact("Authorization: Bearer abc.def") == "Authorization: [redacted]"
    assert redact("whsec_QUJD") == "[redacted]"
