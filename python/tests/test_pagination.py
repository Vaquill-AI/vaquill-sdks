from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from vaquill import AsyncPaginator, CursorStyle, IdWindowStyle, OffsetStyle, SyncPaginator

PAGES = {
    "offset": [
        (None, {"items": [1, 2], "nextOffset": 2}),
        (2, {"items": [3, 4], "nextOffset": 4}),
        (4, {"items": [5], "nextOffset": None}),
    ],
}


def offset_fetch(calls: list[dict[str, Any]]):
    def fetch(params: dict[str, Any]) -> Mapping[str, Any]:
        calls.append(params)
        for start, body in PAGES["offset"]:
            if params.get("offset") == start:
                return body
        raise AssertionError(params)

    return fetch


def test_offset_style_walks_all_pages() -> None:
    calls: list[dict[str, Any]] = []
    pager = SyncPaginator[int](offset_fetch(calls), style=OffsetStyle(), params={"limit": 2})
    assert list(pager) == [1, 2, 3, 4, 5]
    assert calls == [{"limit": 2}, {"limit": 2, "offset": 2}, {"limit": 2, "offset": 4}]
    assert not pager.truncated


def test_max_pages_guard() -> None:
    calls: list[dict[str, Any]] = []
    pager = SyncPaginator[int](offset_fetch(calls), style=OffsetStyle(), max_pages=2)
    assert list(pager) == [1, 2, 3, 4] and len(calls) == 2 and pager.truncated


def test_max_items_guard_trims_and_stops_fetching() -> None:
    calls: list[dict[str, Any]] = []
    pager = SyncPaginator[int](offset_fetch(calls), style=OffsetStyle(), max_items=3)
    assert list(pager) == [1, 2, 3] and len(calls) == 2 and pager.truncated


def test_guard_not_truncated_when_data_ends_exactly() -> None:
    body = {"items": [1, 2], "nextOffset": None}
    pager = SyncPaginator[int](lambda p: body, style=OffsetStyle(), max_pages=1)
    assert list(pager) == [1, 2] and not pager.truncated


def test_manual_page_access() -> None:
    pages = list(SyncPaginator[int](offset_fetch([]), style=OffsetStyle()).pages())
    assert pages == [[1, 2], [3, 4], [5]]


def test_cursor_style_and_parse() -> None:
    bodies = {None: {"results": ["a"], "nextCursor": "c1"}, "c1": {"results": ["b"]}}
    pager = SyncPaginator[str](
        lambda p: bodies[p.get("cursor")],
        style=CursorStyle(),
        items_key="results",
        parse=str.upper,
    )
    assert list(pager) == ["A", "B"]


def test_id_window_before_id() -> None:
    data = [{"id": i} for i in range(10, 0, -1)]
    calls: list[dict[str, Any]] = []

    def fetch(params: dict[str, Any]) -> Mapping[str, Any]:
        calls.append(params)
        before = params.get("beforeId")
        rows = [r for r in data if before is None or r["id"] < before]
        return {"items": rows[: params["limit"]]}

    items = list(SyncPaginator[dict[str, int]](fetch, style=IdWindowStyle(), params={"limit": 4}))
    assert [r["id"] for r in items] == list(range(10, 0, -1))
    assert [c.get("beforeId") for c in calls] == [None, 7, 3]  # short last page stops


def test_id_window_since_id_stops_on_empty() -> None:
    pages: list[dict[str, Any]] = [{"items": [{"id": "a"}, {"id": "b"}]}, {"items": []}]
    seen: list[dict[str, Any]] = []

    def fetch(params: dict[str, Any]) -> Mapping[str, Any]:
        seen.append(params)
        return pages[len(seen) - 1]

    pager = SyncPaginator[dict[str, str]](fetch, style=IdWindowStyle(param="sinceId"))
    assert len(list(pager)) == 2 and seen[1] == {"sinceId": "b"}


async def test_async_paginator() -> None:
    sync_calls: list[dict[str, Any]] = []
    inner = offset_fetch(sync_calls)

    async def fetch(params: dict[str, Any]) -> Mapping[str, Any]:
        return inner(params)

    pager = AsyncPaginator[int](fetch, style=OffsetStyle(), max_items=4)
    assert [i async for i in pager] == [1, 2, 3, 4] and pager.truncated
    pages = [p async for p in AsyncPaginator[int](fetch, style=OffsetStyle()).pages()]
    assert pages == [[1, 2], [3, 4], [5]]
