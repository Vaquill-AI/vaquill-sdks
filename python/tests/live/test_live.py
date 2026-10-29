"""Live production run. Opt-in: ``VAQUILL_LIVE=1 .venv/bin/python -m pytest tests/live -q``.

Set ``VAQUILL_LIVE_REPORT=/path/report.json`` to keep the measurements.
Spends credits (about 400 for a full run). Order matters: later tests reuse ids found earlier.
"""

# pyright: basic
from __future__ import annotations

import asyncio
import random
import string
import time
from typing import Any

import httpx
import pytest

import vaquill
from tests.live.harness import (
    S,
    async_http,
    dump,
    find_all,
    read_balance,
    run_op,
    sync_http,
    wait_for_slot,
    write_report,
)
from vaquill import AsyncVaquill, Vaquill

pytestmark = pytest.mark.live

ANCHOR = "USC_T17_C1_S107"
ANCHOR_CITE = "17 U.S.C. 107"
TEXT = (
    "Plaintiff sued under 42 U.S.C. 1983(b). The court applied 17 U.S.C. 107, and 42 U.S.C. 1983."
)


def _ok(*names: str) -> None:
    bad = {
        f"{n}/{k}": S.ops[n][k].get("error")
        for n in names
        for k in ("sync", "async")
        if n in S.ops and not S.ops[n][k]["ok"]
    }
    assert not bad, bad


async def _alist(pager: Any) -> list[Any]:
    return [x async for x in pager]


def _is_async(c: Any) -> bool:
    return isinstance(c, AsyncVaquill)


def test_00_baseline() -> None:
    S.client = Vaquill(http_client=sync_http())
    S.balance0 = S.balance = read_balance()
    run_op("credits.balance", lambda c: c.credits.balance(), charged=False)
    run_op("pricing.get", lambda c: c.pricing.get(), charged=False)
    run_op("statutes.coverage", lambda c: c.statutes.coverage(), charged=False)
    run_op("boards.list", lambda c: c.boards.list(), charged=False)
    run_op("watches.list", lambda c: c.watches.list(), charged=False)
    _ok("credits.balance", "pricing.get", "statutes.coverage", "boards.list", "watches.list")


def test_10_search_and_resolve() -> None:
    q = "statute of limitations for medical malpractice"
    p1 = run_op("statutes.search", lambda c: c.statutes.search(q, state="ca", limit=5))
    p2 = run_op(
        "statutes.search (offset 5)", lambda c: c.statutes.search(q, state="ca", limit=5, offset=5)
    )
    if p1 and p2:
        a = {h.act_id for h in p1.results}
        b = {h.act_id for h in p2.results}
        S.notes["search_pages_overlap"] = sorted(a & b)
        S.notes["search_page_sizes"] = [len(p1.results), len(p2.results)]
        S.ids["ca"] = p1.results[0].act_id if p1.results else None
        S.notes["search_next_offset"] = dump(p1).get("nextOffset")

    def it(c: Any) -> Any:
        pager = c.statutes.iter_search(q, state="ca", limit=3, max_pages=2)
        return _alist(pager) if _is_async(c) else list(pager)

    items = run_op("statutes.iter_search (2 pages)", it)
    S.notes["iter_search_items"] = len(items) if items else None
    assert items is not None and len(items) > 3, "iter_search must follow hasMore past page 1"
    mn = run_op(
        "statutes.search (mn)", lambda c: c.statutes.search("appropriation", state="mn", limit=3)
    )
    if mn and mn.results:
        S.ids["mn"] = mn.results[0].act_id
    res = run_op("statutes.resolve", lambda c: c.statutes.resolve(ANCHOR_CITE))
    if res:
        S.notes["resolve"] = {
            "resolved": res.resolved,
            "act": dump(res).get("section", {}).get("actId"),
        }
    batch = run_op(
        "statutes.resolve_batch",
        lambda c: c.statutes.resolve_batch([ANCHOR_CITE, "42 U.S.C. 1983", "999 U.S.C. 99999"]),
    )
    if batch:
        S.notes["resolve_batch_keys"] = sorted(dump(batch).keys())
    _ok(
        "statutes.search",
        "statutes.search (offset 5)",
        "statutes.iter_search (2 pages)",
        "statutes.search (mn)",
        "statutes.resolve",
        "statutes.resolve_batch",
    )


