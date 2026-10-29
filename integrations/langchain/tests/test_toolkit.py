"""Toolkit selection, opt-in watch tools, spend guard and client reuse."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import KEY
from vaquill import AsyncVaquill, Vaquill

from langchain_vaquill import READ_ONLY_TOOLS, WATCH_WRITE_TOOLS, VaquillToolkit
from langchain_vaquill.tools import tool_name

WATCH_NAMES = {tool_name(c) for c in WATCH_WRITE_TOOLS}


def test_default_is_read_only(provider_kwargs: dict[str, Any]) -> None:
    names = {t.name for t in VaquillToolkit(**provider_kwargs).get_tools()}
    assert names == {tool_name(c) for c in READ_ONLY_TOOLS}
    assert not names & WATCH_NAMES


def test_watch_tools_need_the_flag(provider_kwargs: dict[str, Any]) -> None:
    names = {
        t.name for t in VaquillToolkit(**provider_kwargs, include_watch_tools=True).get_tools()
    }
    assert names >= WATCH_NAMES


def test_selecting_a_watch_tool_without_the_flag_fails(provider_kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="include_watch_tools"):
        VaquillToolkit(**provider_kwargs, tools=["vaquill_delete_watch"])


def test_selection_by_name_and_unknown_names(provider_kwargs: dict[str, Any]) -> None:
    kit = VaquillToolkit(
        **provider_kwargs, tools=["vaquill_search_statutes", "vaquill_search_statutes"]
    )
    assert [t.name for t in kit.get_tools()] == ["vaquill_search_statutes"]
    with pytest.raises(ValueError, match="Unknown Vaquill tool"):
        VaquillToolkit(**provider_kwargs, tools=["vaquill_nope"])


def test_free_only(provider_kwargs: dict[str, Any], server: Any) -> None:
    tools = VaquillToolkit(**provider_kwargs, free_only=True).get_tools()
    names = {t.name for t in tools}
    assert "vaquill_credit_balance" in names and "vaquill_search_statutes" not in names
    assert "vaquill_get_statute_text" not in names


def test_available_tool_names() -> None:
    assert "vaquill_create_watch" in VaquillToolkit.available_tool_names()
    assert "vaquill_create_watch" not in VaquillToolkit.available_tool_names(
        include_watch_tools=False
    )


def test_tool_names_are_unique_and_prefixed() -> None:
    names = VaquillToolkit.available_tool_names()
    assert len(names) == len(set(names))
    assert all(n.startswith("vaquill_") for n in names)


def test_spend_guard_stops_paid_calls(provider_kwargs: dict[str, Any], server: Any) -> None:
    kit = VaquillToolkit(**provider_kwargs, max_credits=4)
    tool = {t.name: t for t in kit.get_tools()}["vaquill_search_statutes"]
    assert '"results"' in tool.invoke({"query": "a"})
    assert kit.credits_spent == 4
    out = tool.invoke({"query": "b"})
    assert "credit limit" in out and "Do not retry" in out
    assert len(server.calls("search_statutes")) == 1  # the second call never left the process


async def test_spend_guard_async(provider_kwargs: dict[str, Any], server: Any) -> None:
    kit = VaquillToolkit(**provider_kwargs, max_credits=4)
    tool = {t.name: t for t in kit.get_tools()}["vaquill_search_statutes"]
    await tool.ainvoke({"query": "a"})
    assert "credit limit" in await tool.ainvoke({"query": "b"})
    await kit.aclose()


def test_free_tools_work_after_the_cap(provider_kwargs: dict[str, Any]) -> None:
    kit = VaquillToolkit(**provider_kwargs, max_credits=4)
    tools = {t.name: t for t in kit.get_tools()}
    tools["vaquill_search_statutes"].invoke({"query": "a"})
    assert "1234" in tools["vaquill_credit_balance"].invoke({})


def test_api_key_from_environment(monkeypatch: pytest.MonkeyPatch, server: Any) -> None:
    monkeypatch.setenv("VAQUILL_API_KEY", KEY)
    tool = {t.name: t for t in VaquillToolkit(base_url=server.url).get_tools()}[
        "vaquill_credit_balance"
    ]
    tool.invoke({})
    assert server.requests[0]["headers"]["authorization"] == f"Bearer {KEY}"


def test_missing_key_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="VAQUILL_API_KEY"):
        VaquillToolkit()


def test_key_is_not_in_repr(provider_kwargs: dict[str, Any]) -> None:
    kit = VaquillToolkit(**provider_kwargs)
    assert (
        KEY not in repr(kit)
        and KEY not in repr(kit.get_tools()[0])
        and KEY not in str(kit.model_dump())
    )


def test_reuses_a_passed_client_and_marks_the_user_agent(server: Any) -> None:
    client = Vaquill(api_key=KEY, base_url=server.url, max_retries=0)
    kit = VaquillToolkit(client=client)
    {t.name: t for t in kit.get_tools()}["vaquill_credit_balance"].invoke({})
    ua = server.requests[0]["headers"]["user-agent"]
    assert ua.startswith("vaquill-python/") and "langchain-vaquill/0.1.0" in ua
    kit.close()
    # The caller's client is still usable after the toolkit is closed.
    assert client.credits.balance().credits_remaining == 1234


def test_passed_client_spend_is_shared(server: Any) -> None:
    client = Vaquill(api_key=KEY, base_url=server.url, max_retries=0)
    kit = VaquillToolkit(client=client, max_credits=100)
    {t.name: t for t in kit.get_tools()}["vaquill_search_statutes"].invoke({"query": "a"})
    assert client.credits_spent == 4 and kit.credits_spent == 4


async def test_sync_client_only_serves_async_calls_in_a_thread(server: Any) -> None:
    client = Vaquill(api_key=KEY, base_url=server.url, max_retries=0)
    tool = {t.name: t for t in VaquillToolkit(client=client).get_tools()}["vaquill_credit_balance"]
    assert "1234" in await tool.ainvoke({})


async def test_async_client_only_rejects_sync_calls(server: Any) -> None:
    aclient = AsyncVaquill(api_key=KEY, base_url=server.url, max_retries=0)
    tool = {t.name: t for t in VaquillToolkit(async_client=aclient).get_tools()}[
        "vaquill_credit_balance"
    ]
    assert "1234" in await tool.ainvoke({})
    assert "async interface" in tool.invoke({})
    await aclient.aclose()


def test_extra_default_headers_survive_on_a_passed_client(server: Any) -> None:
    client = Vaquill(
        api_key=KEY, base_url=server.url, max_retries=0, default_headers={"X-Team": "legal"}
    )
    {t.name: t for t in VaquillToolkit(client=client).get_tools()}["vaquill_credit_balance"].invoke(
        {}
    )
    headers = server.requests[0]["headers"]
    assert headers["x-team"] == "legal" and "langchain-vaquill" in headers["user-agent"]


def test_a_bad_key_type_is_rejected() -> None:
    from langchain_vaquill import ClientProvider

    with pytest.raises(TypeError):
        ClientProvider(api_key=123)  # type: ignore[arg-type]
