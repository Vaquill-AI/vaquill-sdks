"""Auto-pagination helpers on the resources: request chaining, guards, credit counting."""

from __future__ import annotations

import json
from typing import Any

import httpx

from vaquill import AsyncVaquill, Vaquill

from .conftest import KEY
from .spec import BY_ID, resolve, sample


def item(schema: str, **over: Any) -> dict[str, Any]:
    return {**sample({"$ref": f"#/components/schemas/{schema}"}), **over}


def page_server(pages: list[dict[str, Any]], seen: list[httpx.Request]) -> Any:
    queue = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=queue.pop(0))

    return handler


def sync_client(handler: Any) -> Vaquill:
    return Vaquill(api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_iter_search_chains_offsets_and_counts_credits() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    pages = [
        {
            **base,
            "results": [item("StatuteResult", actId="a1")],
            "nextOffset": 1,
            "creditsConsumed": 4,
        },
        {
            **base,
            "results": [item("StatuteResult", actId="a2")],
            "nextOffset": None,
            "creditsConsumed": 4,
        },
    ]
    client = sync_client(page_server(pages, seen))
    rows = list(client.statutes.iter_search("negligence", state="ca", limit=1))
    assert [r.act_id for r in rows] == ["a1", "a2"]
    bodies = [json.loads(r.content) for r in seen]
    assert [b["offset"] for b in bodies] == [0, 1]
    assert (
        bodies[0]["state"] == "ca"
        and bodies[0]["limit"] == 1
        and bodies[0]["query"] == "negligence"
    )
    assert all("Idempotency-Key" in r.headers for r in seen)
    assert client.credits_spent == 8


def test_max_pages_stops_a_charged_iteration_and_flags_truncation() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    page = {**base, "results": [item("StatuteResult")], "nextOffset": 5, "creditsConsumed": 4}
    client = sync_client(page_server([page, page, page], seen))
    pager = client.statutes.iter_search("x", max_pages=2)
    assert len(list(pager)) == 2
    assert len(seen) == 2
    assert pager.truncated is True


def test_section_changes_walk_back_with_before_id_and_forward_with_since_id() -> None:
    for order, param in (("desc", "beforeId"), ("asc", "sinceId")):
        seen: list[httpx.Request] = []
        base = sample(BY_ID["get_section_changes"].response or {})
        pages = [
            {
                **base,
                "changes": [item("StatuteChangeEvent", id=9), item("StatuteChangeEvent", id=7)],
                "hasMore": True,
            },
            {**base, "changes": [item("StatuteChangeEvent", id=5)], "hasMore": False},
        ]
        client = sync_client(page_server(pages, seen))
        ids = [c.id for c in client.statutes.iter_section_changes("A1", limit=2, order=order)]
        assert ids == [9, 7, 5]
        assert seen[1].url.params[param] == "7"
        assert len(seen) == 2


def test_divisions_follow_next_cursor_and_session_laws_changes_follow_since_id() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["list_statute_divisions"].response or {})
    pages = [
        {**base, "divisions": [item("UsDivisionNode")], "nextCursor": "c2"},
        {**base, "divisions": [item("UsDivisionNode")], "nextCursor": None},
    ]
    client = sync_client(page_server(pages, seen))
    assert len(list(client.statutes.iter_divisions("STATE", state="wa", title_number=1))) == 2
    assert seen[1].url.params["cursor"] == "c2" and seen[1].url.params["titleNumber"] == "1"

    seen = []
    base = sample(BY_ID["get_session_law_changes"].response or {})
    pages: list[dict[str, Any]] = [
        {**base, "changes": [item("SessionLawChange", id=3)], "hasMore": True},
        {**base, "changes": [], "hasMore": False},
    ]
    client = sync_client(page_server(pages, seen))
    assert [c.id for c in client.session_laws.iter_changes(since_id=2, limit=1)] == [3]
    assert seen[0].url.params["sinceId"] == "2"
    assert seen[1].url.params["sinceId"] == "3"


def test_free_listings_unwrap_the_data_envelope() -> None:
    seen: list[httpx.Request] = []
    meta = {"creditsConsumed": 0, "processingTimeMs": 1.0}
    boards = [
        {"data": {"boards": [item("BoardResponse")], "total": 2, "hasMore": True}, "meta": meta},
        {"data": {"boards": [item("BoardResponse")], "total": 2, "hasMore": False}, "meta": meta},
    ]
    client = sync_client(page_server(boards, seen))
    assert len(list(client.boards.iter_list(limit=1))) == 2
    assert [r.url.params["offset"] for r in seen] == ["0", "1"]
    assert all("Idempotency-Key" not in r.headers for r in seen)

    seen = []
    changes = [
        {
            "data": {"changes": [item("ChangeResponse", id=8), item("ChangeResponse", id=6)]},
            "meta": meta,
        },
        {"data": {"changes": [item("ChangeResponse", id=4)]}, "meta": meta},
    ]
    client = sync_client(page_server(changes, seen))
    assert [c.id for c in client.watches.iter_changes("w1", limit=2)] == [8, 6, 4]
    assert seen[1].url.params["beforeId"] == "6"
    assert client.credits_spent == 0


async def test_async_iter_search_and_pages() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    pages = [
        {**base, "results": [item("StatuteResult", actId="a1")], "nextOffset": 1},
        {**base, "results": [item("StatuteResult", actId="a2")], "nextOffset": None},
    ]
    client = AsyncVaquill(
        api_key=KEY,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(page_server(pages, seen))),
    )
    got = [r.act_id async for r in client.statutes.iter_search("x")]
    assert got == ["a1", "a2"]


def test_the_schema_helper_resolves_refs() -> None:
    assert resolve({"$ref": "#/components/schemas/StatuteResult"})["type"] == "object"


def test_iter_search_follows_has_more_when_next_offset_is_null() -> None:
    """Live bug: hybrid search answers ``hasMore: true`` with ``nextOffset: null``."""
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    pages = [
        {
            **base,
            "results": [item("StatuteResult", actId=f"a{i}") for i in (1, 2)],
            "hasMore": True,
            "nextOffset": None,
            "creditsConsumed": 4,
        },
        {
            **base,
            "results": [item("StatuteResult", actId="a3")],
            "hasMore": False,
            "nextOffset": None,
            "creditsConsumed": 4,
        },
    ]
    client = sync_client(page_server(pages, seen))
    got = [hit.act_id for hit in client.statutes.iter_search("negligence", limit=2)]
    assert got == ["a1", "a2", "a3"]
    assert [json.loads(r.content)["offset"] for r in seen] == [0, 2]
    assert client.credits_spent == 8


async def test_async_iter_search_follows_has_more_when_next_offset_is_null() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    pages = [
        {
            **base,
            "results": [item("StatuteResult", actId="a1")],
            "hasMore": True,
            "nextOffset": None,
        },
        {**base, "results": [item("StatuteResult", actId="a2")], "hasMore": False},
    ]
    http = httpx.AsyncClient(transport=httpx.MockTransport(page_server(pages, seen)))
    client = AsyncVaquill(api_key=KEY, http_client=http)
    got = [hit.act_id async for hit in client.statutes.iter_search("negligence", limit=1)]
    assert got == ["a1", "a2"]
    assert [json.loads(r.content)["offset"] for r in seen] == [0, 1]
