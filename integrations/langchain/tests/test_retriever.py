"""VaquillRetriever: documents, filters, k and the hard spend guard."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import KEY, ROW
from langchain_core.documents import Document
from vaquill import SpendGuardExceeded, Vaquill

from langchain_vaquill import VaquillRetriever


def make(provider_kwargs: dict[str, Any], **kw: Any) -> VaquillRetriever:
    return VaquillRetriever(**provider_kwargs, **kw)


def test_documents_and_metadata(provider_kwargs: dict[str, Any], server: Any) -> None:
    docs = make(provider_kwargs).invoke("civil rights")
    assert len(docs) == 1 and isinstance(docs[0], Document)
    doc = docs[0]
    assert doc.page_content == ROW["body"]
    assert doc.id == ROW["actId"]
    assert doc.metadata == {
        "id": "USC_T42_C21_S1983",
        "citation": "42 U.S.C. § 1983",
        "jurisdiction": "federal",
        "sourceUrl": ROW["sourceUrl"],
        "corpusType": "USC",
        "actStatus": "in_force",
        "sectionTitle": ROW["sectionTitle"],
        "effectiveDate": "1871-04-20",
        "lastAmendedDate": "1996-10-19",
        "currentThrough": "2025-03-15",
        "score": 0.91,
    }


def test_k_filters_and_body_flag_reach_the_wire(
    provider_kwargs: dict[str, Any], server: Any
) -> None:
    r = make(
        provider_kwargs, k=7, filters={"state": "ca", "corpus_type": ["STATE"], "year_from": None}
    )
    r.invoke("homicide")
    body = server.requests[0]["json"]
    assert body["limit"] == 7 and body["state"] == "ca" and body["corpusType"] == ["STATE"]
    assert body["includeBody"] is True and "yearFrom" not in body and body["query"] == "homicide"


def test_excerpt_mode(provider_kwargs: dict[str, Any], server: Any) -> None:
    docs = make(provider_kwargs, include_body=False).invoke("x")
    assert docs[0].page_content == ROW["excerpt"]
    assert server.requests[0]["json"]["includeBody"] is False


def test_empty_results(provider_kwargs: dict[str, Any], server: Any) -> None:
    server.override("search_statutes", 200, {"query": "x", "results": [], "creditsConsumed": 4})
    assert make(provider_kwargs).invoke("x") == []


async def test_async(provider_kwargs: dict[str, Any], server: Any) -> None:
    docs = await make(provider_kwargs).ainvoke("x")
    assert docs[0].metadata["citation"] == "42 U.S.C. § 1983"


def test_unknown_filter_is_rejected(provider_kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Unsupported filter"):
        make(provider_kwargs, filters={"bogus": 1})


def test_k_bounds(provider_kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make(provider_kwargs, k=0)
    with pytest.raises(ValueError):
        make(provider_kwargs, k=51)


def test_estimated_cost(provider_kwargs: dict[str, Any]) -> None:
    assert make(provider_kwargs, k=3).estimated_call_cost == 4 + 6 * 3
    assert make(provider_kwargs, k=3, include_body=False).estimated_call_cost == 4


def test_guard_refuses_before_sending(provider_kwargs: dict[str, Any], server: Any) -> None:
    r = make(provider_kwargs, k=5, max_credits=10)  # one call may cost up to 34
    with pytest.raises(SpendGuardExceeded, match="No request was sent"):
        r.invoke("x")
    assert server.requests == []


def test_guard_counts_real_spend_across_calls(provider_kwargs: dict[str, Any], server: Any) -> None:
    r = make(provider_kwargs, k=1, include_body=False, max_credits=9)  # 4 per call
    r.invoke("a")
    r.invoke("b")
    assert r.credits_spent == 8
    with pytest.raises(SpendGuardExceeded):
        r.invoke("c")
    assert len(server.calls("search_statutes")) == 2


async def test_guard_async(provider_kwargs: dict[str, Any], server: Any) -> None:
    r = make(provider_kwargs, k=1, include_body=False, max_credits=4)
    await r.ainvoke("a")
    with pytest.raises(SpendGuardExceeded):
        await r.ainvoke("b")


def test_sdk_guard_is_a_second_line_of_defence(server: Any) -> None:
    client = Vaquill(api_key=KEY, base_url=server.url, max_retries=0)
    r = VaquillRetriever(client=client, k=1, include_body=False, max_credits=4)
    r.invoke("a")
    assert client.credits_spent == 4
    with pytest.raises(SpendGuardExceeded):
        r.invoke("b")


def test_api_errors_become_tool_exceptions(provider_kwargs: dict[str, Any], server: Any) -> None:
    from langchain_core.tools import ToolException

    server.override("search_statutes", 402, {"detail": "no", "code": "insufficient_credits"})
    with pytest.raises(ToolException, match="out of credits"):
        make(provider_kwargs).invoke("x")


async def test_async_api_errors(provider_kwargs: dict[str, Any], server: Any) -> None:
    from langchain_core.tools import ToolException

    server.override("search_statutes", 500, {"detail": "boom"})
    with pytest.raises(ToolException, match="server error"):
        await make(provider_kwargs).ainvoke("x")


def test_user_agent_and_key_hygiene(provider_kwargs: dict[str, Any], server: Any) -> None:
    r = make(provider_kwargs)
    r.invoke("x")
    assert "langchain-vaquill/0.1.0" in server.requests[0]["headers"]["user-agent"]
    assert KEY not in repr(r)


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="VAQUILL_API_KEY"):
        VaquillRetriever()


def test_body_missing_falls_back_to_excerpt(provider_kwargs: dict[str, Any], server: Any) -> None:
    row = {k: v for k, v in ROW.items() if k != "body"}
    server.override("search_statutes", 200, {"results": [row], "creditsConsumed": 4})
    assert make(provider_kwargs).invoke("x")[0].page_content == ROW["excerpt"]
