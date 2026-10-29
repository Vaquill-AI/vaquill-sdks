"""``client.statutes``: US statutes, regulations, rules and constitutions.

Every operation is charged except :meth:`SyncStatutes.coverage`. See docs/OPERATIONS.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict, Unpack

from .._pagination import CursorStyle, SyncPaginator
from ..types import (
    ExtractCitationsResponse,
    PartRulemakingResponse,
    SectionEnactmentsResponse,
    SectionRulemakingResponse,
    StatuteBodyResponse,
    StatuteChangeEvent,
    StatuteChangesResponse,
    StatuteCitedByResponse,
    StatuteCountResponse,
    StatuteCrossStateResponse,
    StatuteDefinitionsResponse,
    StatuteNeighborsResponse,
    StatuteResolveBatchItem,
    StatuteResolveBatchResponse,
    StatuteResolveResponse,
    StatuteResult,
    StatuteSearchResponse,
    StatuteSectionResponse,
    StatuteSectionsResponse,
    UsDivisionNode,
    UsStatutesCoverageEnvelope,
    UsStatutesDivisionsResponse,
)
from ._base import (
    HasMoreId,
    NextOffsetOrHasMore,
    RequestOptions,
    SyncResource,
    chunk_options,
    chunked,
    compact,
    seg,
    unique,
    wire,
)

__all__ = ["SyncStatutes"]

Strs = str | Sequence[str]


RESOLVE_BATCH_MAX = 500
"""Citations per ``POST /us/statutes/resolve`` call (``maxItems`` in the spec)."""
SECTIONS_BATCH_MAX = 50
"""Ids per ``POST /us/statutes/sections`` call (``maxItems`` in the spec)."""


class SearchFilters(TypedDict, total=False):
    """Filters of :meth:`SyncStatutes.search`, also taken by ``iter_search``."""

    state: str
    corpus_type: Strs
    act_status: str
    agency: Strs
    article: Strs
    changed_since: str
    chapter: Strs
    code: Strs
    document_type: str
    excerpt_chars: int
    exclude_repealed: bool
    fields: Sequence[str]
    include_body: bool
    include_pinpoint: bool
    limit: int
    match_type: str
    part: Strs
    published_from: str
    published_to: str
    source: str
    title_number: int
    year_from: int
    year_to: int


class DivisionFilters(TypedDict, total=False):
    """Filters of :meth:`SyncStatutes.divisions`, also taken by ``iter_divisions``."""

    state: str
    title_number: int
    code: str
    chapter: str
    part: str
    article: str
    exclude_repealed: bool
    act_status: str
    subchapter: str
    act: str
    title: str
    subtitle: str
    division: str
    subdivision: str
    subpart: str
    subject_group: str


class SyncStatutes(SyncResource):
    def search(
        self,
        query: str,
        *,
        state: str | None = None,
        corpus_type: Strs | None = None,
        act_status: str | None = None,
        agency: Strs | None = None,
        article: Strs | None = None,
        changed_since: str | None = None,
        chapter: Strs | None = None,
        code: Strs | None = None,
        document_type: str | None = None,
        excerpt_chars: int | None = None,
        exclude_repealed: bool | None = None,
        fields: Sequence[str] | None = None,
        include_body: bool | None = None,
        include_pinpoint: bool | None = None,
        limit: int | None = None,
        match_type: str | None = None,
        offset: int | None = None,
        part: Strs | None = None,
        published_from: str | None = None,
        published_to: str | None = None,
        source: str | None = None,
        title_number: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteSearchResponse:
        """Hybrid search across the corpus, or a boolean query. Charged, 4 credits per call.

        ``include_body`` adds the body price for every row that returns text.

        Args:
            query: Search text, a citation, or a boolean expression with ``match_type="boolean"``.
            state: Lowercase jurisdiction code (``"federal"``, ``"ca"``...).
            corpus_type: One corpus type or a list (see ``vaquill.types.CorpusType``).
            act_status: Only this status (``"in_force"``...).
            agency: Agency slug(s), for agency corpora.
            article: Article filter.
            changed_since: Only sections changed after this date.
            chapter: Chapter filter.
            code: Code filter.
            document_type: Federal Register document type.
            excerpt_chars: Excerpt length, 100 to 4000 (server default 500).
            exclude_repealed: Leave out repealed sections.
            fields: Response fields to return.
            include_body: Return the section text in each row.
            include_pinpoint: Resolve a pinpoint inside the query.
            limit: Results per page, 1 to 50 (server default 10).
            match_type: ``"any"``, ``"all"``, ``"phrase"`` or ``"boolean"``.
            offset: Results to skip (server maximum 10000).
            part: Part filter.
            published_from: Earliest publication date.
            published_to: Latest publication date.
            source: Source filter.
            title_number: Title number filter.
            year_from: Earliest year.
            year_to: Latest year.
        """
        body = {
            "query": query,
            "state": state,
            "corpusType": corpus_type,
            "actStatus": act_status,
            "agency": agency,
            "article": article,
            "changedSince": changed_since,
            "chapter": chapter,
            "code": code,
            "documentType": document_type,
            "excerptChars": excerpt_chars,
            "excludeRepealed": exclude_repealed,
            "fields": fields,
            "includeBody": include_body,
            "includePinpoint": include_pinpoint,
            "limit": limit,
            "matchType": match_type,
            "offset": offset,
            "part": part,
            "publishedFrom": published_from,
            "publishedTo": published_to,
            "source": source,
            "titleNumber": title_number,
            "yearFrom": year_from,
            "yearTo": year_to,
        }
        return self._client.request(
            "POST",
            "/api/v1/us/statutes/search",
            cast_to=StatuteSearchResponse,
            json=compact(body),
            charged=True,
            **options,
        )

    def iter_search(
        self,
        query: str,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        **filters: Unpack[SearchFilters],
    ) -> SyncPaginator[StatuteResult]:
        """Iterate :meth:`search` results across pages. Every page is charged: set a guard."""

        def fetch(body: dict[str, Any]) -> Any:
            response = self._client.raw_request(
                "POST", "/api/v1/us/statutes/search", json=body, charged=True
            )
            return response.json()

        return SyncPaginator(
            fetch,
            style=NextOffsetOrHasMore(),
            items_key="results",
            params=wire({"query": query, **filters, "offset": 0}),
            max_pages=max_pages,
            max_items=max_items,
            parse=StatuteResult.model_validate,
        )

    def resolve(
        self,
        cite: str,
        *,
        state: str | None = None,
        corpus_type: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteResolveResponse:
        """Resolve one citation to its exact section. Charged, 2 credits, even if unresolved.

        Args:
            cite: The citation, for example ``"42 U.S.C. 1983"``.
            state: Jurisdiction hint for a bare citation.
            corpus_type: Corpus hint (``"STATE"``, ``"REGULATION"``...).
        """
        return self._client.request(
            "GET",
            "/api/v1/us/statutes/resolve",
            cast_to=StatuteResolveResponse,
            params={"cite": cite, "state": state, "corpusType": corpus_type},
            charged=True,
            **options,
        )

    def resolve_batch(
        self,
        citations: Sequence[str],
        *,
        state: str | None = None,
        corpus_type: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteResolveBatchResponse:
        """Resolve many citations. Charged, 2 credits per citation, unresolved ones included.

        Args:
            citations: The citations.
            state: Jurisdiction hint for bare citations.
            corpus_type: Corpus hint.
        """
        body = {"citations": list(citations), "state": state, "corpusType": corpus_type}
        return self._client.request(
            "POST",
            "/api/v1/us/statutes/resolve",
            cast_to=StatuteResolveBatchResponse,
            json=compact(body),
            charged=True,
            **options,
        )

    def resolve_batch_all(
        self,
        citations: Sequence[str],
        *,
        state: str | None = None,
        corpus_type: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> list[StatuteResolveBatchItem]:
        """Resolve any number of citations by chunking :meth:`resolve_batch`. Charged.

        Sends at most ``RESOLVE_BATCH_MAX`` (500, the spec's per-call cap) citations per call and
        returns the ``results`` of every call as one flat list, in order. Exact repeats are sent
        once. The ``max_credits`` spend guard is checked before each chunk, so a guard that is
        reached part way raises ``SpendGuardExceeded`` and the later chunks are not sent.
        A caller's ``idempotency_key`` is suffixed with the chunk number after the first chunk.

        Args:
            citations: The citations.
            state: Jurisdiction hint for bare citations.
            corpus_type: Corpus hint.
        """
        results: list[StatuteResolveBatchItem] = []
        for i, chunk in enumerate(chunked(unique(citations), RESOLVE_BATCH_MAX)):
            body = {"citations": chunk, "state": state, "corpusType": corpus_type}
            response = self._client.request(
                "POST",
                "/api/v1/us/statutes/resolve",
                cast_to=StatuteResolveBatchResponse,
                json=compact(body),
                charged=True,
                **chunk_options(options, i),
            )
            results.extend(response.results or [])
        return results

    def get_section(self, act_id: str, **options: Unpack[RequestOptions]) -> StatuteSectionResponse:
        """A section's metadata (no text). Charged, 2 credits.

        Args:
            act_id: The section id, for example from :meth:`resolve`.
        """
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}",
            cast_to=StatuteSectionResponse,
            charged=True,
            **options,
        )

    def get_section_body(
        self,
        act_id: str,
        *,
        format: str | None = None,
        structured: bool | None = None,
        pinpoint: str | None = None,
        as_of: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteBodyResponse:
        """A section's text. Charged, 6 credits (0 when the text is not held).

        Args:
            act_id: The section id.
            format: Text format to return (``"html"``, ``"plain"``, ``"markdown"``...).
            structured: Also return the subsection tree.
            pinpoint: A subsection such as ``"(a)(1)"``.
            as_of: Read the section as it stood on this date.
        """
        params = {"format": format, "structured": structured, "pinpoint": pinpoint, "asOf": as_of}
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/body",
            cast_to=StatuteBodyResponse,
            params=params,
            charged=True,
            **options,
        )

    def neighbors(
        self, act_id: str, *, limit: int | None = None, **options: Unpack[RequestOptions]
    ) -> StatuteNeighborsResponse:
        """Related sections (``/related``). Charged, 2 credits.

        Args:
            act_id: The section id.
            limit: Neighbours to return, 1 to 10 (server default 3).
        """
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/related",
            cast_to=StatuteNeighborsResponse,
            params={"limit": limit},
            charged=True,
            **options,
        )

    def get_sections_batch(
        self,
        act_ids: Sequence[str],
        *,
        include_body: bool | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteSectionsResponse:
        """Many sections at once. Charged, 2 credits per section returned.

        Args:
            act_ids: Section ids.
            include_body: Also return each section's text (the body price applies).
        """
        body = {"actIds": list(act_ids), "includeBody": include_body}
        return self._client.request(
            "POST",
            "/api/v1/us/statutes/sections",
            cast_to=StatuteSectionsResponse,
            json=compact(body),
            charged=True,
            **options,
        )

    def get_sections_all(
        self,
        act_ids: Sequence[str],
        *,
        include_body: bool | None = None,
        **options: Unpack[RequestOptions],
    ) -> list[StatuteResult]:
        """Fetch any number of sections by chunking :meth:`get_sections_batch`. Charged.

        Sends at most ``SECTIONS_BATCH_MAX`` (50, the spec's per-call cap) ids per call and returns
        the ``sections`` of every call as one flat list, in order. Exact repeats are sent once.
        The ``max_credits`` spend guard is checked before each chunk, so a guard that is reached
        part way raises ``SpendGuardExceeded`` and the later chunks are not sent. Ids with no
        match are dropped (use :meth:`get_sections_batch` to see ``notFound``).
        A caller's ``idempotency_key`` is suffixed with the chunk number after the first chunk.

        Args:
            act_ids: Section ids.
            include_body: Also return each section's text (the body price applies).
        """
        sections: list[StatuteResult] = []
        for i, chunk in enumerate(chunked(unique(act_ids), SECTIONS_BATCH_MAX)):
            body = {"actIds": chunk, "includeBody": include_body}
            response = self._client.request(
                "POST",
                "/api/v1/us/statutes/sections",
                cast_to=StatuteSectionsResponse,
                json=compact(body),
                charged=True,
                **chunk_options(options, i),
            )
            sections.extend(response.sections or [])
        return sections

    def count(
        self,
        *,
        query: str | None = None,
        state: str | None = None,
        corpus_type: Strs | None = None,
        act_status: str | None = None,
        article: Strs | None = None,
        chapter: Strs | None = None,
        code: Strs | None = None,
        exclude_repealed: bool | None = None,
        match_type: str | None = None,
        part: Strs | None = None,
        title_number: int | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteCountResponse:
        """Count the sections in a scope or matching a boolean query. Charged, 1 credit."""
        body = {
            "query": query,
            "state": state,
            "corpusType": corpus_type,
            "actStatus": act_status,
            "article": article,
            "chapter": chapter,
            "code": code,
            "excludeRepealed": exclude_repealed,
            "matchType": match_type,
            "part": part,
            "titleNumber": title_number,
        }
        return self._client.request(
            "POST",
            "/api/v1/us/statutes/count",
            cast_to=StatuteCountResponse,
            json=compact(body),
            charged=True,
            **options,
        )

    def coverage(
        self, *, state: str | None = None, **options: Unpack[RequestOptions]
    ) -> UsStatutesCoverageEnvelope:
        """What the corpus holds, per jurisdiction and corpus type. Free.

        Args:
            state: Only this jurisdiction.
        """
        return self._client.request(
            "GET",
            "/api/v1/us/statutes/coverage",
            cast_to=UsStatutesCoverageEnvelope,
            params={"state": state},
            **options,
        )

    def divisions(
        self,
        corpus_type: str,
        *,
        state: str | None = None,
        title_number: int | None = None,
        code: str | None = None,
        chapter: str | None = None,
        part: str | None = None,
        article: str | None = None,
        exclude_repealed: bool | None = None,
        act_status: str | None = None,
        subchapter: str | None = None,
        act: str | None = None,
        title: str | None = None,
        subtitle: str | None = None,
        division: str | None = None,
        subdivision: str | None = None,
        subpart: str | None = None,
        subject_group: str | None = None,
        cursor: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> UsStatutesDivisionsResponse:
        """Browse one level of the hierarchy (titles, chapters, parts...). Charged, 1 credit.

        Args:
            corpus_type: The corpus to browse.
            state: Jurisdiction code, for state corpora.
            title_number: USC/CFR title.
            code: State code name.
            chapter: Descend into this chapter.
            part: Descend into this part.
            article: Descend into this article.
            exclude_repealed: Leave out repealed divisions.
            act_status: Only this status.
            subchapter: Descend into this subchapter.
            act: Descend into this act.
            title: Descend into this title.
            subtitle: Descend into this subtitle.
            division: Descend into this division.
            subdivision: Descend into this subdivision.
            subpart: Descend into this subpart.
            subject_group: Descend into this subject group.
            cursor: ``nextCursor`` of the previous page.
        """
        params = {
            "corpusType": corpus_type,
            "state": state,
            "titleNumber": title_number,
            "code": code,
            "chapter": chapter,
            "part": part,
            "article": article,
            "excludeRepealed": exclude_repealed,
            "actStatus": act_status,
            "subchapter": subchapter,
            "act": act,
            "title": title,
            "subtitle": subtitle,
            "division": division,
            "subdivision": subdivision,
            "subpart": subpart,
            "subjectGroup": subject_group,
            "cursor": cursor,
        }
        return self._client.request(
            "GET",
            "/api/v1/us/statutes/divisions",
            cast_to=UsStatutesDivisionsResponse,
            params=params,
            charged=True,
            **options,
        )

    def iter_divisions(
        self,
        corpus_type: str,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        **filters: Unpack[DivisionFilters],
    ) -> SyncPaginator[UsDivisionNode]:
        """Iterate :meth:`divisions` across pages. Every page is charged: set a guard."""

        def fetch(params: dict[str, Any]) -> Any:
            response = self._client.raw_request(
                "GET", "/api/v1/us/statutes/divisions", params=params, charged=True
            )
            return response.json()

        return SyncPaginator(
            fetch,
            style=CursorStyle(),
            items_key="divisions",
            params=wire({"corpus_type": corpus_type, **filters}),
            max_pages=max_pages,
            max_items=max_items,
            parse=UsDivisionNode.model_validate,
        )

    def section_changes(
        self,
        act_id: str,
        *,
        limit: int | None = None,
        since_id: int | None = None,
        before_id: int | None = None,
        change_kind: Sequence[str] | None = None,
        order: str | None = None,
        **options: Unpack[RequestOptions],
    ) -> StatuteChangesResponse:
        """Observed changes to a section. Charged, 1 credit.

        Args:
            act_id: The section id.
            limit: Changes per page, 1 to 200 (server default 50).
            since_id: Only changes with a larger id (use with ``order="asc"``).
            before_id: Only changes with a smaller id (walk back through history).
            change_kind: Only these kinds of change.
            order: ``"desc"`` (default, newest first) or ``"asc"``.
        """
        params = {
            "limit": limit,
            "sinceId": since_id,
            "beforeId": before_id,
            "changeKind": change_kind,
            "order": order,
        }
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/changes",
            cast_to=StatuteChangesResponse,
            params=params,
            charged=True,
            **options,
        )

    def iter_section_changes(
        self,
        act_id: str,
        *,
        limit: int = 50,
        change_kind: Sequence[str] | None = None,
        order: str = "desc",
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> SyncPaginator[StatuteChangeEvent]:
        """Iterate a section's changes across pages. Every page is charged: set a guard."""

        def fetch(params: dict[str, Any]) -> Any:
            response = self._client.raw_request(
                "GET",
                f"/api/v1/us/statutes/section/{seg(act_id)}/changes",
                params=params,
                charged=True,
            )
            return response.json()

        return SyncPaginator(
            fetch,
            style=HasMoreId("sinceId" if order == "asc" else "beforeId"),
            items_key="changes",
            params=wire({"limit": limit, "change_kind": change_kind, "order": order}),
            max_pages=max_pages,
            max_items=max_items,
            parse=StatuteChangeEvent.model_validate,
        )

    def enactments(
        self, act_id: str, **options: Unpack[RequestOptions]
    ) -> SectionEnactmentsResponse:
        """The session laws that enacted or amended a section. Charged (see docs/OPERATIONS.md)."""
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/enactments",
            cast_to=SectionEnactmentsResponse,
            charged=True,
            **options,
        )

    def section_rulemaking(
        self, act_id: str, **options: Unpack[RequestOptions]
    ) -> SectionRulemakingResponse:
        """Federal Register documents behind one CFR section. Charged (see docs/OPERATIONS.md)."""
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/rulemaking",
            cast_to=SectionRulemakingResponse,
            charged=True,
            **options,
        )

    def part_rulemaking(
        self,
        title: int,
        part: str,
        *,
        years: int | None = None,
        **options: Unpack[RequestOptions],
    ) -> PartRulemakingResponse:
        """Every Federal Register document for a CFR part. Charged (see docs/OPERATIONS.md)."""
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/part/{title}/{seg(part)}/rulemaking",
            cast_to=PartRulemakingResponse,
            params={"years": years},
            charged=True,
            **options,
        )

    def cited_by(
        self, act_id: str, *, limit: int | None = None, **options: Unpack[RequestOptions]
    ) -> StatuteCitedByResponse:
        """Sections that cite this one. Charged, 2 credits.

        Args:
            act_id: The section id.
            limit: Sections to return, 1 to 100 (server default 25).
        """
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/cited-by",
            cast_to=StatuteCitedByResponse,
            params={"limit": limit},
            charged=True,
            **options,
        )

    def definitions(
        self, act_id: str, **options: Unpack[RequestOptions]
    ) -> StatuteDefinitionsResponse:
        """Terms a section defines or uses. Charged, 4 credits."""
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/definitions",
            cast_to=StatuteDefinitionsResponse,
            charged=True,
            **options,
        )

    def cross_state(
        self, act_id: str, *, limit: int | None = None, **options: Unpack[RequestOptions]
    ) -> StatuteCrossStateResponse:
        """Comparable sections in other states. Charged, 6 credits.

        Args:
            act_id: The section id.
            limit: States to return, 1 to 25 (server default 5).
        """
        return self._client.request(
            "GET",
            f"/api/v1/us/statutes/section/{seg(act_id)}/cross-state",
            cast_to=StatuteCrossStateResponse,
            params={"limit": limit},
            charged=True,
            **options,
        )

    def extract_citations(
        self,
        text: str,
        *,
        state: str | None = None,
        resolve: bool | None = None,
        include_unresolved: bool | None = None,
        **options: Unpack[RequestOptions],
    ) -> ExtractCitationsResponse:
        """Find the citations in a document and resolve them. Charged, 2 credits per distinct one.

        With ``resolve=False`` it only extracts the citations and costs 0 credits.

        Args:
            text: The document text.
            state: Jurisdiction hint for bare citations.
            resolve: Resolve each citation (default true); false only extracts and costs nothing.
            include_unresolved: Keep citations that did not resolve in the answer.
        """
        body = {
            "text": text,
            "state": state,
            "resolve": resolve,
            "includeUnresolved": include_unresolved,
        }
        return self._client.request(
            "POST",
            "/api/v1/us/statutes/extract-citations",
            cast_to=ExtractCitationsResponse,
            json=compact(body),
            charged=True,
            **options,
        )
