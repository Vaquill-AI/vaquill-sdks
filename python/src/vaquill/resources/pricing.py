"""``client.pricing``: the credit price of every endpoint (free)."""

from __future__ import annotations

from typing import Unpack

from ..types import ApiCreditPricingResponse
from ._base import RequestOptions, SyncResource

__all__ = ["SyncPricing"]


class SyncPricing(SyncResource):
    def get(
        self, *, region: str | None = None, **options: Unpack[RequestOptions]
    ) -> ApiCreditPricingResponse:
        """The full pricing matrix: credits and USD per endpoint. Free.

        Args:
            region: Jurisdiction to price (``"US"``).
        """
        return self._client.request(
            "GET",
            "/api/v1/api-credits/pricing",
            cast_to=ApiCreditPricingResponse,
            params={"region": region},
            **options,
        )
