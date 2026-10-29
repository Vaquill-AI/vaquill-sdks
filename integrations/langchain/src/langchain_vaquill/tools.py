"""LangChain tools over the Vaquill Data API (US primary law).

Every tool wraps one SDK method. Sync and async share one definition: the SDK's sync and async
resources have identical signatures, so ``_call`` returns a result or an awaitable depending on
the client it is handed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Literal

from langchain_core.tools import BaseTool, ToolException
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._client import ClientProvider
from ._errors import to_tool_exception
from ._format import dump, project_statutes, prune, render, section_text

__all__ = [
    "READ_ONLY_TOOLS",
    "WATCH_WRITE_TOOLS",
    "VaquillTool",
    "all_tool_classes",
]

_IGNORED = {"run_manager", "config", "callbacks"}


def _validation_message(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(p) for p in item.get("loc", ())) or "input"
        parts.append(f"{where}: {item.get('msg', 'invalid')}")
    return "Invalid arguments. " + "; ".join(parts) + ". Fix them and call the tool again."


class VaquillTool(BaseTool):
    """Base class: a tool bound to a :class:`ClientProvider` and one SDK method."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: ClientProvider | None = Field(default=None, exclude=True, repr=False)
    handle_tool_error: bool | str | Callable[[ToolException], str] | None = True  # pyright: ignore[reportIncompatibleVariableOverride]
    handle_validation_error: bool | str | Callable[[ValidationError], str] | None = (  # pyright: ignore[reportIncompatibleVariableOverride]
        _validation_message
    )
    max_output_chars: int = 30000

    # (namespace, method) on the SDK client, for example ("statutes", "search").
    sdk: ClassVar[tuple[str, str]]
    #: Does a call spend credits (some, like extract_citations, only when asked to resolve).
    charged: ClassVar[bool] = True
    #: Tools that change account state. Never in the default selection.
    mutating: ClassVar[bool] = False
    #: Arguments handled here, never sent to the SDK.
    local_args: ClassVar[frozenset[str]] = frozenset()

    # -- hooks ----------------------------------------------------------------------------

    def _prepare(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Defaults applied to the SDK arguments."""
        return kwargs

    def _present(self, result: Any, local: dict[str, Any]) -> Any:
        """The value to render for the model."""
        return project_statutes(prune(dump(result)))

    # -- machinery ------------------------------------------------------------------------

    def _provider(self) -> ClientProvider:
        if self.provider is None:
            raise ToolException(
                "This tool has no Vaquill client. Build tools with VaquillToolkit(...).get_tools()."
            )
        return self.provider

    def _split(self, kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        clean = {k: v for k, v in kwargs.items() if k not in _IGNORED and v is not None}
        local = {k: clean.pop(k) for k in list(clean) if k in self.local_args}
        return self._prepare(clean), local

    def _call(self, client: Any, sdk_kwargs: dict[str, Any]) -> Any:
        namespace, method = self.sdk
        return getattr(getattr(client, namespace), method)(**sdk_kwargs)

    def _out(self, result: Any, local: dict[str, Any]) -> str:
        return render(self._present(result, local), self.max_output_chars)

    def _run(self, *args: Any, **kwargs: Any) -> str:
        sdk_kwargs, local = self._split(kwargs)
        try:
            result = self._call(self._provider().sync_client, sdk_kwargs)
        except ToolException:
            raise
        except Exception as exc:
            raise to_tool_exception(exc) from None
        return self._out(result, local)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        sdk_kwargs, local = self._split(kwargs)
        try:
            result = await self._provider().acall(lambda c: self._call(c, sdk_kwargs))
        except ToolException:
            raise
        except Exception as exc:
            raise to_tool_exception(exc) from None
        return self._out(result, local)


# ---------------------------------------------------------------------------------------
# Argument schemas
# ---------------------------------------------------------------------------------------

_ACT_ID = Field(
    description="The section id (actId) from a search or resolve result, for example "
    "'USC_T42_C21_S1983'. Not a citation string."
)
_STATE = Field(
    default=None,
    description="Lowercase jurisdiction code: 'federal' or a state such as 'ca', 'tx', 'ny'.",
)
_MATCH = Literal["any", "all", "phrase", "boolean"]


class SearchStatutesInput(BaseModel):
    query: str = Field(description="What to look for: a question, keywords, or a citation.")
    state: str | None = _STATE
    corpus_type: list[str] | None = Field(
        default=None,
        description="Restrict to corpora, for example ['STATE'], ['USC'], ['CFR'], ['CONSTITUTION'].",
    )
    act_status: str | None = Field(
        default=None, description="Only this status, for example 'in_force'."
    )
    exclude_repealed: bool | None = Field(default=None, description="Leave out repealed sections.")
    code: list[str] | None = Field(default=None, description="Restrict to these state codes.")
    title_number: int | None = Field(default=None, description="USC or CFR title number.")
    match_type: _MATCH | None = Field(
        default=None,
        description="'any' (default ranking), 'all', 'phrase', or 'boolean' for AND/OR/NOT queries.",
    )
    limit: int | None = Field(default=None, ge=1, le=25, description="Rows to return (default 5).")
    offset: int | None = Field(default=None, ge=0, le=10000, description="Rows to skip.")
    include_body: bool | None = Field(
        default=None,
        description="Return full section text in each row. EXPENSIVE: adds 6 credits per row "
        "that has text. Leave false and use vaquill_get_statute_text for the one section you need.",
    )


class ActIdInput(BaseModel):
    act_id: str = _ACT_ID


class ActIdLimitInput(BaseModel):
    act_id: str = _ACT_ID
    limit: int | None = Field(default=None, ge=1, le=100, description="Rows to return.")


class SectionTextInput(BaseModel):
    act_id: str = _ACT_ID
    pinpoint: str | None = Field(
        default=None, description="A subsection to return, such as '(a)(1)'."
    )
    as_of: str | None = Field(
        default=None, description="Read the section as it stood on this date (YYYY-MM-DD)."
    )
    max_chars: int = Field(
        default=12000,
        ge=500,
        le=100000,
        description="Cut the returned text to this many characters.",
    )


class ResolveInput(BaseModel):
    cite: str = Field(
        description="One citation, for example '42 U.S.C. 1983' or 'Cal. Penal Code 187'."
    )
    state: str | None = Field(default=None, description="Jurisdiction hint for a bare citation.")
    corpus_type: str | None = Field(default=None, description="Corpus hint, for example 'STATE'.")


class ResolveBatchInput(BaseModel):
    citations: list[str] = Field(
        min_length=1,
        max_length=50,
        description="Citations to resolve, at most 50 per call.",
    )
    state: str | None = Field(default=None, description="Jurisdiction hint for bare citations.")
    corpus_type: str | None = Field(default=None, description="Corpus hint.")


class ExtractCitationsInput(BaseModel):
    text: str = Field(description="Document text to scan for legal citations.")
    state: str | None = Field(default=None, description="Jurisdiction hint for bare citations.")
    resolve: bool = Field(
        default=False,
        description="False (default) only finds citation strings and is FREE. True also resolves "
        "each distinct citation to a section and costs 2 credits per distinct citation.",
    )
    include_unresolved: bool | None = Field(
        default=None, description="With resolve=true, keep citations that did not resolve."
    )


class CountInput(BaseModel):
    query: str | None = Field(default=None, description="Optional text or boolean expression.")
    state: str | None = _STATE
    corpus_type: list[str] | None = Field(default=None, description="Corpora to count in.")
    act_status: str | None = Field(default=None, description="Only this status.")
    code: list[str] | None = Field(default=None, description="State code(s).")
    chapter: list[str] | None = Field(default=None, description="Chapter(s).")
    part: list[str] | None = Field(default=None, description="Part(s).")
    article: list[str] | None = Field(default=None, description="Article(s).")
    title_number: int | None = Field(default=None, description="USC or CFR title number.")
    exclude_repealed: bool | None = Field(default=None, description="Leave out repealed sections.")
    match_type: _MATCH | None = Field(default=None, description="How the query is matched.")


class DivisionsInput(BaseModel):
    corpus_type: str = Field(
        description="The corpus to browse, for example 'STATE', 'USC', 'CFR', 'CONSTITUTION'."
    )
    state: str | None = _STATE
    title_number: int | None = Field(default=None, description="USC or CFR title.")
    code: str | None = Field(default=None, description="State code name to descend into.")
    chapter: str | None = Field(default=None, description="Descend into this chapter.")
    part: str | None = Field(default=None, description="Descend into this part.")
    article: str | None = Field(default=None, description="Descend into this article.")
    subchapter: str | None = Field(default=None, description="Descend into this subchapter.")
    exclude_repealed: bool | None = Field(default=None, description="Leave out repealed divisions.")
    cursor: str | None = Field(default=None, description="nextCursor from the previous page.")


class SectionChangesInput(BaseModel):
    act_id: str = _ACT_ID
    limit: int | None = Field(default=None, ge=1, le=200, description="Changes per page.")
    before_id: int | None = Field(
        default=None, description="Only changes with a smaller id (walk back through history)."
    )
    change_kind: list[str] | None = Field(default=None, description="Only these kinds of change.")
    order: Literal["asc", "desc"] | None = Field(default=None, description="Default 'desc'.")


class SessionLawSearchInput(BaseModel):
    query: str = Field(description="Topic or wording to find in enacted session laws (acts).")
    jurisdiction: str | None = Field(default=None, description="Lowercase state code.")
    session: str | None = Field(default=None, description="Legislative session label.")
    instrument_type: list[str] | None = Field(
        default=None, description="Only these types, for example ['act']."
    )
    approved_from: str | None = Field(
        default=None, description="Earliest approval date, YYYY-MM-DD."
    )
    approved_to: str | None = Field(default=None, description="Latest approval date, YYYY-MM-DD.")
    limit: int | None = Field(default=None, ge=1, le=25, description="Rows to return (default 5).")
    offset: int | None = Field(default=None, ge=0, le=59, description="Rows to skip.")


class SessionLawInput(BaseModel):
    session_law_id: str = Field(
        description="The sessionLawId from a session-law search, or a citation such as "
        "'Act 2025-127' (a citation adds the resolve price and needs jurisdiction)."
    )
    jurisdiction: str | None = Field(
        default=None, description="Needed when a citation is passed without a state."
    )


class SessionLawTextInput(BaseModel):
    session_law_id: str = Field(description="The sessionLawId from a session-law search.")
    cursor: str | None = Field(default=None, description="nextCursor from the previous page.")
    version: int | None = Field(default=None, description="A version number of the law.")
    max_chars: int = Field(
        default=12000,
        ge=500,
        le=100000,
        description="Cut the returned text to this many characters.",
    )


class SessionLawVersionsInput(BaseModel):
    session_law_id: str = Field(description="The sessionLawId from a session-law search.")


class NoInput(BaseModel):
    """This tool takes no arguments."""


class CoverageInput(BaseModel):
    state: str | None = _STATE


class PricingInput(BaseModel):
    region: str | None = Field(default=None, description="Optional pricing region.")


class BoardsInput(BaseModel):
    corpus_type: str | None = Field(default=None, description="Only this corpus type.")
    state: str | None = _STATE
    limit: int | None = Field(default=None, ge=1, le=500, description="Page size.")


class ListWatchesInput(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=200, description="Page size.")
    offset: int | None = Field(default=None, ge=0, description="Watches to skip.")


class CreateWatchInput(BaseModel):
    corpus_type: str = Field(description="Corpus to watch; see vaquill_list_boards.")
    state: str | None = _STATE
    channel: Literal["webhook", "email", "both"] | None = Field(
        default=None, description="Delivery channel (default 'webhook')."
    )
    webhook_url: str | None = Field(
        default=None, description="HTTPS endpoint that receives events."
    )
    email_address: str | None = Field(default=None, description="Recipient for the email channel.")


class UpdateWatchInput(BaseModel):
    watch_id: str = Field(description="The watch id from vaquill_list_watches.")
    webhook_url: str | None = Field(default=None, description="New HTTPS endpoint.")
    email_address: str | None = Field(default=None, description="New email recipient.")
    is_active: bool | None = Field(default=None, description="Pause (false) or resume (true).")


class DeleteWatchInput(BaseModel):
    watch_id: str = Field(description="The watch id from vaquill_list_watches.")


# ---------------------------------------------------------------------------------------
# Statute tools
# ---------------------------------------------------------------------------------------

_PRICES = " Prices are credits; vaquill_get_pricing returns the live matrix."


class SearchStatutesTool(VaquillTool):
    name: str = "vaquill_search_statutes"
    description: str = (
        "Search US primary law (federal and state statutes, regulations, court rules, "
        "constitutions) by meaning, keywords or citation. Returns ranked sections with actId, "
        "citation, title, state, status, an excerpt, sourceUrl and dates, plus hasMore and "
        "nextOffset for paging. COSTS 4 credits per call, plus 6 per row if include_body is true. "
        "Use the returned actId with the other section tools. Search first, read text second."
        + _PRICES
    )
    args_schema: ArgsSchema | None = SearchStatutesInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "search")

    def _prepare(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        kwargs.setdefault("limit", 5)
        return kwargs


class GetStatuteSectionTool(VaquillTool):
    name: str = "vaquill_get_statute_section"
    description: str = (
        "Get one section's metadata WITHOUT its text: citation, title, hierarchy, status "
        "(in force, repealed, renumbered), source link, dates and amendment notes. Costs 2 "
        "credits. Use vaquill_get_statute_text when you need the wording." + _PRICES
    )
    args_schema: ArgsSchema | None = ActIdInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "get_section")


class GetStatuteTextTool(VaquillTool):
    name: str = "vaquill_get_statute_text"
    description: str = (
        "Get the full text of one section by actId, optionally a pinpoint subsection like "
        "'(a)(1)' or the text as of a date. Returns the text (operative text where the corpus "
        "separates it, otherwise the full body), source link and credit line. Long text is cut "
        "to max_chars and marked truncated. COSTS 6 credits (0 when the text is not held; "
        "bodyUnavailable says so)." + _PRICES
    )
    args_schema: ArgsSchema | None = SectionTextInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "get_section_body")
    local_args: ClassVar[frozenset[str]] = frozenset({"max_chars"})

    def _present(self, result: Any, local: dict[str, Any]) -> Any:
        return section_text(dump(result), int(local.get("max_chars", 12000)))


class ResolveCitationTool(VaquillTool):
    name: str = "vaquill_resolve_citation"
    description: str = (
        "Turn ONE citation string (for example '42 U.S.C. 1983', 'Tex. Penal Code 19.02') into "
        "the exact section it names. Returns resolved true/false, the section (actId, citation, "
        "status, sourceUrl) and, when it fails, a missReason and hint. COSTS 2 credits even when "
        "the citation does not resolve. Never guess an actId; resolve first." + _PRICES
    )
    args_schema: ArgsSchema | None = ResolveInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "resolve")


class ResolveCitationsTool(VaquillTool):
    name: str = "vaquill_resolve_citations"
    description: str = (
        "Resolve up to 50 citation strings in one call. Returns one result per citation, in "
        "order, each with resolved true/false and the section. COSTS about 2 credits PER "
        "citation, charged even for ones that do not resolve, so pass only citations you need."
        + _PRICES
    )
    args_schema: ArgsSchema | None = ResolveBatchInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "resolve_batch")


class ExtractCitationsTool(VaquillTool):
    name: str = "vaquill_extract_citations"
    description: str = (
        "Find the legal citations inside a block of text (a brief, a contract, an opinion). "
        "With resolve=false (the default) it only lists the citation strings and is FREE. With "
        "resolve=true it also resolves each distinct citation to a section and COSTS 2 credits "
        "per distinct citation." + _PRICES
    )
    args_schema: ArgsSchema | None = ExtractCitationsInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "extract_citations")
    charged: ClassVar[bool] = False  # free unless resolve=true

    def _prepare(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        # The server default is resolve=true (paid). The tool default is the free mode.
        kwargs.setdefault("resolve", False)
        return kwargs


class CountSectionsTool(VaquillTool):
    name: str = "vaquill_count_sections"
    description: str = (
        "Count how many sections exist in a scope (a state, code, chapter, title) or match a "
        "query. Returns the count and whether it is exact. Costs 1 credit. Use it to size a "
        "question before paying for searches." + _PRICES
    )
    args_schema: ArgsSchema | None = CountInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "count")


class ListDivisionsTool(VaquillTool):
    name: str = "vaquill_list_divisions"
    description: str = (
        "Browse one level of the legal hierarchy (titles, chapters, parts, articles) of a "
        "corpus, to see how a code is organised. Returns the child divisions with names, counts "
        "and a nextCursor for more. Costs 1 credit per page." + _PRICES
    )
    args_schema: ArgsSchema | None = DivisionsInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "divisions")


class SectionChangesTool(VaquillTool):
    name: str = "vaquill_section_changes"
    description: str = (
        "List the observed changes to one section over time (amendments, repeals, renumbering), "
        "newest first. Returns change events with ids and kinds; page back with before_id. "
        "Costs 1 credit per page." + _PRICES
    )
    args_schema: ArgsSchema | None = SectionChangesInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "section_changes")


class SectionCitedByTool(VaquillTool):
    name: str = "vaquill_section_cited_by"
    description: str = (
        "List the sections that cite a given section (what depends on it). Returns the citing "
        "sections with actId and citation, a total and a truncated flag. Costs 2 credits." + _PRICES
    )
    args_schema: ArgsSchema | None = ActIdLimitInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "cited_by")


class SectionDefinitionsTool(VaquillTool):
    name: str = "vaquill_section_definitions"
    description: str = (
        "List the terms a section defines or relies on, with where each definition lives. "
        "Costs 4 credits." + _PRICES
    )
    args_schema: ArgsSchema | None = ActIdInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "definitions")


class SectionNeighborsTool(VaquillTool):
    name: str = "vaquill_section_neighbors"
    description: str = (
        "Get the sections next to and related to a given section, plus its container (the "
        "chapter or part it sits in). Costs 2 credits." + _PRICES
    )
    args_schema: ArgsSchema | None = ActIdLimitInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "neighbors")


class StatutesCoverageTool(VaquillTool):
    name: str = "vaquill_statutes_coverage"
    description: str = (
        "Show what the corpus holds per state and corpus type (counts and freshness). FREE. "
        "Use it to check whether a jurisdiction is covered before searching."
    )
    args_schema: ArgsSchema | None = CoverageInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "coverage")
    charged: ClassVar[bool] = False


# ---------------------------------------------------------------------------------------
# Session laws
# ---------------------------------------------------------------------------------------


class SearchSessionLawsTool(VaquillTool):
    name: str = "vaquill_search_session_laws"
    description: str = (
        "Search session laws (acts as enacted, before codification) by topic or wording. "
        "Returns acts with sessionLawId, citation, title, session, approval date and a passage. "
        "COSTS 4 credits per page." + _PRICES
    )
    args_schema: ArgsSchema | None = SessionLawSearchInput
    sdk: ClassVar[tuple[str, str]] = ("session_laws", "search")

    def _prepare(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        kwargs.setdefault("limit", 5)
        return kwargs


class GetSessionLawTool(VaquillTool):
    name: str = "vaquill_get_session_law"
    description: str = (
        "Get one session law's record WITHOUT its text: citation, title, session, dates, "
        "enactment outcome, code sections affected and source. Costs 2 credits (more if you pass "
        "a citation to resolve). Use vaquill_get_session_law_text for the wording." + _PRICES
    )
    args_schema: ArgsSchema | None = SessionLawInput
    sdk: ClassVar[tuple[str, str]] = ("session_laws", "get")


class GetSessionLawTextTool(VaquillTool):
    name: str = "vaquill_get_session_law_text"
    description: str = (
        "Get one PAGE of a session law's text. Returns the text, hasMore and nextCursor; pass "
        "nextCursor back as cursor for the next page. COSTS 6 credits PER PAGE, so read only "
        "what you need." + _PRICES
    )
    args_schema: ArgsSchema | None = SessionLawTextInput
    sdk: ClassVar[tuple[str, str]] = ("session_laws", "get_body")
    local_args: ClassVar[frozenset[str]] = frozenset({"max_chars"})

    def _present(self, result: Any, local: dict[str, Any]) -> Any:
        data = prune(dump(result))
        limit = int(local.get("max_chars", 12000))
        for key in ("text", "body", "content", "plain"):
            value = data.get(key)
            if isinstance(value, str) and len(value) > limit:
                data[key] = value[:limit]
                data["truncated"] = True
        return data


class SectionCrossStateTool(VaquillTool):
    name: str = "vaquill_section_cross_state"
    description: str = (
        "Find comparable sections in OTHER states for a given state section (how do other "
        "states treat the same subject). Returns matching sections per state. COSTS 6 credits."
        + _PRICES
    )
    args_schema: ArgsSchema | None = ActIdLimitInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "cross_state")


class SectionEnactmentsTool(VaquillTool):
    name: str = "vaquill_section_enactments"
    description: str = (
        "List the session laws (acts as enacted) that enacted or amended a section, to trace "
        "where its current wording came from. Charged; vaquill_get_pricing has the price."
    )
    args_schema: ArgsSchema | None = ActIdInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "enactments")


class SectionRulemakingTool(VaquillTool):
    name: str = "vaquill_section_rulemaking"
    description: str = (
        "For a CFR (federal regulation) section, list the Federal Register documents behind "
        "it: proposals, final rules and amendments. Only meaningful for CFR actIds. Charged; "
        "vaquill_get_pricing has the price."
    )
    args_schema: ArgsSchema | None = ActIdInput
    sdk: ClassVar[tuple[str, str]] = ("statutes", "section_rulemaking")


class SessionLawVersionsTool(VaquillTool):
    name: str = "vaquill_session_law_versions"
    description: str = (
        "List every version of a session law (original and corrected texts) so you can pass a "
        "version number to vaquill_get_session_law_text. Costs 1 credit." + _PRICES
    )
    args_schema: ArgsSchema | None = SessionLawVersionsInput
    sdk: ClassVar[tuple[str, str]] = ("session_laws", "versions")


# ---------------------------------------------------------------------------------------
# Account and free reference
# ---------------------------------------------------------------------------------------


class CreditBalanceTool(VaquillTool):
    name: str = "vaquill_credit_balance"
    description: str = (
        "Read the credits this API key can still spend, with the plan and the next expiry. "
        "FREE. Call it before an expensive plan of searches."
    )
    args_schema: ArgsSchema | None = NoInput
    sdk: ClassVar[tuple[str, str]] = ("credits", "balance")
    charged: ClassVar[bool] = False


class GetPricingTool(VaquillTool):
    name: str = "vaquill_get_pricing"
    description: str = "Get the live credit price of every Vaquill operation. FREE."
    args_schema: ArgsSchema | None = PricingInput
    sdk: ClassVar[tuple[str, str]] = ("pricing", "get")
    charged: ClassVar[bool] = False


class ListBoardsTool(VaquillTool):
    name: str = "vaquill_list_boards"
    description: str = (
        "List the legal sources that can be watched for changes, with last retrieval time and "
        "cadence. FREE."
    )
    args_schema: ArgsSchema | None = BoardsInput
    sdk: ClassVar[tuple[str, str]] = ("boards", "list")
    charged: ClassVar[bool] = False


class ListWatchesTool(VaquillTool):
    name: str = "vaquill_list_watches"
    description: str = "List the law-change watches on this account. FREE. Read only."
    args_schema: ArgsSchema | None = ListWatchesInput
    sdk: ClassVar[tuple[str, str]] = ("watches", "list")
    charged: ClassVar[bool] = False


# ---------------------------------------------------------------------------------------
# Watch writes (opt-in)
# ---------------------------------------------------------------------------------------


class CreateWatchTool(VaquillTool):
    name: str = "vaquill_create_watch"
    description: str = (
        "CREATES a law-change watch that sends a webhook or email when a corpus source "
        "changes. Free, but it changes the account and starts outbound deliveries to the given "
        "URL or address. Only call it when the user asked for it."
    )
    args_schema: ArgsSchema | None = CreateWatchInput
    sdk: ClassVar[tuple[str, str]] = ("watches", "create")
    charged: ClassVar[bool] = False
    mutating: ClassVar[bool] = True


class UpdateWatchTool(VaquillTool):
    name: str = "vaquill_update_watch"
    description: str = (
        "CHANGES an existing watch (destination or paused/active). Free. Only call it when the "
        "user asked for it."
    )
    args_schema: ArgsSchema | None = UpdateWatchInput
    sdk: ClassVar[tuple[str, str]] = ("watches", "update")
    charged: ClassVar[bool] = False
    mutating: ClassVar[bool] = True


class DeleteWatchTool(VaquillTool):
    name: str = "vaquill_delete_watch"
    description: str = (
        "PERMANENTLY DELETES a watch. Cannot be undone. Free. Only call it when the user "
        "explicitly asked to delete that watch."
    )
    args_schema: ArgsSchema | None = DeleteWatchInput
    sdk: ClassVar[tuple[str, str]] = ("watches", "delete")
    charged: ClassVar[bool] = False
    mutating: ClassVar[bool] = True

    def _present(self, result: Any, local: dict[str, Any]) -> Any:
        return {"deleted": True}


READ_ONLY_TOOLS: tuple[type[VaquillTool], ...] = (
    SearchStatutesTool,
    GetStatuteSectionTool,
    GetStatuteTextTool,
    ResolveCitationTool,
    ResolveCitationsTool,
    ExtractCitationsTool,
    CountSectionsTool,
    ListDivisionsTool,
    SectionChangesTool,
    SectionCitedByTool,
    SectionDefinitionsTool,
    SectionNeighborsTool,
    SectionCrossStateTool,
    SectionEnactmentsTool,
    SectionRulemakingTool,
    StatutesCoverageTool,
    SearchSessionLawsTool,
    GetSessionLawTool,
    GetSessionLawTextTool,
    SessionLawVersionsTool,
    CreditBalanceTool,
    GetPricingTool,
    ListBoardsTool,
    ListWatchesTool,
)
WATCH_WRITE_TOOLS: tuple[type[VaquillTool], ...] = (
    CreateWatchTool,
    UpdateWatchTool,
    DeleteWatchTool,
)


def all_tool_classes() -> tuple[type[VaquillTool], ...]:
    return READ_ONLY_TOOLS + WATCH_WRITE_TOOLS


def tool_name(cls: type[VaquillTool]) -> str:
    return str(cls.model_fields["name"].default)
