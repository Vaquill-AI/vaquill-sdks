"""``client.boards``: the sources a watch can follow (free)."""

from __future__ import annotations

from typing import Any, Unpack

from .._pagination import SyncPaginator
from ..types import BoardResponse, BoardsEnvelope
from ._base import HasMoreOffset, RequestOptions, SyncResource

__all__ = ["SyncBoards"]


class SyncBoards(SyncResource):
    def list(
        self,
        *,
        corpus_type: str | None = None,
        state: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        **options: Unpack[RequestOptions],
    ) -> BoardsEnvelope:
        """List the sources you can watch, with ``lastRetrievedAt`` and ``cadence``. Free.

        Args:
            corpus_type: Only this corpus type.
            state: Only this jurisdiction (lowercase code, for example ``"wa"``).
            limit: Page size, 1 to 500 (server default 500).
            offset: Rows to skip.
        """
        params = {"corpusType": corpus_type, "state": state, "limit": limit, "offset": offset}
        return self._client.request(
            "GET", "/api/v1/boards", cast_to=BoardsEnvelope, params=params, **options
        )

    def iter_list(
        self,
        *,
        corpus_type: str | None = None,
        state: str | None = None,
        limit: int = 500,
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> SyncPaginator[BoardResponse]:
        """Iterate every board across pages. Free, so no credit guard is needed."""

        def fetch(params: dict[str, Any]) -> Any:
            response = self._client.raw_request("GET", "/api/v1/boards", params=params)
            return response.json()["data"]

        return SyncPaginator(
            fetch,
            style=HasMoreOffset(),
            items_key="boards",
            params={"corpusType": corpus_type, "state": state, "limit": limit, "offset": 0},
            max_pages=max_pages,
            max_items=max_items,
            parse=BoardResponse.model_validate,
        )
