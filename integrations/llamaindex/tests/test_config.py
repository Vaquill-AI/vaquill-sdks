"""Key and client configuration, User-Agent suffix and async fallbacks."""

import asyncio
import sys

import pytest
from conftest import TEST_KEY
from fake_server import FakeVaquillServer
from vaquill import AsyncVaquill, Vaquill

from llama_index.retrievers.vaquill import VaquillRetriever
from llama_index.tools.vaquill import INTEGRATION_NAME, VaquillToolSpec, __version__, integration_user_agent


def test_missing_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="VAQUILL_API_KEY"):
        VaquillToolSpec()
    with pytest.raises(ValueError, match="VAQUILL_API_KEY"):
        VaquillRetriever()


def test_key_from_environment(monkeypatch: pytest.MonkeyPatch, server: FakeVaquillServer) -> None:
    monkeypatch.setenv("VAQUILL_API_KEY", TEST_KEY)
    tools = VaquillToolSpec(base_url=server.url)
    tools.get_credit_balance()
    assert server.last("get_credit_balance").headers["authorization"] == f"Bearer {TEST_KEY}"


def test_explicit_key_wins_over_environment(monkeypatch: pytest.MonkeyPatch, server: FakeVaquillServer) -> None:
    monkeypatch.setenv("VAQUILL_API_KEY", "vq_key_from_env")
    VaquillToolSpec(api_key=TEST_KEY, base_url=server.url).get_credit_balance()
    assert server.last().headers["authorization"] == f"Bearer {TEST_KEY}"


def test_base_url_from_environment(monkeypatch: pytest.MonkeyPatch, server: FakeVaquillServer) -> None:
    monkeypatch.setenv("VAQUILL_BASE_URL", server.url)
    VaquillToolSpec(api_key=TEST_KEY).get_credit_balance()
    assert server.requests


def test_user_agent_has_sdk_and_integration_tokens(server: FakeVaquillServer) -> None:
    VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, user_agent_suffix="my-agent/2").get_credit_balance()
    agent = server.last().headers["user-agent"]
    assert agent.startswith("vaquill-python/")
    assert f"{INTEGRATION_NAME}/{__version__}" in agent
    assert agent.endswith("my-agent/2")


async def test_user_agent_on_async_client(server: FakeVaquillServer) -> None:
    await VaquillToolSpec(api_key=TEST_KEY, base_url=server.url).get_credit_balance_async()
    assert f"{INTEGRATION_NAME}/{__version__}" in server.last().headers["user-agent"]


def test_integration_user_agent_helper() -> None:
    assert integration_user_agent().endswith(f"{INTEGRATION_NAME}/{__version__}")
    assert integration_user_agent("  a   b ").endswith("a b")


def test_retriever_sends_same_user_agent(server: FakeVaquillServer) -> None:
    VaquillRetriever(api_key=TEST_KEY, base_url=server.url).retrieve("q")
    assert INTEGRATION_NAME in server.last().headers["user-agent"]


def test_prebuilt_client_is_used_as_is(server: FakeVaquillServer) -> None:
    client = Vaquill(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    tools = VaquillToolSpec(client=client)
    assert "creditsRemaining" in tools.get_credit_balance()
    assert server.last().headers["user-agent"].startswith("vaquill-python/")
    assert INTEGRATION_NAME not in server.last().headers["user-agent"]


async def test_prebuilt_sync_client_serves_async_calls_in_a_thread(server: FakeVaquillServer) -> None:
    client = Vaquill(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    tools = VaquillToolSpec(client=client)
    assert "creditsRemaining" in await tools.get_credit_balance_async()
    assert tools._conn.async_client is None


async def test_prebuilt_async_client_is_used(server: FakeVaquillServer) -> None:
    async_client = AsyncVaquill(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    tools = VaquillToolSpec(async_client=async_client)
    assert "creditsRemaining" in await tools.get_credit_balance_async()
    assert tools._conn.async_client is async_client


def test_prebuilt_async_only_uses_key_for_sync(server: FakeVaquillServer) -> None:
    async_client = AsyncVaquill(api_key=TEST_KEY, base_url=server.url)
    tools = VaquillToolSpec(api_key=TEST_KEY, async_client=async_client, base_url=server.url)
    assert "creditsRemaining" in tools.get_credit_balance()


def test_secrets_listing_contains_key_only_when_known(server: FakeVaquillServer) -> None:
    assert VaquillToolSpec(api_key=TEST_KEY, base_url=server.url)._conn.secrets == [TEST_KEY]
    client = Vaquill(api_key=TEST_KEY, base_url=server.url)
    assert VaquillToolSpec(client=client)._conn.secrets == []


def test_timeout_and_retries_are_passed_on(server: FakeVaquillServer) -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, timeout=3, max_retries=0)
    assert tools._conn.sync_client.max_retries == 0


def test_tool_spec_is_usable_from_a_running_loop_via_async(server: FakeVaquillServer) -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url)

    async def go() -> str:
        return await asyncio.gather(tools.get_credit_balance_async(), tools.get_credit_balance_async())  # type: ignore[return-value]

    assert len(asyncio.run(go())) == 2


def test_python_version_supported() -> None:
    assert sys.version_info >= (3, 11)
