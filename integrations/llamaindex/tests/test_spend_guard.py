"""The max_credits guard for the tool spec and the retriever."""

import pytest
from conftest import TEST_KEY
from fake_server import FakeVaquillServer
from vaquill import SpendGuardExceeded, Vaquill

from llama_index.retrievers.vaquill import VaquillRetriever
from llama_index.tools.vaquill import VaquillToolSpec


def _priced_search(server: FakeVaquillServer, credits: float) -> None:
    server.set(
        "search_statutes",
        200,
        {
            "creditsConsumed": credits,
            "count": 1,
            "hasMore": False,
            "offset": 0,
            "query": "q",
            "results": [{"actId": "A1", "citation": "1 U.S.C. 1", "excerpt": "Text."}],
        },
    )


def test_tool_stops_once_cap_is_reached(server: FakeVaquillServer) -> None:
    _priced_search(server, 4)
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, max_credits=5)
    assert not tools.search_statutes("q").startswith("Vaquill error")
    assert tools.credits_spent == 4
    assert not tools.search_statutes("q").startswith("Vaquill error")  # 4 < 5, still allowed
    blocked = tools.search_statutes("q")
    assert blocked.startswith("Vaquill error: Spend guard reached")
    assert len([r for r in server.requests if r.method == "POST"]) == 2


async def test_cap_counts_sync_and_async_together(server: FakeVaquillServer) -> None:
    _priced_search(server, 4)
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, max_credits=8)
    tools.search_statutes("q")
    await tools.search_statutes_async("q")
    assert tools.credits_spent == 8
    assert "Spend guard" in tools.search_statutes("q")
    assert "Spend guard" in await tools.search_statutes_async("q")


def test_free_calls_do_not_spend(server: FakeVaquillServer) -> None:
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_credits=1)
    for _ in range(3):
        assert "creditsRemaining" in tools.get_credit_balance()
    assert tools.credits_spent == 0


def test_cap_inherited_from_prebuilt_client(server: FakeVaquillServer) -> None:
    _priced_search(server, 4)
    client = Vaquill(api_key=TEST_KEY, base_url=server.url, max_retries=0, max_credits=4)
    tools = VaquillToolSpec(client=client)
    assert tools._conn.max_credits == 4
    tools.search_statutes("q")
    assert "Spend guard" in tools.search_statutes("q")


def test_explicit_cap_applies_to_prebuilt_client(server: FakeVaquillServer) -> None:
    _priced_search(server, 4)
    client = Vaquill(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    tools = VaquillToolSpec(client=client, max_credits=4)
    tools.search_statutes("q")
    assert "Spend guard" in tools.search_statutes("q")


def test_retriever_refuses_when_worst_case_would_pass_cap(server: FakeVaquillServer) -> None:
    retriever = VaquillRetriever(api_key=TEST_KEY, base_url=server.url, similarity_top_k=5, max_credits=20)
    assert retriever.worst_case_credits == 34
    with pytest.raises(SpendGuardExceeded):
        retriever.retrieve("q")
    assert not server.requests


async def test_retriever_async_refuses_before_any_request(server: FakeVaquillServer) -> None:
    retriever = VaquillRetriever(api_key=TEST_KEY, base_url=server.url, similarity_top_k=5, max_credits=20)
    with pytest.raises(SpendGuardExceeded):
        await retriever.aretrieve("q")
    assert not server.requests


def test_retriever_without_body_has_small_worst_case(server: FakeVaquillServer) -> None:
    _priced_search(server, 4)
    retriever = VaquillRetriever(
        api_key=TEST_KEY, base_url=server.url, similarity_top_k=5, include_body=False, max_credits=9, max_retries=0
    )
    assert retriever.worst_case_credits == 4
    retriever.retrieve("q")
    retriever.retrieve("q")  # 4 spent + 4 worst case = 8 <= 9
    assert retriever.credits_spent == 8
    with pytest.raises(SpendGuardExceeded):
        retriever.retrieve("q")  # 8 + 4 > 9
    assert len(server.requests) == 2
