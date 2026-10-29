"""A LlamaIndex retriever that returns US primary-law sections from Vaquill."""

import hashlib
from typing import Any, Dict, List, Mapping, NoReturn, Optional, Sequence, Union

from pydantic.alias_generators import to_snake

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.callbacks.base import CallbackManager
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.vector_stores.types import FilterOperator, MetadataFilters
from llama_index.tools.vaquill._core import VaquillConnection
from llama_index.tools.vaquill._errors import VaquillToolError, describe_error
from llama_index.tools.vaquill._render import to_data
from vaquill import AsyncVaquill, SpendGuardExceeded, Vaquill

__all__ = ["VaquillRetriever"]

MAX_TOP_K = 50
# Filters that map onto POST /us/statutes/search. The retriever owns query, limit and body.
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
# Planning prices, in credits, used ONLY for the worst-case estimate that refuses a retrieval before
# any request is sent. The SDK ships no static price table (`client.pricing.get()` is a live, free
# network call, and a guard cannot need a request before the first request). These two figures are
# the single source in this package, copied from the OpenAPI contract (openapi/vaquill-us.json:
# `POST /us/statutes/search` "4 credits per call", section text "6 credits" per row) and pinned by
# tests/test_pricing_constants.py. Real spend is read back from `creditsConsumed`.
SEARCH_CREDITS = 4.0
BODY_CREDITS_PER_ROW = 6.0

_DATE_KEYS = ("effectiveDate", "lastAmendedDate", "currentThrough", "expirationDate")
_EXTRA_KEYS = ("corpusType", "actStatus", "sectionTitle", "title")
_EMBED_EXCLUDED = ["id", "sourceUrl", *_DATE_KEYS, "corpusType", "actStatus"]


def _normalize_filters(
    filters: Union[Mapping[str, Any], MetadataFilters, None],
) -> Dict[str, Any]:
    """Validate filters and return them as snake_case search arguments."""
    if filters is None:
        return {}
    pairs: List[Any] = []
    if isinstance(filters, MetadataFilters):
        for item in filters.filters:
            if isinstance(item, MetadataFilters):
                raise ValueError("VaquillRetriever supports only a flat list of EQ and IN metadata filters.")
            operator = getattr(item, "operator", FilterOperator.EQ)
            key = getattr(item, "key", None)
            if key is None or operator not in (FilterOperator.EQ, FilterOperator.IN):
                raise ValueError(
                    "VaquillRetriever supports only EQ and IN metadata filters, on a flat list of filters."
                )
            pairs.append((key, item.value))
    else:
        pairs = list(filters.items())
    out: Dict[str, Any] = {}
    for raw_key, value in pairs:
        key = to_snake(str(raw_key))
        if key not in ALLOWED_FILTERS:
            raise ValueError(f"Unsupported filter {raw_key!r}. Supported: {', '.join(sorted(ALLOWED_FILTERS))}.")
        out[key] = value
    return out


