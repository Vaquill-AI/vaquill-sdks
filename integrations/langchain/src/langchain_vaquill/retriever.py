"""``VaquillRetriever``: US primary law as LangChain Documents, with a hard spend cap."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, SecretStr, model_validator
from vaquill import AsyncVaquill, SpendGuardExceeded, Vaquill

from ._client import ClientProvider
from ._errors import to_tool_exception

__all__ = ["BODY_CREDITS", "SEARCH_CREDITS", "VaquillRetriever"]

#: Planning prices, in credits, used ONLY to refuse a call before it is sent. The SDK does not ship
#: a static price table: `client.pricing.get()` is a live (free) network call, and a guard that
#: needs a request before the first request is not a guard. So the two figures live here, in this
#: one place, copied from the OpenAPI contract (openapi/vaquill-us.json: `POST /us/statutes/search`
#: "4 credits per call", section text "6 credits" per row) and pinned by tests/test_pricing_constants.py.
#: Real spend is always read back from each response's `creditsConsumed`, so a stale constant can
#: only make the pre-call guard too loose or too strict, never mis-bill.
SEARCH_CREDITS = 4.0
BODY_CREDITS = 6.0

ALLOWED_FILTERS = frozenset(
    {
        "state",
        "corpus_type",
        "act_status",
        "agency",
        "article",
        "changed_since",
        "chapter",
        "code",
        "document_type",
        "exclude_repealed",
        "match_type",
        "part",
        "published_from",
        "published_to",
        "source",
        "title_number",
        "year_from",
        "year_to",
    }
)


class VaquillRetriever(BaseRetriever):
    """Retrieve US statutes, regulations, rules and constitutions from Vaquill.

    Each search call COSTS credits: about 4 per call, plus about 6 per returned row when
    ``include_body`` is true (the default, so ``page_content`` is the section text).
    ``max_credits`` is a hard cap for this retriever instance: a call that could push the total
    over it is refused before any request is sent, and the SDK guard counts the real spend.

    Args:
        api_key: ``vq_key_...``. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        client / async_client: Existing SDK clients to reuse.
        k: Documents per query (1 to 50).
        filters: Search filters, snake_case names of ``Vaquill.statutes.search`` such as
            ``{"state": "ca", "corpus_type": ["STATE"], "exclude_repealed": True}``.
        include_body: True for section text in ``page_content`` (about 6 extra credits per row).
            False returns the excerpt, which costs only the search price.
        max_credits: Hard spend cap in credits for this retriever. Default 50.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key: SecretStr | None = Field(default=None, repr=False)
    client: Vaquill | None = Field(default=None, exclude=True)
    async_client: AsyncVaquill | None = Field(default=None, exclude=True)
    base_url: str | None = None
    k: int = Field(default=4, ge=1, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)
    include_body: bool = True
    max_credits: float = Field(default=50.0, gt=0)

    _provider: ClientProvider | None = None
    _spent: float = 0.0

    @model_validator(mode="after")
    def _check(self) -> VaquillRetriever:
        bad = sorted(set(self.filters) - ALLOWED_FILTERS)
        if bad:
            raise ValueError(
                f"Unsupported filter(s): {', '.join(bad)}. Allowed: {', '.join(sorted(ALLOWED_FILTERS))}."
            )
        self._provider = ClientProvider(
            api_key=self.api_key.get_secret_value() if self.api_key else None,
            client=self.client,
            async_client=self.async_client,
            base_url=self.base_url,
            max_credits=self.max_credits,
        )
        return self

    # -- spend ----------------------------------------------------------------------------

    @property
    def credits_spent(self) -> float:
        """Credits this retriever has consumed (from each response's creditsConsumed)."""
        return self._spent

    @property
    def estimated_call_cost(self) -> float:
        return SEARCH_CREDITS + (BODY_CREDITS * self.k if self.include_body else 0.0)

    def _guard(self) -> None:
        if self._spent + self.estimated_call_cost > self.max_credits:
            raise SpendGuardExceeded(
                f"max_credits={self.max_credits:g} would be exceeded: {self._spent:g} spent, "
                f"next call may cost up to {self.estimated_call_cost:g}. No request was sent."
            )

    def _args(self, query: str) -> dict[str, Any]:
        args: dict[str, Any] = {"query": query, "limit": self.k, "include_body": self.include_body}
        args.update({k: v for k, v in self.filters.items() if v is not None})
        return args

    # -- documents ------------------------------------------------------------------------

    def _to_documents(self, response: Any) -> list[Document]:
        self._spent += float(getattr(response, "credits_consumed", None) or 0.0)
        docs = []
        for row in response.results or []:
            excerpt = row.excerpt or ""
            text = (row.body or excerpt) if self.include_body else excerpt
            meta: dict[str, Any] = {
                "id": row.act_id,
                "citation": row.citation,
                "jurisdiction": row.state,
                "sourceUrl": row.source_url,
                "corpusType": row.corpus_type,
                "actStatus": row.act_status,
                "sectionTitle": row.section_title,
                "effectiveDate": row.effective_date,
                "lastAmendedDate": row.last_amended_date,
                "currentThrough": row.current_through,
                "score": row.relevance_score,
            }
            docs.append(
                Document(
                    id=row.act_id,
                    page_content=text,
                    metadata={k: v for k, v in meta.items() if v is not None},
                )
            )
        return docs

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        self._guard()
        try:
            response = self._provider_().sync_client.statutes.search(**self._args(query))
        except SpendGuardExceeded:
            raise
        except Exception as exc:
            raise to_tool_exception(exc) from None
        return self._to_documents(response)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        self._guard()
        args = self._args(query)
        try:
            response = await self._provider_().acall(lambda c: c.statutes.search(**args))
        except SpendGuardExceeded:
            raise
        except Exception as exc:
            raise to_tool_exception(exc) from None
        return self._to_documents(response)

    def _provider_(self) -> ClientProvider:
        assert self._provider is not None
        return self._provider