def test_20_sections() -> None:
    run_op("statutes.get_section", lambda c: c.statutes.get_section(ANCHOR))
    body = run_op("statutes.get_section_body", lambda c: c.statutes.get_section_body(ANCHOR))
    if body:
        S.notes["body_plain_len"] = len(body.plain or "")
    run_op("statutes.neighbors", lambda c: c.statutes.neighbors(ANCHOR, limit=3))
    run_op(
        "statutes.get_sections_batch",
        lambda c: c.statutes.get_sections_batch([ANCHOR, "USC_T42_C21_S1983"]),
    )
    run_op("statutes.count", lambda c: c.statutes.count(state="ca"))
    first = run_op("statutes.divisions", lambda c: c.statutes.divisions("USC"))
    cursor = dump(first).get("nextCursor") if first else None
    S.notes["divisions_next_cursor"] = bool(cursor)
    if cursor:
        run_op(
            "statutes.divisions (cursor page 2)",
            lambda c: c.statutes.divisions("USC", cursor=cursor),
        )

    def it(c: Any) -> Any:
        pager = c.statutes.iter_divisions("USC", max_pages=2)
        return _alist(pager) if _is_async(c) else list(pager)

    run_op("statutes.iter_divisions (2 pages)", it)
    run_op("statutes.section_changes", lambda c: c.statutes.section_changes(ANCHOR, limit=5))

    def itc(c: Any) -> Any:
        pager = c.statutes.iter_section_changes(ANCHOR, limit=2, max_pages=2)
        return _alist(pager) if _is_async(c) else list(pager)

    run_op("statutes.iter_section_changes (2 pages)", itc)
    run_op("statutes.cited_by", lambda c: c.statutes.cited_by(ANCHOR, limit=5))
    run_op("statutes.definitions", lambda c: c.statutes.definitions(ANCHOR))
    run_op("statutes.extract_citations", lambda c: c.statutes.extract_citations(TEXT))
    mn = S.ids.get("mn") or ANCHOR
    ca = S.ids.get("ca") or ANCHOR
    run_op("statutes.enactments", lambda c: c.statutes.enactments(mn))
    run_op("statutes.cross_state", lambda c: c.statutes.cross_state(ca, limit=5))
    _ok(
        *[
            n
            for n in S.ops
            if n.startswith("statutes.")
            and n
            not in {
                "statutes.coverage",
                "statutes.search",
                "statutes.search (offset 5)",
                "statutes.iter_search (2 pages)",
                "statutes.search (mn)",
                "statutes.resolve",
                "statutes.resolve_batch",
            }
        ]
    )


def test_30_session_laws() -> None:
    lst = run_op("session_laws.list", lambda c: c.session_laws.list("mn", limit=5))
    ids = [str(x) for x in find_all(dump(lst), "sessionLawId")] if lst else []
    ids = list(dict.fromkeys(ids))
    S.ids["sl"] = ids
    S.notes["session_law_ids"] = ids[:5]
    cursor = dump(lst).get("nextCursor") if lst else None

    def it(c: Any) -> Any:
        pager = c.session_laws.iter_list("mn", limit=2, max_pages=2)
        return _alist(pager) if _is_async(c) else list(pager)

    run_op("session_laws.iter_list (2 pages)", it)
    s1 = run_op(
        "session_laws.search",
        lambda c: c.session_laws.search("appropriations", jurisdiction="mn", limit=3),
    )
    run_op(
        "session_laws.search (offset 3)",
        lambda c: c.session_laws.search("appropriations", jurisdiction="mn", limit=3, offset=3),
    )
    if s1:
        S.notes["sl_search_keys"] = sorted(dump(s1).keys())
    if not ids:
        pytest.skip("no session law ids returned by list")
    sid = ids[0]
    run_op("session_laws.get", lambda c: c.session_laws.get(sid))
    body = run_op("session_laws.get_body", lambda c: c.session_laws.get_body(sid))
    if body:
        S.notes["sl_body_keys"] = sorted(dump(body).keys())
    run_op("session_laws.versions", lambda c: c.session_laws.versions(sid))
    run_op("session_laws.get_batch", lambda c: c.session_laws.get_batch(ids[:2]))
    run_op(
        "session_laws.changes",
        lambda c: c.session_laws.changes(since_id=0, jurisdiction="mn", limit=3),
    )

    def itc(c: Any) -> Any:
        pager = c.session_laws.iter_changes(jurisdiction="mn", limit=2, max_pages=2)
        return _alist(pager) if _is_async(c) else list(pager)

    run_op("session_laws.iter_changes (2 pages)", itc)
    S.notes["sl_list_cursor"] = bool(cursor)
    _ok(*[n for n in S.ops if n.startswith("session_laws.")])


