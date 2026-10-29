"""``client.credits``: your credit balance (free)."""

from __future__ import annotations

from typing import Unpack

from ..types import ExternalCreditBalanceResponse
from ._base import RequestOptions, SyncResource

__all__ = ["SyncCredits"]


class SyncCredits(SyncResource):
    def balance(self, **options: Unpack[RequestOptions]) -> ExternalCreditBalanceResponse:
        """Credits this key's account can spend right now, from live buckets. Free."""
        return self._client.request(
            "GET", "/api/v1/credits/balance", cast_to=ExternalCreditBalanceResponse, **options
        )
