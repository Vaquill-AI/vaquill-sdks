"""``client.watches``: law-change alerts. Free except :meth:`SyncWatches.change_diff`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Unpack

from .._pagination import SyncPaginator
from ..types import (
    ChangeDiffEnvelope,
    ChangeResponse,
    ChangesEnvelope,
    DeliveriesEnvelope,
    WatchEnvelope,
    WatchesEnvelope,
    WatchResponse,
    WatchTestEnvelope,
    WebhookAuthRequest,
)
from ._base import HasMoreId, HasMoreOffset, RequestOptions, SyncResource, compact, seg, wire

__all__ = ["SyncWatches"]

WebhookAuth = WebhookAuthRequest | Mapping[str, Any]


def _auth(value: WebhookAuth | None) -> Mapping[str, Any] | None:
    if isinstance(value, WebhookAuthRequest):
        return value.model_dump(by_alias=True, exclude_none=True)
    return value


class SyncWatches(SyncResource):
    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        **options: Unpack[RequestOptions],
    ) -> WatchesEnvelope:
        """List your watches. Free.

        Args:
            limit: Page size, 1 to 200 (server default 100).
            offset: Watches to skip.
        """
        return self._client.request(
            "GET",
            "/api/v1/watches",
            cast_to=WatchesEnvelope,
            params={"limit": limit, "offset": offset},
            **options,
        )

    def iter_list(
        self, *, limit: int = 100, max_pages: int | None = None, max_items: int | None = None
    ) -> SyncPaginator[WatchResponse]:
        """Iterate all your watches across pages. Free."""

        def fetch(params: dict[str, Any]) -> Any:
            response = self._client.raw_request("GET", "/api/v1/watches", params=params)
            return response.json()["data"]

        return SyncPaginator(
            fetch,
            style=HasMoreOffset(),
            items_key="watches",
            params={"limit": limit, "offset": 0},
            max_pages=max_pages,
            max_items=max_items,
            parse=WatchResponse.model_validate,
        )

    def create(
        self,
        corpus_type: str,
        *,
        state: str | None = None,
        channel: str | None = None,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        webhook_auth: WebhookAuth | None = None,
        email_address: str | None = None,
        scope: Mapping[str, Any] | None = None,
        **options: Unpack[RequestOptions],
    ) -> WatchEnvelope:
        """Watch a corpus source and get a webhook or email when it changes. Free.

        Args:
            corpus_type: Corpus to watch (see ``client.boards.list``).
            state: Jurisdiction code, when the corpus is per state.
            channel: ``"webhook"`` (default), ``"email"`` or ``"both"``.
            webhook_url: HTTPS endpoint that receives the events.
            webhook_secret: Signing secret; verify deliveries with ``vaquill.verify_webhook``.
            webhook_auth: Extra auth the server attaches to each delivery.
            email_address: Recipient for the email channel.
            scope: Narrow the watch (see the API reference).
        """
        body = {
            "corpusType": corpus_type,
            "state": state,
            "channel": channel,
            "webhookUrl": webhook_url,
            "webhookSecret": webhook_secret,
            "webhookAuth": _auth(webhook_auth),
            "emailAddress": email_address,
            "scope": scope,
        }
        return self._client.request(
            "POST", "/api/v1/watches", cast_to=WatchEnvelope, json=compact(body), **options
        )

    def update(
        self,
        watch_id: str,
        *,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        webhook_auth: WebhookAuth | None = None,
        email_address: str | None = None,
        is_active: bool | None = None,
        scope: Mapping[str, Any] | None = None,
        **options: Unpack[RequestOptions],
    ) -> WatchEnvelope:
        """Change a watch. Only the arguments you pass are updated. Free."""
        body = {
            "webhookUrl": webhook_url,
            "webhookSecret": webhook_secret,
            "webhookAuth": _auth(webhook_auth),
            "emailAddress": email_address,
            "isActive": is_active,
            "scope": scope,
        }
        return self._client.request(
            "PATCH",
            f"/api/v1/watches/{seg(watch_id)}",
            cast_to=WatchEnvelope,
            json=compact(body),
            **options,
        )

    def delete(self, watch_id: str, **options: Unpack[RequestOptions]) -> None:
        """Delete a watch. Free."""
        return self._client.request(
            "DELETE", f"/api/v1/watches/{seg(watch_id)}", cast_to=type(None), **options
        )

    def test(self, watch_id: str, **options: Unpack[RequestOptions]) -> WatchTestEnvelope:
        """Send a test event to the watch's channel. Free."""
        return self._client.request(
            "POST", f"/api/v1/watches/{seg(watch_id)}/test", cast_to=WatchTestEnvelope, **options
        )

    def changes(
        self,
        watch_id: str,
        *,
        limit: int | None = None,
        since_id: int | None = None,
        before_id: int | None = None,
        since: str | None = None,
        change_kind: Sequence[str] | None = None,
        order: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> ChangesEnvelope:
        """List the changes a watch has recorded. Free.

        Args:
            watch_id: The watch.
            limit: Page size, 1 to 200 (server default 50).
            since_id: Only changes with a larger id (walk forward, use with ``order="asc"``).
            before_id: Only changes with a smaller id (walk back through history).
            since: Only changes detected after this ISO timestamp.
            change_kind: Only these kinds of change.
            order: ``"desc"`` (default, newest first) or ``"asc"``.
        """
        params = {
            "limit": limit,
            "sinceId": since_id,
            "beforeId": before_id,
            "since": since,
            "changeKind": change_kind,
            "order": order,
        }
        return self._client.request(
            "GET",
            f"/api/v1/watches/{seg(watch_id)}/changes",
            cast_to=ChangesEnvelope,
            params=params,
            **options,
        )

    def iter_changes(
        self,
        watch_id: str,
        *,
        limit: int = 50,
        since: str | None = None,
        change_kind: Sequence[str] | None = None,
        order: str = "desc",
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> SyncPaginator[ChangeResponse]:
        """Iterate a watch's changes across pages (free). Newest first unless ``order="asc"``."""

        def fetch(params: dict[str, Any]) -> Any:
            response = self._client.raw_request(
                "GET", f"/api/v1/watches/{seg(watch_id)}/changes", params=params
            )
            return response.json()["data"]

        return SyncPaginator(
            fetch,
            style=HasMoreId("sinceId" if order == "asc" else "beforeId"),
            items_key="changes",
            params=wire(
                {"limit": limit, "since": since, "change_kind": change_kind, "order": order}
            ),
            max_pages=max_pages,
            max_items=max_items,
            parse=ChangeResponse.model_validate,
        )

    def change_diff(
        self, watch_id: str, change_id: int, **options: Unpack[RequestOptions]
    ) -> ChangeDiffEnvelope:
        """Before and after text of one change. Charged (see docs/OPERATIONS.md)."""
        return self._client.request(
            "GET",
            f"/api/v1/watches/{seg(watch_id)}/changes/{change_id}/diff",
            cast_to=ChangeDiffEnvelope,
            charged=True,
            **options,
        )

    def deliveries(
        self, watch_id: str, *, limit: int | None = None, **options: Unpack[RequestOptions]
    ) -> DeliveriesEnvelope:
        """Recent webhook and email deliveries for a watch, with delivery health. Free.

        Args:
            watch_id: The watch.
            limit: Deliveries to return, 1 to 200 (server default 50).
        """
        return self._client.request(
            "GET",
            f"/api/v1/watches/{seg(watch_id)}/deliveries",
            cast_to=DeliveriesEnvelope,
            params={"limit": limit},
            **options,
        )
