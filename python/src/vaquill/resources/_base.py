"""Pieces shared by every resource: request options, path and body helpers, paging styles."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic.alias_generators import to_camel

from .._base_client import AsyncAPIClient, SyncAPIClient
from .._pagination import IdWindowStyle


class RequestOptions(TypedDict, total=False):
    """Per-call options accepted by every resource method as extra keyword arguments."""

    timeout: float | httpx.Timeout
    max_retries: int
    idempotency_key: str
    headers: Mapping[str, str]


def seg(value: str) -> str:
    """Percent-encode one path segment (a citation may be passed where an id goes).

    Raises ``ValueError`` for an empty segment (it would produce ``//``) and for ``.`` or
    ``..``, which a URL parser resolves away and so would silently call another endpoint.
    """
    if value in ("", ".", ".."):
        raise ValueError(f"Invalid path segment {value!r}: it must not be empty, '.' or '..'.")
    return quote(value, safe="")


_T = TypeVar("_T")


def chunked(items: Sequence[_T], size: int) -> Iterator[list[_T]]:
    """Consecutive slices of at most ``size`` items."""
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def unique(items: Sequence[str]) -> list[str]:
    """The items without exact repeats, first occurrence kept, order preserved."""
    return list(dict.fromkeys(items))


def chunk_options(options: RequestOptions, index: int) -> RequestOptions:
    """Per-chunk request options: a caller's idempotency key is suffixed for chunks after the first.

    Every chunk has a different body, so reusing one key would be rejected as a key reuse.
    """
    out = cast(RequestOptions, dict(options))
    key = options.get("idempotency_key")
    if key is not None and index > 0:
        suffix = f"-{index}"
        out["idempotency_key"] = key[: 255 - len(suffix)] + suffix  # the server caps a key at 255
    return out


def compact(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unset (None) members so the server default applies."""
    return {k: v for k, v in fields.items() if v is not None}


def wire(fields: Mapping[str, Any]) -> dict[str, Any]:
    """snake_case keyword arguments to camelCase wire names, unset members dropped."""
    return {to_camel(k): v for k, v in fields.items() if v is not None}


@dataclass(frozen=True)
class HasMoreOffset:
    """Offset paging for responses with ``hasMore`` but no ``nextOffset``."""

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        more = body.get("hasMore")
        if more is None:  # no flag: a full page means there may be another
            more = len(items) >= int(params.get("limit") or 0) > 0
        if not more or not items:
            return None
        return {**params, "offset": int(params.get("offset") or 0) + len(items)}


@dataclass(frozen=True)
class NextOffsetOrHasMore:
    """Offset paging for ``search_statutes``.

    The spec documents ``nextOffset`` as present only with ``matchType: "boolean"``. A hybrid
    search answers ``hasMore: true`` with ``nextOffset: null``, so follow ``nextOffset`` when
    the server gives one and otherwise step by the rows returned while ``hasMore`` is true.
    """

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        nxt = body.get("nextOffset")
        if nxt is not None:
            return {**params, "offset": nxt}
        if body.get("hasMore") is True and items:
            return {**params, "offset": int(params.get("offset") or 0) + len(items)}
        return None


@dataclass(frozen=True)
class HasMoreId:
    """``sinceId`` / ``beforeId`` paging that also stops when the server says ``hasMore: false``."""

    param: str

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        if body.get("hasMore") is False:
            return None
        return IdWindowStyle(param=self.param).next_params(params, body, items)


@dataclass(frozen=True)
class HasMoreCursor:
    """``cursor`` paging that stops when ``hasMore`` is false or ``pageEnd`` reaches ``totalChars``.

    Used by ``session_laws.iter_body``. Later pages are addressed by the cursor alone, so
    ``startChar`` is dropped after the first page.
    """

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        nxt = body.get("nextCursor")
        if not nxt or body.get("hasMore") is False:
            return None
        end, total = body.get("pageEnd"), body.get("totalChars")
        if isinstance(end, int) and isinstance(total, int) and end >= total:
            return None  # the last page is the one whose pageEnd equals totalChars
        return {k: v for k, v in params.items() if k != "startChar"} | {"cursor": nxt}


class SyncResource:
    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client


class AsyncResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client