def _first_text(row: Mapping[str, Any]) -> str:
    for key in ("body", "excerpt"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


class VaquillRetriever(BaseRetriever):
    """Retrieve US primary-law sections for a query.

    Each hit becomes a ``NodeWithScore`` whose ``TextNode`` text is the section text and whose
    metadata has ``citation``, ``jurisdiction``, ``id``, ``sourceUrl`` and the effective dates.

    COST: every retrieval is one charged search, 4 credits plus the text price per row when
    ``include_body`` is true (the default, so the nodes hold real section text). Set
    ``max_credits`` to refuse a retrieval that could push the total past your budget.

    Args:
        api_key: ``vq_key_...``. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        similarity_top_k: Sections per query, 1 to 50 (default 5).
        filters: A mapping (``{"state": "ca", "corpus_type": "STATE"}``) or ``MetadataFilters``
            with EQ or IN. Allowed keys: ``ALLOWED_FILTERS``; camelCase is accepted.
        include_body: Fetch full section text (default True). False returns the short
            excerpt, which is cheaper.
        max_credits: Hard cap. A retrieval is refused before any request when its worst-case
            cost would pass the cap, given what this retriever has already spent.
        client: A pre-built ``vaquill.Vaquill``.
        async_client: A pre-built ``vaquill.AsyncVaquill``.
        base_url: Overrides ``VAQUILL_BASE_URL``.
        timeout: Request timeout for clients built here.
        max_retries: Retries for clients built here.
        user_agent_suffix: Extra token appended to the integration User-Agent.
        callback_manager: LlamaIndex callback manager.
        verbose: LlamaIndex verbose flag.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        similarity_top_k: int = 5,
        filters: Union[Mapping[str, Any], MetadataFilters, None] = None,
        include_body: bool = True,
        max_credits: Optional[float] = None,
        client: Optional[Vaquill] = None,
        async_client: Optional[AsyncVaquill] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        user_agent_suffix: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
        verbose: bool = False,
    ) -> None:
        if not 1 <= similarity_top_k <= MAX_TOP_K:
            raise ValueError(f"similarity_top_k must be between 1 and {MAX_TOP_K}, got {similarity_top_k}.")
        self._conn = VaquillConnection(
            api_key,
            client=client,
            async_client=async_client,
            base_url=base_url,
            max_credits=max_credits,
            timeout=timeout,
            max_retries=max_retries,
            user_agent_suffix=user_agent_suffix,
        )
        self.similarity_top_k = similarity_top_k
        self.include_body = include_body
        self._filters = _normalize_filters(filters)
        super().__init__(callback_manager=callback_manager, verbose=verbose)

    @property
    def filters(self) -> Dict[str, Any]:
        """The validated search filters in effect."""
        return dict(self._filters)

    @property
    def credits_spent(self) -> float:
        """Credits consumed through this retriever so far."""
        return self._conn.credits_spent

    @property
    def worst_case_credits(self) -> float:
        """The most one retrieval can cost, used by the ``max_credits`` guard."""
        body = BODY_CREDITS_PER_ROW * self.similarity_top_k if self.include_body else 0.0
        return SEARCH_CREDITS + body

    def _search(self, client: Any, query: str) -> Any:
        return client.statutes.search(
            query,
            limit=self.similarity_top_k,
            include_body=True if self.include_body else None,
            **self._filters,
        )

    def _raise(self, exc: BaseException) -> NoReturn:
        if isinstance(exc, (SpendGuardExceeded, VaquillToolError)):
            raise exc
        raise VaquillToolError(describe_error(exc, self._conn.secrets)) from None

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        try:
            response = self._conn.call(lambda c: self._search(c, query_bundle.query_str), self.worst_case_credits)
        except Exception as exc:
            self._raise(exc)
        return self._to_nodes(response)

    async def _aretrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        try:
            response = await self._conn.acall(
                lambda c: self._search(c, query_bundle.query_str), self.worst_case_credits
            )
        except Exception as exc:
            self._raise(exc)
        return self._to_nodes(response)

    @staticmethod
    def _to_nodes(response: Any) -> List[NodeWithScore]:
        data = to_data(response)
        rows: Sequence[Mapping[str, Any]] = data.get("results", []) if isinstance(data, dict) else []
        nodes: List[NodeWithScore] = []
        for row in rows:
            text = _first_text(row)
            if not text:
                continue
            citation = row.get("citation") or row.get("displayLabel") or row.get("citationShort")
            act_id = row.get("actId")
            metadata: Dict[str, Any] = {
                "citation": citation,
                "jurisdiction": row.get("state"),
                "id": act_id,
                "sourceUrl": row.get("sourceUrl"),
            }
            for key in (*_DATE_KEYS, *_EXTRA_KEYS):
                metadata[key] = row.get(key)
            metadata = {k: v for k, v in metadata.items() if v is not None}
            node_id = act_id or hashlib.sha256(f"{citation}|{text[:200]}".encode()).hexdigest()[:32]
            node = TextNode(
                id_=str(node_id),
                text=text,
                metadata=metadata,
                excluded_embed_metadata_keys=[k for k in _EMBED_EXCLUDED if k in metadata],
            )
            score = row.get("relevanceScore")
            nodes.append(NodeWithScore(node=node, score=float(score) if isinstance(score, (int, float)) else None))
        return nodes
