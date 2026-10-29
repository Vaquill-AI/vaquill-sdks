"""Error mapping: short, actionable, no stack trace, no key."""

from typing import Any, Dict

import pytest
from conftest import TEST_KEY
from fake_server import FakeVaquillServer

from llama_index.tools.vaquill import VaquillToolError, VaquillToolSpec
from llama_index.tools.vaquill._errors import describe_error, sanitize

CASES = [
    (401, {"detail": "bad key"}, "rejected the API key"),
    (402, {"detail": "no credits"}, "Out of credits"),
    (403, {"detail": "nope"}, "may not use that endpoint"),
    (404, {"detail": "no such section"}, "Not found"),
    (400, {"detail": "limit must be <= 50"}, "request was invalid"),
    (422, {"detail": "bad value"}, "request was invalid"),
    (429, {"detail": "slow down", "retryAfterSeconds": 7}, "about 7 seconds"),
    (500, {"detail": "boom"}, "server error"),
    (418, {"detail": "teapot"}, "status 418"),
]


@pytest.mark.parametrize(("status", "body", "expected"), CASES)
async def test_status_errors_become_short_messages(
    spec: VaquillToolSpec, server: FakeVaquillServer, status: int, body: Dict[str, Any], expected: str
) -> None:
    server.set("get_section", status, body)
    for result in (spec.get_section("A1"), await spec.get_section_async("A1")):
        assert result.startswith("Vaquill error: ")
        assert expected in result
        assert "Traceback" not in result
        assert TEST_KEY not in result
        assert len(result) < 500


def test_daily_cap_says_do_not_retry(spec: VaquillToolSpec, server: FakeVaquillServer) -> None:
    server.set("get_section", 429, {"detail": "daily cap", "code": "daily_cap_exceeded"})
    result = spec.get_section("A1")
    assert result.startswith("Vaquill error: ")
    assert "daily" in result.lower() or "Rate limited" in result


def test_key_echoed_by_server_is_scrubbed(spec: VaquillToolSpec, server: FakeVaquillServer) -> None:
    server.set("get_section", 400, {"detail": f"invalid header Bearer {TEST_KEY} and {TEST_KEY}"})
    result = spec.get_section("A1")
    assert TEST_KEY not in result
    assert "[redacted]" in result


def test_raise_on_error_raises_sanitized_error_without_chain(server: FakeVaquillServer) -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, raise_on_error=True)
    server.set("get_section", 401, {"detail": "bad"})
    with pytest.raises(VaquillToolError) as info:
        tools.get_section("A1")
    assert TEST_KEY not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


async def test_raise_on_error_async(server: FakeVaquillServer) -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, raise_on_error=True)
    server.set("get_section", 404, {"detail": "gone"})
    with pytest.raises(VaquillToolError, match="Not found"):
        await tools.get_section_async("A1")


def test_bad_path_argument_is_an_invalid_argument_message(spec: VaquillToolSpec, server: FakeVaquillServer) -> None:
    result = spec.get_section("..")
    assert result.startswith("Vaquill error: Invalid argument")
    assert not server.requests


def test_connection_error_message() -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url="http://127.0.0.1:9", max_retries=0, timeout=2)
    result = tools.get_credit_balance()
    assert result.startswith("Vaquill error: ")
    assert "Could not reach" in result or "timed out" in result
    assert TEST_KEY not in result


def test_unparseable_response_message(spec: VaquillToolSpec, server: FakeVaquillServer) -> None:
    server.set("get_credit_balance", 200, {"creditsRemaining": "not-a-number"})
    result = spec.get_credit_balance()
    assert result.startswith("Vaquill error: ")
    assert "could not read" in result


def test_describe_error_unknown_exception_hides_details() -> None:
    result = describe_error(RuntimeError("secret internals vq_key_abc123"))
    assert "Unexpected RuntimeError" in result
    assert "vq_key" not in result


def test_describe_error_generic_vaquill_error_is_sanitized() -> None:
    from vaquill import VaquillError

    result = describe_error(VaquillError("Invalid key vq_key_abcdef"))
    assert "vq_key_abcdef" not in result


def test_sanitize_caps_length_and_removes_secrets() -> None:
    text = "token " + "y" * 1000 + " hunter2"
    out = sanitize(text, secrets=["hunter2", ""])
    assert len(out) <= 304
    assert sanitize("a hunter2 b", secrets=["hunter2"]) == "a [redacted] b"