def _balance_around(fn: Any) -> tuple[Any, float]:
    before = read_balance()
    try:
        out = fn()
    except Exception as exc:
        out = exc
    time.sleep(1)
    after = read_balance()
    S.balance = after
    return out, round(before - after, 6)


def test_40_errors() -> None:
    bad_key = "vq_key_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=32)
    )  # pragma: allowlist secret
    http = sync_http()
    bad = Vaquill(api_key=bad_key, http_client=http)
    exc, _ = _balance_around(lambda: bad.credits.balance())
    assert isinstance(exc, vaquill.AuthenticationError), repr(exc)
    S.notes["bad_key"] = {
        "status": exc.status_code,
        "code": exc.code,
        "request_id": bool(exc.request_id),
        "body": exc.body,
        "str": str(exc),
    }
    http.close()

    exc, delta = _balance_around(lambda: S.client.statutes.get_section("USC_T99_C99_S99999"))
    assert isinstance(exc, vaquill.NotFoundError), repr(exc)
    S.notes["not_found"] = {
        "status": exc.status_code,
        "code": exc.code,
        "body": exc.body,
        "str": str(exc),
        "charged": delta,
    }

    exc, delta = _balance_around(lambda: S.client.statutes.get_section("usc_t17_c1_s107"))
    S.notes["not_found_wrong_case"] = {
        "type": type(exc).__name__,
        "body": getattr(exc, "body", None),
        "charged": delta,
    }

    exc, delta = _balance_around(lambda: S.client.statutes.search("negligence", limit=9999))
    S.notes["validation_limit"] = {
        "type": type(exc).__name__,
        "status": getattr(exc, "status_code", None),
        "errors": getattr(exc, "errors", None),
        "body": getattr(exc, "body", None),
        "str": str(exc),
        "charged": delta,
    }
    exc2, delta2 = _balance_around(lambda: S.client.statutes.divisions("NOT_A_CORPUS"))
    S.notes["validation_corpus"] = {
        "type": type(exc2).__name__,
        "body": getattr(exc2, "body", None),
        "charged": delta2,
    }
    assert isinstance(exc, vaquill.UnprocessableEntityError), repr(exc)

    async def abad() -> Any:
        h = async_http()
        try:
            async with AsyncVaquill(api_key=bad_key, http_client=h) as ac:
                await ac.credits.balance()
        except Exception as e:
            return e
        finally:
            await h.aclose()

    aexc = asyncio.run(abad())
    assert isinstance(aexc, vaquill.AuthenticationError), repr(aexc)


def test_50_idempotency_replay() -> None:
    key = "sdk-live-test-" + "".join(random.choices(string.ascii_lowercase, k=12))
    outs = []
    for i in range(2):
        before = read_balance()
        raw = S.client.with_raw_response.request(
            "POST",
            "/api/v1/us/statutes/count",
            cast_to=dict,
            json={"state": "ca"},
            charged=True,
            idempotency_key=key,
        )
        after = read_balance()
        outs.append(
            {
                "call": i + 1,
                "balance_delta": round(before - after, 6),
                "credits_consumed": raw.credits_consumed,
                "replayed_header": raw.headers.get("idempotent-replayed"),
                "idempotency_headers": {
                    k: v for k, v in raw.headers.items() if "idempot" in k.lower()
                },
                "sdk_charged_this_call": raw.credits_charged_this_call,
            }
        )
        S.balance = after
    S.notes["idempotency_replay"] = outs


