"""Pieces shared by every resource: request options, path and body helpers, paging styles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict
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
    """Percent-encode one path segment (a citation may be passed where an id goes)."""
    return quote(value, safe="")


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


class SyncResource:
    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client


class AsyncResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client
