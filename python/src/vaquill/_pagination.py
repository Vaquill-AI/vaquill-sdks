"""Auto-paginating iterators for offset, cursor and id-window list endpoints.

WARNING: on charged endpoints every page spends credits. Iterating a whole result set can
cost far more than one call. Always set ``max_pages`` or ``max_items`` unless you intend
to read everything. When a guard stops iteration early, ``truncated`` is True.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")
Fetch = Callable[[dict[str, Any]], Mapping[str, Any]]
AsyncFetch = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]


class PageStyle(Protocol):
    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        """Params for the next page, or None when this was the last."""
        ...


@dataclass(frozen=True)
class OffsetStyle:
    """``offset`` request param, ``nextOffset`` response member (null on the last page)."""

    param: str = "offset"
    next_key: str = "nextOffset"

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        nxt = body.get(self.next_key)
        return None if nxt is None else {**params, self.param: nxt}


@dataclass(frozen=True)
class CursorStyle:
    """Opaque ``cursor`` request param, ``nextCursor`` response member."""

    param: str = "cursor"
    next_key: str = "nextCursor"

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        nxt = body.get(self.next_key)
        return None if not nxt else {**params, self.param: nxt}


@dataclass(frozen=True)
class IdWindowStyle:
    """``sinceId`` (walking forward) or ``beforeId`` (walking back) from the last item's id.

    Stops on an empty page, or a short page when ``limit_param`` is set in the params.
    """

    param: str = "beforeId"
    id_key: str = "id"
    limit_param: str = "limit"

    def next_params(
        self, params: dict[str, Any], body: Mapping[str, Any], items: list[Any]
    ) -> dict[str, Any] | None:
        if not items:
            return None
        limit = params.get(self.limit_param)
        if isinstance(limit, int) and len(items) < limit:
            return None
        last = items[-1]
        last_id = last.get(self.id_key) if isinstance(last, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return None if last_id is None else {**params, self.param: last_id}


class _State(Generic[T]):
    def __init__(
        self,
        style: PageStyle,
        items_key: str,
        params: Mapping[str, Any] | None,
        max_pages: int | None,
        max_items: int | None,
        parse: Callable[[Any], T] | None,
    ) -> None:
        self.style = style
        self.items_key = items_key
        self.params: dict[str, Any] | None = dict(params or {})
        self.max_pages = max_pages
        self.max_items = max_items
        self.parse = parse
        self.pages = 0
        self.count = 0
        self.truncated = False

    def exhausted(self) -> bool:
        """Whether a guard forbids fetching another page. Marks ``truncated`` if more existed."""
        if self.params is None:
            return True
        if (self.max_pages is not None and self.pages >= self.max_pages) or (
            self.max_items is not None and self.count >= self.max_items
        ):
            self.truncated = True
            return True
        return False

    def take(self, body: Mapping[str, Any]) -> list[T]:
        assert self.params is not None
        raw: Any = body.get(self.items_key) or []
        raw_items: list[Any] = list(raw) if isinstance(raw, list) else []  # pyright: ignore[reportUnknownArgumentType]
        self.params = self.style.next_params(self.params, body, raw_items)
        self.pages += 1
        if self.max_items is not None:
            raw_items = raw_items[: self.max_items - self.count]
        self.count += len(raw_items)
        return [self.parse(i) for i in raw_items] if self.parse else raw_items


class SyncPaginator(Generic[T]):
    """Iterate items across pages; ``pages()`` yields whole pages to control cost."""

    def __init__(
        self,
        fetch: Fetch,
        *,
        style: PageStyle,
        items_key: str = "items",
        params: Mapping[str, Any] | None = None,
        max_pages: int | None = None,
        max_items: int | None = None,
        parse: Callable[[Any], T] | None = None,
    ) -> None:
        self._fetch = fetch
        self._state = _State(style, items_key, params, max_pages, max_items, parse)

    @property
    def truncated(self) -> bool:
        return self._state.truncated

    def pages(self) -> Iterator[list[T]]:
        s = self._state
        while not s.exhausted():
            assert s.params is not None
            yield s.take(self._fetch(dict(s.params)))

    def __iter__(self) -> Iterator[T]:
        for page in self.pages():
            yield from page


class AsyncPaginator(Generic[T]):
    def __init__(
        self,
        fetch: AsyncFetch,
        *,
        style: PageStyle,
        items_key: str = "items",
        params: Mapping[str, Any] | None = None,
        max_pages: int | None = None,
        max_items: int | None = None,
        parse: Callable[[Any], T] | None = None,
    ) -> None:
        self._fetch = fetch
        self._state = _State(style, items_key, params, max_pages, max_items, parse)

    @property
    def truncated(self) -> bool:
        return self._state.truncated

    async def pages(self) -> AsyncIterator[list[T]]:
        s = self._state
        while not s.exhausted():
            assert s.params is not None
            yield s.take(await self._fetch(dict(s.params)))

    async def __aiter__(self) -> AsyncIterator[T]:
        async for page in self.pages():
            for item in page:
                yield item
