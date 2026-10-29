"""Public clients. Each exposes the resource namespaces (``client.statutes`` and friends)."""

from __future__ import annotations

from functools import cached_property

from ._base_client import AsyncAPIClient, SyncAPIClient
from .resources import (
    AsyncBoards,
    AsyncCredits,
    AsyncPricing,
    AsyncSessionLaws,
    AsyncStatutes,
    AsyncWatches,
    SyncBoards,
    SyncCredits,
    SyncPricing,
    SyncSessionLaws,
    SyncStatutes,
    SyncWatches,
)

__all__ = ["AsyncVaquill", "Vaquill"]


class Vaquill(SyncAPIClient):
    """Synchronous client.

    Namespaces: ``statutes``, ``session_laws``, ``watches``, ``boards``, ``credits``, ``pricing``.

    Args:
        api_key: ``vq_key_...``. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        base_url: Defaults to ``VAQUILL_BASE_URL``, then ``https://api.vaquill.ai``.
        timeout: Seconds or an ``httpx.Timeout``. Overridable per call.
        max_retries: Retries after the first attempt (default 2).
        default_headers: Extra headers on every request. Authorization cannot be overridden.
        idempotency_keys: Send an auto-generated ``Idempotency-Key`` on charged calls (default
            True). When False, charged calls are not retried after an ambiguous failure.
        max_credits: Optional spend guard. Charged calls raise ``SpendGuardExceeded`` once
            the credits consumed through this client reach the cap.
        http_client: An ``httpx.Client`` to use (proxies, mTLS, test doubles). Not closed by us.
    """

    @cached_property
    def statutes(self) -> SyncStatutes:
        return SyncStatutes(self)

    @cached_property
    def session_laws(self) -> SyncSessionLaws:
        return SyncSessionLaws(self)

    @cached_property
    def watches(self) -> SyncWatches:
        return SyncWatches(self)

    @cached_property
    def boards(self) -> SyncBoards:
        return SyncBoards(self)

    @cached_property
    def credits(self) -> SyncCredits:
        return SyncCredits(self)

    @cached_property
    def pricing(self) -> SyncPricing:
        return SyncPricing(self)


class AsyncVaquill(AsyncAPIClient):
    """Asynchronous client. Same arguments and namespaces as :class:`Vaquill`."""

    @cached_property
    def statutes(self) -> AsyncStatutes:
        return AsyncStatutes(self)

    @cached_property
    def session_laws(self) -> AsyncSessionLaws:
        return AsyncSessionLaws(self)

    @cached_property
    def watches(self) -> AsyncWatches:
        return AsyncWatches(self)

    @cached_property
    def boards(self) -> AsyncBoards:
        return AsyncBoards(self)

    @cached_property
    def credits(self) -> AsyncCredits:
        return AsyncCredits(self)

    @cached_property
    def pricing(self) -> AsyncPricing:
        return AsyncPricing(self)
