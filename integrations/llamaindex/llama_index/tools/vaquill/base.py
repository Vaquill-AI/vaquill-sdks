"""Vaquill US primary-law tools for LlamaIndex agents."""

import json
from typing import Any, Callable, List, Optional, Tuple, Union

from llama_index.core.tools.tool_spec.base import BaseToolSpec
from llama_index.tools.vaquill._core import VaquillConnection
from llama_index.tools.vaquill._errors import VaquillToolError, describe_error
from llama_index.tools.vaquill._render import render, to_data
from vaquill import AsyncVaquill, Vaquill

__all__ = ["SEARCH_RESULT_FIELDS", "VaquillToolSpec"]

StrOrList = Union[str, List[str]]

# Search rows carry about 170 optional fields. These are the ones a model can use.
SEARCH_RESULT_FIELDS = (
    "actId",
    "citation",
    "citationShort",
    "displayLabel",
    "sectionTitle",
    "title",
    "state",
    "corpusType",
    "actStatus",
    "effectiveDate",
    "lastAmendedDate",
    "currentThrough",
    "sourceUrl",
    "relevanceScore",
    "excerpt",
    "body",
    "bodyUnavailable",
    "breadcrumb",
)

_READ_FUNCTIONS: List[Tuple[str, str]] = [
    ("search_statutes", "search_statutes_async"),
    ("get_section", "get_section_async"),
    ("resolve_citation", "resolve_citation_async"),
    ("resolve_citations", "resolve_citations_async"),
    ("extract_citations", "extract_citations_async"),
    ("count_sections", "count_sections_async"),
    ("list_divisions", "list_divisions_async"),
    ("get_section_changes", "get_section_changes_async"),
    ("get_cited_by", "get_cited_by_async"),
    ("get_definitions", "get_definitions_async"),
    ("get_neighbors", "get_neighbors_async"),
    ("search_session_laws", "search_session_laws_async"),
    ("get_session_law", "get_session_law_async"),
    ("get_credit_balance", "get_credit_balance_async"),
]
_WATCH_FUNCTIONS: List[Tuple[str, str]] = [
    ("create_watch", "create_watch_async"),
    ("update_watch", "update_watch_async"),
    ("delete_watch", "delete_watch_async"),
]

_Request = Callable[[Any], Any]
_Shape = Callable[[Any], str]