def test_60_raw_headers() -> None:
    raw = S.client.with_raw_response.request("GET", "/api/v1/credits/balance", cast_to=dict)
    rl = raw.rate_limit
    S.notes["raw_free"] = {
        "request_id": raw.request_id,
        "headers": sorted(h.lower() for h in raw.headers),
        "rate_limit": rl.__dict__,
    }
    raw2 = S.client.with_raw_response.request(
        "POST", "/api/v1/us/statutes/count", cast_to=dict, json={"state": "ca"}, charged=True
    )
    S.balance = read_balance()
    S.notes["raw_charged"] = {
        "request_id": raw2.request_id,
        "headers": sorted(h.lower() for h in raw2.headers),
        "rate_limit": raw2.rate_limit.__dict__,
        "credits": raw2.credits_consumed,
        "idempotent_replayed": raw2.idempotent_replayed,
        "x_request_id_in_body": "requestId" in (raw2.json() or {}),
    }
    assert raw.request_id and raw2.request_id


def test_70_spend_guard_and_retries() -> None:
    http = sync_http()
    guard = Vaquill(http_client=http, max_credits=1)
    calls0 = S.http_calls
    guard.statutes.count(state="ca")
    S.balance = read_balance()
    calls1 = S.http_calls
    with pytest.raises(vaquill.SpendGuardExceeded):
        guard.statutes.count(state="ca")
    S.notes["spend_guard"] = {
        "spent": guard.credits_spent,
        "http_calls_for_blocked_call": S.http_calls - calls1,
        "calls_first": calls1 - calls0 - 0,
    }
    zero = Vaquill(http_client=http, max_credits=0)
    c2 = S.http_calls
    with pytest.raises(vaquill.SpendGuardExceeded):
        zero.statutes.count(state="ca")
    assert S.http_calls == c2
    http.close()

    attempts = {"n": 0}

    def count(request: httpx.Request) -> None:
        attempts["n"] += 1

    dead = httpx.Client(event_hooks={"request": [count]}, timeout=2)
    c = Vaquill(base_url="http://127.0.0.1:9", http_client=dead, max_retries=2)
    t = time.perf_counter()
    with pytest.raises(vaquill.APIConnectionError):
        c.credits.balance()
    S.notes["retry_free"] = {
        "attempts": attempts["n"],
        "seconds": round(time.perf_counter() - t, 2),
    }
    attempts["n"] = 0
    with pytest.raises(vaquill.APIConnectionError):
        c.statutes.count(state="ca")
    S.notes["retry_charged"] = {"attempts": attempts["n"]}

    async def adead() -> int:
        n = {"v": 0}

        async def acount(request: httpx.Request) -> None:
            n["v"] += 1

        h = httpx.AsyncClient(event_hooks={"request": [acount]}, timeout=2)
        try:
            async with AsyncVaquill(
                base_url="http://127.0.0.1:9", http_client=h, max_retries=2
            ) as ac:
                with pytest.raises(vaquill.APIConnectionError):
                    await ac.credits.balance()
        finally:
            await h.aclose()
        return n["v"]

    S.notes["retry_async_attempts"] = asyncio.run(adead())


def test_80_watches_create() -> None:
    exc, _ = _balance_around(lambda: S.client.watches.create("state", state="wa"))
    if isinstance(exc, Exception):
        S.notes["watch_create_no_channel"] = {
            "type": type(exc).__name__,
            "status": getattr(exc, "status_code", None),
            "body": getattr(exc, "body", None),
        }
        return
    wid = dump(exc)
    S.notes["watch_create_no_channel"] = {"created": True, "keys": sorted(wid.keys())}
    ids = find_all(wid, "watchId") or find_all(wid, "id")
    for i in ids:
        S.client.watches.delete(str(i))
        S.notes["watch_deleted"] = str(i)


def test_90_rate_limit_burst_and_report() -> None:
    time.sleep(61)
    http = sync_http(pace=False)
    c = Vaquill(http_client=http)
    remaining: list[Any] = []
    codes: list[int] = []
    for _ in range(10):
        raw = c.with_raw_response.request(
            "GET", "/api/v1/credits/balance", cast_to=dict, max_retries=0
        )
        remaining.append(raw.rate_limit.remaining)
        codes.append(raw.status_code)
    S.notes["burst"] = {"codes": codes, "remaining": remaining}
    http.close()
    time.sleep(61)
    wait_for_slot()
    S.balance = read_balance()
    write_report()
