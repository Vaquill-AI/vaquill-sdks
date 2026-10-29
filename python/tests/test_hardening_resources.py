"""Resource-layer hardening: path segments, webhook secrets, pagination guards, batch helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from vaquill import AsyncVaquill, SpendGuardExceeded, Vaquill, verify_webhook
from vaquill._pagination import CursorStyle, OffsetStyle, SyncPaginator
from vaquill.resources._base import seg

from .conftest import KEY
from .spec import BY_ID, sample

META = {"creditsConsumed": 0, "processingTimeMs": 1.0}


def item(schema: str, **over: Any) -> dict[str, Any]:
    return {**sample({"$ref": f"#/components/schemas/{schema}"}), **over}


def sync_client(handler: Any, **kw: Any) -> Vaquill:
    return Vaquill(
        api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw
    )


def async_client(handler: Any, **kw: Any) -> AsyncVaquill:
    return AsyncVaquill(
        api_key=KEY, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw
    )


# --- seg() ---------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_seg_refuses_segments_that_change_the_endpoint(bad: str) -> None:
    with pytest.raises(ValueError):
        seg(bad)


def test_seg_still_encodes_ordinary_values() -> None:
    assert seg("42 U.S.C. 1983") == "42%20U.S.C.%201983"
    assert seg("a/b") == "a%2Fb"
    assert seg("..x") == "..x"


def test_dot_dot_id_never_reaches_the_wire() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = sync_client(handler)
    for call in (
        lambda: client.statutes.get_section(".."),
        lambda: client.session_laws.get(""),
        lambda: client.session_laws.get_body("."),
    ):
        with pytest.raises(ValueError):
            call()
    assert seen == []


# --- webhooks ------------------------------------------------------------------------------


@pytest.mark.parametrize("secret", ["", "   ", "\n\t", "whsec_", [], [""], ["good-secret", " "]])
def test_verify_webhook_refuses_a_blank_secret(secret: Any) -> None:
    with pytest.raises(ValueError):
        verify_webhook(b"{}", {}, secret)


def test_blank_secret_cannot_verify_a_forged_event() -> None:
    import base64
    import hashlib
    import hmac

    body = b'{"event":"x"}'
    signed = b"id1.1700000000." + body
    forged = base64.b64encode(hmac.new(b"", signed, hashlib.sha256).digest()).decode()
    headers = {
        "webhook-id": "id1",
        "webhook-timestamp": "1700000000",
        "webhook-signature": f"v1,{forged}",
    }
    with pytest.raises(ValueError):
        verify_webhook(body, headers, "", now=1700000000)


def test_a_real_secret_still_verifies() -> None:
    import base64
    import hashlib
    import hmac

    secret = "s3cret-value"  # pragma: allowlist secret
    body = b'{"event":"x"}'
    sig = base64.b64encode(
        hmac.new(secret.encode(), b"id1.1700000000." + body, hashlib.sha256).digest()
    ).decode()
    headers = {
        "webhook-id": "id1",
        "webhook-timestamp": "1700000000",
        "webhook-signature": f"v1,{sig}",
    }
    assert verify_webhook(body, headers, secret, now=1700000000).event == "x"


# --- pagination guards ---------------------------------------------------------------------


def test_max_items_cutting_the_last_page_marks_truncated() -> None:
    pager: SyncPaginator[Any] = SyncPaginator(
        lambda params: {"items": [1, 2, 3], "nextOffset": None},
        style=OffsetStyle(),
        max_items=2,
    )
    assert list(pager) == [1, 2]
    assert pager.truncated is True


def test_exactly_max_items_on_the_last_page_is_not_truncated() -> None:
    pager: SyncPaginator[Any] = SyncPaginator(
        lambda params: {"items": [1, 2], "nextOffset": None}, style=OffsetStyle(), max_items=2
    )
    assert list(pager) == [1, 2]
    assert pager.truncated is False and pager.stuck is False


def test_repeated_offset_stops_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[dict[str, Any]] = []

    def fetch(params: dict[str, Any]) -> dict[str, Any]:
        calls.append(params)
        return {"items": [len(calls)], "nextOffset": 5}

    pager: SyncPaginator[Any] = SyncPaginator(fetch, style=OffsetStyle(), params={"offset": 5})
    with caplog.at_level(logging.WARNING, logger="vaquill"):
        assert list(pager) == [1]
    assert len(calls) == 1
    assert pager.stuck is True
    assert any("Pagination stopped" in r.getMessage() for r in caplog.records)


def test_repeated_cursor_stops() -> None:
    calls = 0

    def fetch(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"items": [calls], "nextCursor": "same"}

    pager: SyncPaginator[Any] = SyncPaginator(fetch, style=CursorStyle())
    assert list(pager) == [
        1,
        2,
    ]  # first call sends no cursor, second sends "same", third is refused
    assert calls == 2 and pager.stuck is True


def test_empty_page_with_has_more_true_stops() -> None:
    calls = 0

    def fetch(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"items": [], "hasMore": True, "nextOffset": calls}

    pager: SyncPaginator[Any] = SyncPaginator(fetch, style=OffsetStyle())
    assert list(pager) == []
    assert calls == 1 and pager.stuck is True


def test_stuck_server_through_a_resource_costs_one_page() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    page = {**base, "results": [item("StatuteResult")], "nextOffset": 0, "creditsConsumed": 4}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page)

    client = sync_client(handler)
    pager = client.statutes.iter_search("x")
    assert len(list(pager)) == 1
    assert len(seen) == 1 and client.credits_spent == 4 and pager.stuck is True


@pytest.mark.anyio
async def test_async_paginator_exposes_stuck_and_truncated() -> None:
    seen: list[httpx.Request] = []
    base = sample(BY_ID["search_statutes"].response or {})
    page = {**base, "results": [item("StatuteResult")] * 2, "nextOffset": 0, "creditsConsumed": 4}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=page)

    client = async_client(handler)
    pager = client.statutes.iter_search("x", max_items=1)
    rows = [r async for r in pager]
    assert len(rows) == 1 and len(seen) == 1
    assert pager.truncated is True and pager.stuck is True


# --- iter_body -----------------------------------------------------------------------------


def body_page(text: str, start: int, end: int, total: int, cursor: str | None) -> dict[str, Any]:
    base = sample(BY_ID["get_session_law_body"].response or {})
    return {
        **base,
        "text": text,
        "pageStart": start,
        "pageEnd": end,
        "totalChars": total,
        "totalPages": 3,
        "nextCursor": cursor,
        "hasMore": cursor is not None,
        "available": True,
        "creditsConsumed": 6,
    }


def test_iter_body_follows_next_cursor_to_the_end() -> None:
    seen: list[httpx.Request] = []
    pages = [
        body_page("aa", 0, 2, 6, "c1"),
        body_page("bb", 2, 4, 6, "c2"),
        body_page("cc", 4, 6, 6, None),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[len(seen) - 1])

    client = sync_client(handler)
    pager = client.session_laws.iter_body("SL1", start_char=0, version=2)
    assert "".join(p.text or "" for p in pager) == "aabbcc"
    assert [r.url.params.get("cursor") for r in seen] == [None, "c1", "c2"]
    assert seen[0].url.params["startChar"] == "0" and "startChar" not in seen[1].url.params
    assert all(r.url.params["version"] == "2" for r in seen)
    assert seen[0].url.path.endswith("/session-laws/SL1/body")
    assert client.credits_spent == 18 and pager.truncated is False and pager.stuck is False


def test_iter_body_stops_when_page_end_reaches_total_chars() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body_page("aa", 0, 2, 2, "c1"))

    client = sync_client(handler)
    assert len(list(client.session_laws.iter_body("SL1"))) == 1
    assert len(seen) == 1


def test_iter_body_max_pages_flags_truncated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        cur = request.url.params.get("cursor")
        n = int(cur[1:]) if cur else 0
        return httpx.Response(200, json=body_page("x", n, n + 1, 99, f"c{n + 1}"))

    client = sync_client(handler)
    pager = client.session_laws.iter_body("SL1", max_pages=2)
    assert len(list(pager)) == 2
    assert pager.truncated is True


@pytest.mark.anyio
async def test_async_iter_body() -> None:
    pages = [body_page("aa", 0, 2, 4, "c1"), body_page("bb", 2, 4, 4, None)]
    n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(200, json=pages[n - 1])

    client = async_client(handler)
    assert "".join([p.text or "" async for p in client.session_laws.iter_body("SL1")]) == "aabb"


# --- batch helpers -------------------------------------------------------------------------


def recorder(
    schema: str,
    response_op: str,
    key: str,
    make: Callable[[str], dict[str, Any]],
    seen: list[httpx.Request],
) -> Any:
    base = sample(BY_ID[response_op].response or {})

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        sent = json.loads(request.content)
        field = next(k for k in ("citations", "actIds", "ids") if k in sent)
        rows = [make(v) for v in sent[field]]
        return httpx.Response(200, json={**base, key: rows, "creditsConsumed": 2 * len(rows)})

    return handler


def test_resolve_batch_all_chunks_at_500() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "StatuteResolveBatchItem",
        "resolve_statute_citations_batch",
        "results",
        lambda c: item("StatuteResolveBatchItem", input=c),
        seen,
    )
    client = sync_client(handler)
    cites = [f"c{i}" for i in range(1203)]
    out = client.statutes.resolve_batch_all(
        cites, state="ca", idempotency_key="key-0123456789abcdef"
    )
    assert len(out) == 1203
    sizes = [len(json.loads(r.content)["citations"]) for r in seen]
    assert sizes == [500, 500, 203]
    assert all(json.loads(r.content)["state"] == "ca" for r in seen)
    assert [r.headers["Idempotency-Key"] for r in seen] == [
        "key-0123456789abcdef",
        "key-0123456789abcdef-1",
        "key-0123456789abcdef-2",
    ]
    assert client.credits_spent == 2 * 1203


def test_batch_all_dedupes_and_skips_empty_input() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "StatuteResult",
        "get_sections_batch",
        "sections",
        lambda a: item("StatuteResult", actId=a),
        seen,
    )
    client = sync_client(handler)
    assert client.statutes.get_sections_all([]) == []
    assert seen == []
    out = client.statutes.get_sections_all(["a", "b", "a"])
    assert [s.act_id for s in out] == ["a", "b"]


def test_get_sections_all_chunks_at_50_and_keeps_order() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "StatuteResult",
        "get_sections_batch",
        "sections",
        lambda a: item("StatuteResult", actId=a),
        seen,
    )
    client = sync_client(handler)
    ids = [f"A{i}" for i in range(120)]
    out = client.statutes.get_sections_all(ids, include_body=True)
    assert [s.act_id for s in out] == ids
    assert [len(json.loads(r.content)["actIds"]) for r in seen] == [50, 50, 20]
    assert all(json.loads(r.content)["includeBody"] is True for r in seen)


def test_get_batch_all_chunks_at_200() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "SessionLawBatchLaw",
        "get_session_laws_batch",
        "laws",
        lambda i: item("SessionLawBatchLaw", sessionLawId=i),
        seen,
    )
    client = sync_client(handler)
    out = client.session_laws.get_batch_all([f"S{i}" for i in range(401)], jurisdiction="mn")
    assert len(out) == 401
    assert [len(json.loads(r.content)["ids"]) for r in seen] == [200, 200, 1]
    assert all(json.loads(r.content)["jurisdiction"] == "mn" for r in seen)


def test_batch_all_honours_the_spend_guard_between_chunks() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "StatuteResult",
        "get_sections_batch",
        "sections",
        lambda a: item("StatuteResult", actId=a),
        seen,
    )
    client = sync_client(handler, max_credits=100)
    with pytest.raises(SpendGuardExceeded):
        client.statutes.get_sections_all([f"A{i}" for i in range(200)])
    assert len(seen) == 1  # the first chunk spent the 100 credits, so the second is refused unsent
    assert client.credits_spent == 100


@pytest.mark.anyio
async def test_async_batch_helpers() -> None:
    seen: list[httpx.Request] = []
    handler = recorder(
        "StatuteResolveBatchItem",
        "resolve_statute_citations_batch",
        "results",
        lambda c: item("StatuteResolveBatchItem", input=c),
        seen,
    )
    client = async_client(handler)
    out = await client.statutes.resolve_batch_all([f"c{i}" for i in range(501)])
    assert len(out) == 501 and len(seen) == 2

    seen.clear()
    handler = recorder(
        "SessionLawBatchLaw",
        "get_session_laws_batch",
        "laws",
        lambda i: item("SessionLawBatchLaw", sessionLawId=i),
        seen,
    )
    client = async_client(handler)
    assert len(await client.session_laws.get_batch_all([f"S{i}" for i in range(201)])) == 201

    seen.clear()
    handler = recorder(
        "StatuteResult",
        "get_sections_batch",
        "sections",
        lambda a: item("StatuteResult", actId=a),
        seen,
    )
    client = async_client(handler)
    assert len(await client.statutes.get_sections_all([f"A{i}" for i in range(51)])) == 51


def test_extract_citations_docstring_states_the_free_mode() -> None:
    from vaquill.resources.statutes import SyncStatutes

    assert "0 credits" in (SyncStatutes.extract_citations.__doc__ or "")