class VaquillToolSpec(BaseToolSpec):
    """Tools that search and read US primary law (statutes, regulations, court rules,
    constitutions, session laws) through the Vaquill Data API.

    Read-only by default. Most tools spend credits; each docstring states the price so the
    agent can reason about cost. Set ``max_credits`` to stop all spending at a hard cap.

    Args:
        api_key: ``vq_key_...``. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        client: A pre-built ``vaquill.Vaquill`` (proxies, test doubles). Optional.
        async_client: A pre-built ``vaquill.AsyncVaquill``. Without it, async calls use
            ``client`` in a thread, or a client built from the key.
        base_url: Overrides ``VAQUILL_BASE_URL`` and ``https://api.vaquill.ai``.
        max_credits: Hard spend cap across sync and async calls. None means no cap.
        enable_watch_management: Also expose create_watch, update_watch and delete_watch.
            Off by default because they change account state.
        raise_on_error: Raise :class:`VaquillToolError` instead of returning an error string.
        max_chars: Longest text field returned to the model; longer text is cut with a marker.
        timeout: Request timeout in seconds for clients built here.
        max_retries: Retries for clients built here.
        user_agent_suffix: Extra token appended to the integration User-Agent.
    """

    spec_functions: List[Union[str, Tuple[str, str]]] = list(_READ_FUNCTIONS)

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[Vaquill] = None,
        async_client: Optional[AsyncVaquill] = None,
        base_url: Optional[str] = None,
        max_credits: Optional[float] = None,
        enable_watch_management: bool = False,
        raise_on_error: bool = False,
        max_chars: int = 12000,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        user_agent_suffix: Optional[str] = None,
    ) -> None:
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
        self.enable_watch_management = enable_watch_management
        self.raise_on_error = raise_on_error
        self.max_chars = max_chars
        functions = list(_READ_FUNCTIONS)
        if enable_watch_management:
            functions.extend(_WATCH_FUNCTIONS)
        self.spec_functions = list(functions)

    # ------------------------------------------------------------------ plumbing

    @property
    def credits_spent(self) -> float:
        """Credits consumed through this tool spec so far."""
        return self._conn.credits_spent

    def _fail(self, exc: BaseException) -> str:
        message = describe_error(exc, self._conn.secrets)
        if self.raise_on_error:
            raise VaquillToolError(message) from None
        return message

    def _run(self, request: _Request, shape: _Shape) -> str:
        try:
            return shape(self._conn.call(request))
        except Exception as exc:
            return self._fail(exc)

    async def _arun(self, request: _Request, shape: _Shape) -> str:
        try:
            return shape(await self._conn.acall(request))
        except Exception as exc:
            return self._fail(exc)

    def _plain(self, **options: Any) -> _Shape:
        return lambda result: render(result, max_chars=self.max_chars, **options)

    def _watch_gate(self) -> Optional[str]:
        if self.enable_watch_management:
            return None
        message = (
            "Vaquill error: watch management is disabled. "
            "Build VaquillToolSpec(enable_watch_management=True) to allow it."
        )
        if self.raise_on_error:
            raise VaquillToolError(message)
        return message

    # ------------------------------------------------------------------ builders
    # Each builder returns (request, shape) so the sync and async tool share one definition.

    def _b_search(
        self,
        query: str,
        state: Optional[str],
        corpus_type: Optional[StrOrList],
        limit: int,
        include_body: bool,
        act_status: Optional[str],
        title_number: Optional[int],
        match_type: Optional[str],
        exclude_repealed: Optional[bool],
        offset: Optional[int],
    ) -> Tuple[_Request, _Shape]:
        def request(c: Any) -> Any:
            return c.statutes.search(
                query,
                state=state,
                corpus_type=corpus_type,
                limit=limit,
                include_body=include_body or None,
                act_status=act_status,
                title_number=title_number,
                match_type=match_type,
                exclude_repealed=exclude_repealed,
                offset=offset,
            )

        return request, self._plain(list_key="results", keep=SEARCH_RESULT_FIELDS)

    def _b_section(
        self,
        act_id: str,
        include_body: bool,
        pinpoint: Optional[str],
        as_of: Optional[str],
        format: Optional[str],
    ) -> Tuple[_Request, _Shape]:
        if not include_body:
            return (lambda c: c.statutes.get_section(act_id)), self._plain()

        def request(c: Any) -> Any:
            return c.statutes.get_section_body(act_id, format=format, pinpoint=pinpoint, as_of=as_of)

        def shape(result: Any) -> str:
            data = to_data(result)
            text = data.get("content") or data.get("plain") or data.get("markdown") or data.get("html")
            for duplicate in ("content", "plain", "markdown", "html"):
                data.pop(duplicate, None)
            if text:
                data["text"] = text
            return render(data, max_chars=self.max_chars)

        return request, shape

    # ------------------------------------------------------------------ statutes

    def search_statutes(
        self,
        query: str,
        state: Optional[str] = None,
        corpus_type: Optional[StrOrList] = None,
        limit: int = 5,
        include_body: bool = False,
        act_status: Optional[str] = None,
        title_number: Optional[int] = None,
        match_type: Optional[str] = None,
        exclude_repealed: Optional[bool] = None,
        offset: Optional[int] = None,
    ) -> str:
        """Search US primary law (statutes, regulations, court rules, constitutions) by topic,
        wording or citation. Use this first when you do not yet know the section id.

        Costs 4 credits per call, plus the text price for every row when include_body is true.
        Keep include_body false to get a short excerpt per hit, then call get_section for the
        one you need. Returns JSON with `results` (actId, citation, sectionTitle, state,
        corpusType, actStatus, effectiveDate, sourceUrl, excerpt) and `creditsConsumed`.

        Args:
            query: Plain words, a citation such as "42 U.S.C. 1983", or a boolean expression
                when match_type is "boolean".
            state: Lowercase jurisdiction code: "federal", "ca", "ny", "tx" and so on.
            corpus_type: Narrow to one corpus type or a list, for example "STATE" or "REGULATION".
            limit: Hits to return, 1 to 50. Default 5; each extra body costs more.
            include_body: Return the full section text in each hit (costs extra credits).
            act_status: Only this status, for example "in_force".
            title_number: Only this USC or CFR title number.
            match_type: "any", "all", "phrase" or "boolean".
            exclude_repealed: Leave out repealed sections.
            offset: Hits to skip, for the next page.
        """
        request, shape = self._b_search(
            query,
            state,
            corpus_type,
            limit,
            include_body,
            act_status,
            title_number,
            match_type,
            exclude_repealed,
            offset,
        )
        return self._run(request, shape)

    async def search_statutes_async(
        self,
        query: str,
        state: Optional[str] = None,
        corpus_type: Optional[StrOrList] = None,
        limit: int = 5,
        include_body: bool = False,
        act_status: Optional[str] = None,
        title_number: Optional[int] = None,
        match_type: Optional[str] = None,
        exclude_repealed: Optional[bool] = None,
        offset: Optional[int] = None,
    ) -> str:
        """Async version of search_statutes."""
        request, shape = self._b_search(
            query,
            state,
            corpus_type,
            limit,
            include_body,
            act_status,
            title_number,
            match_type,
            exclude_repealed,
            offset,
        )
        return await self._arun(request, shape)

    def get_section(
        self,
        act_id: str,
        include_body: bool = False,
        pinpoint: Optional[str] = None,
        as_of: Optional[str] = None,
        format: Optional[str] = None,
    ) -> str:
        """Fetch one section by its actId (from search_statutes or resolve_citation).

        Without include_body this returns metadata only (citation, title, status, dates,
        sourceUrl) and costs 2 credits. With include_body=true it returns the section text
        instead, costs 6 credits (0 when Vaquill does not hold the text) and can be long.
        Check `bodyUnavailable` and `note` in the answer when the text is missing.

        Args:
            act_id: The section id, for example "USC_T42_S1983".
            include_body: Return the text instead of the metadata.
            pinpoint: Only this subsection, for example "(a)(1)". Needs include_body.
            as_of: Read the text as it stood on this date (YYYY-MM-DD). Needs include_body.
            format: Text format: "plain", "markdown" or "html". Needs include_body.
        """
        request, shape = self._b_section(act_id, include_body, pinpoint, as_of, format)
        return self._run(request, shape)

    async def get_section_async(
        self,
        act_id: str,
        include_body: bool = False,
        pinpoint: Optional[str] = None,
        as_of: Optional[str] = None,
        format: Optional[str] = None,
    ) -> str:
        """Async version of get_section."""
        request, shape = self._b_section(act_id, include_body, pinpoint, as_of, format)
        return await self._arun(request, shape)

    def resolve_citation(self, cite: str, state: Optional[str] = None, corpus_type: Optional[str] = None) -> str:
        """Turn one legal citation into the exact section record. Costs 2 credits, even when
        the citation does not resolve.

        Returns JSON with the matched section (actId, citation, sourceUrl), `matchLevel`, and
        `candidates` or a `missReason` when nothing matched exactly. Use the returned actId
        with get_section.

        Args:
            cite: The citation, for example "42 U.S.C. 1983" or "Cal. Penal Code 187".
            state: Lowercase jurisdiction hint for a bare citation.
            corpus_type: Corpus hint such as "STATE" or "REGULATION".
        """
        return self._run(lambda c: c.statutes.resolve(cite, state=state, corpus_type=corpus_type), self._plain())

    async def resolve_citation_async(
        self, cite: str, state: Optional[str] = None, corpus_type: Optional[str] = None
    ) -> str:
        """Async version of resolve_citation."""
        return await self._arun(lambda c: c.statutes.resolve(cite, state=state, corpus_type=corpus_type), self._plain())

    def resolve_citations(self, citations: List[str], state: Optional[str] = None) -> str:
        """Resolve several citations in one call. Costs 2 credits per distinct citation,
        unresolved ones included, so pass only the ones you need (repeats are sent once).

        Returns JSON, one result per citation in the order given.

        Args:
            citations: Citation strings, for example ["42 U.S.C. 1983", "17 C.F.R. 240.10b-5"].
            state: Lowercase jurisdiction hint for bare citations.
        """
        return self._run(lambda c: c.statutes.resolve_batch_all(citations, state=state), self._plain())

    async def resolve_citations_async(self, citations: List[str], state: Optional[str] = None) -> str:
        """Async version of resolve_citations."""
        return await self._arun(lambda c: c.statutes.resolve_batch_all(citations, state=state), self._plain())

    def extract_citations(
        self, text: str, state: Optional[str] = None, resolve: bool = False, include_unresolved: bool = False
    ) -> str:
        """Find the legal citations inside a passage of text, and optionally resolve them.

        With resolve=false (the default here) it only extracts and costs 0 credits. With
        resolve=true it also resolves each distinct citation at 2 credits each.

        Args:
            text: The passage to scan.
            state: Lowercase jurisdiction hint for bare citations.
            resolve: Resolve each citation to a section (costs credits).
            include_unresolved: Keep citations that did not resolve in the answer.
        """
        return self._run(
            lambda c: c.statutes.extract_citations(
                text, state=state, resolve=resolve, include_unresolved=include_unresolved or None
            ),
            self._plain(),
        )

    async def extract_citations_async(
        self, text: str, state: Optional[str] = None, resolve: bool = False, include_unresolved: bool = False
    ) -> str:
        """Async version of extract_citations."""
        return await self._arun(
            lambda c: c.statutes.extract_citations(
                text, state=state, resolve=resolve, include_unresolved=include_unresolved or None
            ),
            self._plain(),
        )

    def count_sections(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        corpus_type: Optional[StrOrList] = None,
        act_status: Optional[str] = None,
        title_number: Optional[int] = None,
        exclude_repealed: Optional[bool] = None,
    ) -> str:
        """Count the sections in a scope, or matching a query, without fetching them.
        Costs 1 credit. Use it to size a topic before paging through search_statutes.

        Args:
            query: Optional search text or boolean expression.
            state: Lowercase jurisdiction code.
            corpus_type: One corpus type or a list.
            act_status: Only this status, for example "in_force".
            title_number: Only this USC or CFR title.
            exclude_repealed: Leave out repealed sections.
        """
        return self._run(
            lambda c: c.statutes.count(
                query=query,
                state=state,
                corpus_type=corpus_type,
                act_status=act_status,
                title_number=title_number,
                exclude_repealed=exclude_repealed,
            ),
            self._plain(),
        )

    async def count_sections_async(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        corpus_type: Optional[StrOrList] = None,
        act_status: Optional[str] = None,
        title_number: Optional[int] = None,
        exclude_repealed: Optional[bool] = None,
    ) -> str:
        """Async version of count_sections."""
        return await self._arun(
            lambda c: c.statutes.count(
                query=query,
                state=state,
                corpus_type=corpus_type,
                act_status=act_status,
                title_number=title_number,
                exclude_repealed=exclude_repealed,
            ),
            self._plain(),
        )

    def list_divisions(
        self,
        corpus_type: str,
        state: Optional[str] = None,
        title_number: Optional[int] = None,
        code: Optional[str] = None,
        chapter: Optional[str] = None,
        part: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Browse one level of a code's hierarchy (titles, chapters, parts, articles).
        Costs 1 credit per call. Start with only corpus_type (and state), then pass the
        chapter or part you picked to go one level deeper. Pass the returned cursor for more.

        Args:
            corpus_type: The corpus to browse, for example "STATE" or "USC".
            state: Lowercase jurisdiction code for state corpora.
            title_number: USC or CFR title.
            code: State code name.
            chapter: Descend into this chapter.
            part: Descend into this part.
            cursor: The cursor from the previous page.
        """
        return self._run(
            lambda c: c.statutes.divisions(
                corpus_type,
                state=state,
                title_number=title_number,
                code=code,
                chapter=chapter,
                part=part,
                cursor=cursor,
            ),
            self._plain(),
        )

    async def list_divisions_async(
        self,
        corpus_type: str,
        state: Optional[str] = None,
        title_number: Optional[int] = None,
        code: Optional[str] = None,
        chapter: Optional[str] = None,
        part: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Async version of list_divisions."""
        return await self._arun(
            lambda c: c.statutes.divisions(
                corpus_type,
                state=state,
                title_number=title_number,
                code=code,
                chapter=chapter,
                part=part,
                cursor=cursor,
            ),
            self._plain(),
        )

    def get_section_changes(self, act_id: str, limit: int = 10, order: Optional[str] = None) -> str:
        """List the observed changes to a section (amendments, repeals, text edits), newest
        first. Costs 1 credit per call.

        Args:
            act_id: The section id.
            limit: Changes to return, 1 to 200. Default 10.
            order: "desc" (newest first, default) or "asc".
        """
        return self._run(lambda c: c.statutes.section_changes(act_id, limit=limit, order=order), self._plain())

    async def get_section_changes_async(self, act_id: str, limit: int = 10, order: Optional[str] = None) -> str:
        """Async version of get_section_changes."""
        return await self._arun(lambda c: c.statutes.section_changes(act_id, limit=limit, order=order), self._plain())

    def get_cited_by(self, act_id: str, limit: int = 10) -> str:
        """List the sections that cite this section. Costs 2 credits per call.

        Args:
            act_id: The section id.
            limit: Sections to return, 1 to 100. Default 10.
        """
        return self._run(lambda c: c.statutes.cited_by(act_id, limit=limit), self._plain())

    async def get_cited_by_async(self, act_id: str, limit: int = 10) -> str:
        """Async version of get_cited_by."""
        return await self._arun(lambda c: c.statutes.cited_by(act_id, limit=limit), self._plain())

    def get_definitions(self, act_id: str) -> str:
        """List the terms a section defines or relies on, with their definitions. Costs 4
        credits per call.

        Args:
            act_id: The section id.
        """
        return self._run(lambda c: c.statutes.definitions(act_id), self._plain())

    async def get_definitions_async(self, act_id: str) -> str:
        """Async version of get_definitions."""
        return await self._arun(lambda c: c.statutes.definitions(act_id), self._plain())

    def get_neighbors(self, act_id: str, limit: int = 3) -> str:
        """List the sections related to or adjacent to this one. Costs 2 credits per call.

        Args:
            act_id: The section id.
            limit: Neighbours to return, 1 to 10. Default 3.
        """
        return self._run(lambda c: c.statutes.neighbors(act_id, limit=limit), self._plain())

    async def get_neighbors_async(self, act_id: str, limit: int = 3) -> str:
        """Async version of get_neighbors."""
        return await self._arun(lambda c: c.statutes.neighbors(act_id, limit=limit), self._plain())

    # ------------------------------------------------------------------ session laws

    def search_session_laws(
        self,
        query: str,
        jurisdiction: Optional[str] = None,
        session: Optional[str] = None,
        limit: int = 5,
        approved_from: Optional[str] = None,
        approved_to: Optional[str] = None,
    ) -> str:
        """Search session laws (acts as enacted by a legislature) by topic or wording.
        Costs 4 credits per page. Returns JSON with `results` (sessionLawId, citation, title,
        approvedDate, enactmentOutcome) and a matching `passage`.

        Args:
            query: Search text.
            jurisdiction: Lowercase state code.
            session: Legislative session label.
            limit: Results per page, 1 to 25. Default 5.
            approved_from: Earliest approval date (YYYY-MM-DD).
            approved_to: Latest approval date (YYYY-MM-DD).
        """
        return self._run(
            lambda c: c.session_laws.search(
                query,
                jurisdiction=jurisdiction,
                session=session,
                limit=limit,
                approved_from=approved_from,
                approved_to=approved_to,
            ),
            self._plain(),
        )

    async def search_session_laws_async(
        self,
        query: str,
        jurisdiction: Optional[str] = None,
        session: Optional[str] = None,
        limit: int = 5,
        approved_from: Optional[str] = None,
        approved_to: Optional[str] = None,
    ) -> str:
        """Async version of search_session_laws."""
        return await self._arun(
            lambda c: c.session_laws.search(
                query,
                jurisdiction=jurisdiction,
                session=session,
                limit=limit,
                approved_from=approved_from,
                approved_to=approved_to,
            ),
            self._plain(),
        )

    def get_session_law(self, session_law_id: str, jurisdiction: Optional[str] = None) -> str:
        """Fetch one session law's record (no text) by its sessionLawId. Costs 2 credits; a
        citation instead of an id adds the citation-resolve price.

        Args:
            session_law_id: The id from search_session_laws, or a citation.
            jurisdiction: Needed when a citation is passed without a state.
        """
        return self._run(lambda c: c.session_laws.get(session_law_id, jurisdiction=jurisdiction), self._plain())

    async def get_session_law_async(self, session_law_id: str, jurisdiction: Optional[str] = None) -> str:
        """Async version of get_session_law."""
        return await self._arun(lambda c: c.session_laws.get(session_law_id, jurisdiction=jurisdiction), self._plain())

    # ------------------------------------------------------------------ account

    def get_credit_balance(self) -> str:
        """Show how many credits this API key can still spend. Free. Call it before a large
        job. Returns creditsRemaining, plan and the rate limit.
        """
        return self._run(lambda c: c.credits.balance(), self._plain())

    async def get_credit_balance_async(self) -> str:
        """Async version of get_credit_balance."""
        return await self._arun(lambda c: c.credits.balance(), self._plain())

    # ------------------------------------------------------------------ watches (opt-in)

    def create_watch(
        self,
        corpus_type: str,
        state: Optional[str] = None,
        channel: Optional[str] = None,
        webhook_url: Optional[str] = None,
        email_address: Optional[str] = None,
    ) -> str:
        """Create a law-change alert on a corpus source. Free. CHANGES ACCOUNT STATE: only call
        this when the user explicitly asked for an alert. Returns the watch (id, channel).

        Args:
            corpus_type: The corpus to watch, for example "STATE".
            state: Lowercase jurisdiction code, for per-state corpora.
            channel: "webhook" (default), "email" or "both".
            webhook_url: HTTPS endpoint that receives events.
            email_address: Recipient for the email channel.
        """
        gate = self._watch_gate()
        if gate:
            return gate
        return self._run(
            lambda c: c.watches.create(
                corpus_type, state=state, channel=channel, webhook_url=webhook_url, email_address=email_address
            ),
            self._plain(),
        )

    async def create_watch_async(
        self,
        corpus_type: str,
        state: Optional[str] = None,
        channel: Optional[str] = None,
        webhook_url: Optional[str] = None,
        email_address: Optional[str] = None,
    ) -> str:
        """Async version of create_watch."""
        gate = self._watch_gate()
        if gate:
            return gate
        return await self._arun(
            lambda c: c.watches.create(
                corpus_type, state=state, channel=channel, webhook_url=webhook_url, email_address=email_address
            ),
            self._plain(),
        )

    def update_watch(
        self,
        watch_id: str,
        webhook_url: Optional[str] = None,
        email_address: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> str:
        """Change a law-change alert (endpoint, recipient, on or off). Free. CHANGES ACCOUNT
        STATE: only call this when the user asked. Only the arguments you pass are updated.

        Args:
            watch_id: The watch id.
            webhook_url: New HTTPS endpoint.
            email_address: New email recipient.
            is_active: Turn the alert on or off.
        """
        gate = self._watch_gate()
        if gate:
            return gate
        return self._run(
            lambda c: c.watches.update(
                watch_id, webhook_url=webhook_url, email_address=email_address, is_active=is_active
            ),
            self._plain(),
        )

    async def update_watch_async(
        self,
        watch_id: str,
        webhook_url: Optional[str] = None,
        email_address: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> str:
        """Async version of update_watch."""
        gate = self._watch_gate()
        if gate:
            return gate
        return await self._arun(
            lambda c: c.watches.update(
                watch_id, webhook_url=webhook_url, email_address=email_address, is_active=is_active
            ),
            self._plain(),
        )

    def delete_watch(self, watch_id: str) -> str:
        """Delete a law-change alert for good. Free. DESTRUCTIVE: only call this when the user
        asked to delete that specific watch.

        Args:
            watch_id: The watch id.
        """
        gate = self._watch_gate()
        if gate:
            return gate
        return self._run(lambda c: c.watches.delete(watch_id), lambda _r: json.dumps({"deleted": watch_id}))

    async def delete_watch_async(self, watch_id: str) -> str:
        """Async version of delete_watch."""
        gate = self._watch_gate()
        if gate:
            return gate
        return await self._arun(lambda c: c.watches.delete(watch_id), lambda _r: json.dumps({"deleted": watch_id}))

    def to_tool_list(
        self, spec_functions: Optional[List[Any]] = None, func_to_metadata_mapping: Any = None
    ) -> List[Any]:
        """Tools for an agent. Watch tools are included only when enable_watch_management is on."""
        return super().to_tool_list(spec_functions or self.spec_functions, func_to_metadata_mapping)
