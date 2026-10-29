"""Shared state, pacing and measurement for the live tests. Never stores the API key."""

# pyright: basic
from __future__ import annotations

import asyncio
import collections
import enum
import inspect
import json
import os
import statistics
import threading
import time
import types
import typing
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel

from vaquill import AsyncVaquill, Vaquill

# The server enforces 30 calls per fixed minute and 1000 per day per key. Stay under 26.
WINDOW = 26
_lock = threading.Lock()
_sent: collections.deque[float] = collections.deque()


class State:
    def __init__(self) -> None:
        self.client: Vaquill
        self.balance = 0.0
        self.balance0 = 0.0
        self.http_calls = 0
        self.last_send = 0.0
        self.ops: dict[str, dict[str, Any]] = {}
        self.extras: set[str] = set()
        self.enum_drift: set[str] = set()
        self.models_parsed = 0
        self.headers_seen: collections.Counter[str] = collections.Counter()
        self.statuses: collections.Counter[int] = collections.Counter()
        self.notes: dict[str, Any] = {}
        self.ids: dict[str, Any] = {}


S = State()


def wait_for_slot(pace: bool = True) -> None:
    with _lock:
        while pace:
            now = time.monotonic()
            while _sent and now - _sent[0] > 60:
                _sent.popleft()
            if len(_sent) < WINDOW:
                break
            time.sleep(max(60 - (now - _sent[0]) + 0.2, 0.2))
        _sent.append(time.monotonic())
        S.http_calls += 1
        S.last_send = time.perf_counter()


def _record(response: httpx.Response) -> None:
    S.statuses[response.status_code] += 1
    for name in response.headers:
        S.headers_seen[name.lower()] += 1


def sync_http(pace: bool = True) -> httpx.Client:
    return httpx.Client(
        event_hooks={
            "request": [lambda request: wait_for_slot(pace)],
            "response": [_record],
        }
    )


def async_http(pace: bool = True) -> httpx.AsyncClient:
    async def req(request: httpx.Request) -> None:
        wait_for_slot(pace)

    async def resp(response: httpx.Response) -> None:
        _record(response)

    return httpx.AsyncClient(event_hooks={"request": [req], "response": [resp]})


def dump(obj: Any) -> Any:
    return obj.model_dump(by_alias=True, mode="json") if isinstance(obj, BaseModel) else obj


def find_all(obj: Any, key: str) -> list[Any]:
    """Every value stored under ``key`` anywhere in a JSON-like structure."""
    found: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found.extend(find_all(v, key))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(find_all(v, key))
    return found


def _enum_in(ann: Any) -> bool:
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return True
    return any(_enum_in(a) for a in typing.get_args(ann))


def walk(obj: Any) -> None:
    """Record extra (undeclared) fields and enum values outside the generated enum."""
    if isinstance(obj, BaseModel):
        name = type(obj).__name__
        for key in obj.model_extra or {}:
            S.extras.add(f"{name}.{key}")
        for field, info in type(obj).model_fields.items():
            value = obj.__dict__.get(field)
            if _enum_in(info.annotation):
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if isinstance(item, str) and not isinstance(item, enum.Enum):
                        S.enum_drift.add(f"{name}.{field}={item!r}")
            walk(value)
    elif isinstance(obj, list):
        for item in obj:
            walk(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            walk(item)


def read_balance() -> float:
    return float(S.client.credits.balance().credits_remaining)


async def _acall(call: Callable[[Any], Any]) -> tuple[Any, float]:
    http = async_http()
    try:
        async with AsyncVaquill(http_client=http) as ac:
            result = await call(ac)
            return result, ac.credits_spent
    finally:
        await http.aclose()


def run_op(name: str, call: Callable[[Any], Any], *, charged: bool = True) -> Any:
    """Run ``call`` on the sync client then the async client, measuring each in isolation.

    ``call`` receives a client and returns a result (sync) or an awaitable (async).
    """
    rec: dict[str, Any] = {"charged": charged}
    S.ops[name] = rec
    first: Any = None
    for kind in ("sync", "async"):
        out: dict[str, Any] = {}
        rec[kind] = out
        before = S.balance
        spent0 = S.client.credits_spent
        started = time.perf_counter()
        try:
            if kind == "sync":
                result = call(S.client)
                spent = S.client.credits_spent - spent0
            else:

                async def go() -> tuple[Any, float]:
                    return await _acall(lambda ac: _await(call(ac)))

                result, spent = asyncio.run(go())
            out["latency_ms"] = round((time.perf_counter() - S.last_send) * 1000, 1)
            out["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
            out["ok"] = True
        except Exception as exc:
            out["ok"] = False
            out["error"] = f"{type(exc).__name__}: {exc}"[:400]
            result, spent = None, 0.0
        if isinstance(result, BaseModel):
            S.models_parsed += 1
            walk(result)
            out["credits_consumed"] = getattr(result, "credits_consumed", None)
        elif isinstance(result, list):
            for item in result:
                walk(item)
            S.models_parsed += 1
        out["sdk_spent"] = spent
        after = read_balance()
        out["balance_delta"] = round(before - after, 6)
        expected = out.get("credits_consumed")
        if expected is None:
            expected = spent
        out["reconciled"] = abs(out["balance_delta"] - expected) < 1e-6
        if not out["reconciled"]:
            time.sleep(3)
            later = read_balance()
            out["balance_delta_after_3s"] = round(before - later, 6)
            after = later
        S.balance = after
        if kind == "sync":
            first = result
    return first


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def p50(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def scrub(text: str) -> str:
    key = os.environ.get("VAQUILL_API_KEY", "")
    return text.replace(key, "<redacted>") if key else text


def write_report() -> None:
    path = os.environ.get("VAQUILL_LIVE_REPORT")
    if not path:
        return
    payload = {
        "ops": S.ops,
        "extras": sorted(S.extras),
        "enum_drift": sorted(S.enum_drift),
        "models_parsed": S.models_parsed,
        "headers_seen": dict(S.headers_seen),
        "statuses": dict(S.statuses),
        "notes": S.notes,
        "http_calls": S.http_calls,
        "balance_start": S.balance0,
        "balance_end": S.balance,
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(scrub(json.dumps(payload, indent=1, default=str)))


_ = types
