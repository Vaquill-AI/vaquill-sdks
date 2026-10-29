"""Dedicated commands for the operations beyond search, resolve and section."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from .._pagination import SyncPaginator
from ._core import (
    USAGE,
    CLIError,
    Flag,
    Result,
    Session,
    add_paging,
    as_dict,
    as_list,
    declare,
    dump,
    forbid,
    generic_human,
    kw,
    more,
    more_notice,
    names,
    paging_kw,
    paging_notice,
    read_lines,
    read_text,
    wants_all,
)
from ._render import UI

Add = Callable[..., argparse.ArgumentParser]
Group = Callable[..., Any]

# Every API operation and the command that runs it (an argv prefix). Operations that a command
# does not cover must be listed in UNMAPPED with the reason; tests/test_cli_coverage.py enforces it.
OPERATION_COMMANDS: dict[str, tuple[str, ...]] = {
    "search_statutes": ("search",),
    "resolve_statute_citation": ("resolve",),
    "resolve_statute_citations_batch": ("statutes", "resolve-batch"),
    "get_section": ("section",),
    "get_section_body": ("section",),
    "get_section_neighbors": ("statutes", "neighbors"),
    "get_sections_batch": ("statutes", "sections"),
    "count_statute_sections": ("statutes", "count"),
    "list_statutes_coverage": ("coverage",),
    "list_statute_divisions": ("statutes", "divisions"),
    "get_section_changes": ("statutes", "changes"),
    "get_section_enactments": ("statutes", "enactments"),
    "get_section_rulemaking": ("statutes", "rulemaking"),
    "get_part_rulemaking": ("statutes", "part-rulemaking"),
    "get_section_cited_by": ("statutes", "cited-by"),
    "get_section_definitions": ("statutes", "definitions"),
    "get_section_cross_state": ("statutes", "cross-state"),
    "extract_statute_citations": ("statutes", "extract-citations"),
    "search_session_laws": ("session-laws", "search"),
    "list_session_laws": ("session-laws", "list"),
    "get_session_law": ("session-laws", "get"),
    "get_session_law_body": ("session-laws", "body"),
    "get_session_law_versions": ("session-laws", "versions"),
    "get_session_laws_batch": ("session-laws", "batch"),
    "get_session_law_changes": ("session-laws", "changes"),
    "list_watches": ("watches", "list"),
    "create_watch": ("watches", "create"),
    "update_watch": ("watches", "update"),
    "delete_watch": ("watches", "delete"),
    "test_watch": ("watches", "test"),
    "list_watch_changes": ("watches", "changes"),
    "get_watch_change_diff": ("watches", "diff"),
    "list_watch_deliveries": ("watches", "deliveries"),
    "list_boards": ("boards",),
    "get_credit_balance": ("credits",),
    "get_pricing": ("pricing",),
}
UNMAPPED: dict[str, str] = {}


# ---- shared helpers --------------------------------------------------------------------


def result(
    data: Any,
    *,
    charged: bool = True,
    list_key: str | None = None,
    cols: tuple[str, ...] | None = None,
    notice: str | None = None,
) -> Result:
    return Result(
        data,
        lambda ui: generic_human(data, ui, list_key=list_key, cols=cols),
        charged=charged,
        notice=notice,
    )


def collect(pager: SyncPaginator[Any]) -> tuple[list[Any], bool]:
    """Drain a paginator into JSON-ready dicts and say whether a limit stopped it early."""
    items = [dump(item) for item in pager]
    return items, pager.truncated


def all_pages(
    pager: SyncPaginator[Any],
    key: str,
    *,
    charged: bool,
    cols: tuple[str, ...] | None = None,
    human: Callable[[UI, dict[str, Any]], str] | None = None,
) -> Result:
    items, truncated = collect(pager)
    data = {key: items, "count": len(items), "truncated": truncated}
    notice = None
    if truncated:
        notice = "notice: stopped at --max-pages or --max-items; more pages exist."
    if human is not None:
        return Result(data, lambda ui: human(ui, data), charged=charged, notice=notice)
    return result(data, charged=charged, list_key=key, cols=cols, notice=notice)


def _ids(args: argparse.Namespace, positional: str, what: str) -> list[str]:
    values: list[str] = list(getattr(args, positional) or [])
    if args.file:
        values += read_lines(args.file)
    if not values:
        raise CLIError(f"Give at least one {what}, or --file PATH (use - for stdin).", USAGE)
    return values


def _add_ids(
    p: argparse.ArgumentParser, dest: str, metavar: str, what: str, *, chunked: bool = True
) -> None:
    p.add_argument(dest, nargs="*", metavar=metavar, help=f"One or more {what}.")
    p.add_argument("--file", metavar="PATH", help=f"Read {what}, one per line (- for stdin).")
    if chunked:
        p.add_argument(
            "--all",
            action="store_true",
            help="Accept more than one call's cap: split into as many calls as needed.",
        )


def _flat(models: list[Any], key: str) -> Result:
    """The flat list a chunking SDK helper returns, shaped like a paged result."""
    items = [dump(m) for m in models]
    data = {key: items, "count": len(items)}
    return result(data, list_key=key)


def json_object(text: str | None, flag: str) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise CLIError(f"{flag} is not valid JSON: {exc}", USAGE) from exc
    if not isinstance(value, dict):
        raise CLIError(f"{flag} must be a JSON object.", USAGE)
    return value  # pyright: ignore[reportUnknownVariableType]


AUTH_FLAGS = (
    Flag(
        "webhook_auth_scheme",
        help="Auth on each delivery.",
        choices=("none", "bearer", "basic", "header"),
    ),
    Flag("webhook_auth_header_name", help="Header name, for the header scheme."),
    Flag("webhook_auth_secret", help="Credential value, stored encrypted."),
)


def webhook_auth(args: argparse.Namespace) -> dict[str, Any] | None:
    fields = {
        "scheme": args.webhook_auth_scheme,
        "headerName": args.webhook_auth_header_name,
        "secret": args.webhook_auth_secret,
    }
    given = {k: v for k, v in fields.items() if v is not None}
    if not given:
        return None
    if "scheme" not in given:
        raise CLIError("--webhook-auth-header-name and --webhook-auth-secret need a scheme.", USAGE)
    return given


# ---- statutes --------------------------------------------------------------------------

SEARCH_FLAGS = (
    Flag("state", help="Jurisdiction code such as ca or federal."),
    Flag("corpus_type", "l", "Corpus type filter."),
    Flag("act_status", help="Only this status, for example in_force."),
    Flag("agency", "l", "Agency slug, for agency corpora."),
    Flag("article", "l", "Article filter."),
    Flag("changed_since", help="Only sections changed after this date."),
    Flag("chapter", "l", "Chapter filter."),
    Flag("code", "l", "Code filter."),
    Flag("document_type", help="Federal Register document type."),
    Flag("excerpt_chars", "i", "Excerpt length, 100 to 4000."),
    Flag("exclude_repealed", "b", "Leave out repealed sections."),
    Flag("fields", "l", "Response field to return (comma lists are split)."),
    Flag("include_body", "b", "Return the section text in each row (costs more)."),
    Flag("include_pinpoint", "b", "Resolve a pinpoint inside the query."),
    Flag("limit", "i", "Results per page, 1 to 50."),
    Flag("match_type", help="How to match the query.", choices=("any", "all", "phrase", "boolean")),
    Flag("offset", "i", "Results to skip."),
    Flag("part", "l", "Part filter."),
    Flag("published_from", help="Earliest publication date."),
    Flag("published_to", help="Latest publication date."),
    Flag("source", help="Source filter."),
    Flag("title_number", "i", "Title number filter."),
    Flag("year_from", "i", "Earliest year."),
    Flag("year_to", "i", "Latest year."),
)

COUNT_FLAGS = (
    Flag("state", help="Jurisdiction code such as ca or federal."),
    Flag("corpus_type", "l", "Corpus type filter."),
    Flag("act_status", help="Only this status."),
    Flag("article", "l", "Article filter."),
    Flag("chapter", "l", "Chapter filter."),
    Flag("code", "l", "Code filter."),
    Flag("exclude_repealed", "b", "Leave out repealed sections."),
    Flag("match_type", help="How to match the query.", choices=("any", "all", "phrase", "boolean")),
    Flag("part", "l", "Part filter."),
    Flag("title_number", "i", "Title number filter."),
)

DIVISION_FLAGS = (
    Flag("state", help="Jurisdiction code, for state corpora."),
    Flag("title_number", "i", "USC or CFR title."),
    Flag("code", help="State code name."),
    Flag("chapter", help="Descend into this chapter."),
    Flag("part", help="Descend into this part."),
    Flag("article", help="Descend into this article."),
    Flag("exclude_repealed", "b", "Leave out repealed divisions."),
    Flag("act_status", help="Only this status."),
    Flag("subchapter", help="Descend into this subchapter."),
    Flag("act", help="Descend into this act."),
    Flag("title", help="Descend into this title."),
    Flag("subtitle", help="Descend into this subtitle."),
    Flag("division", help="Descend into this division."),
    Flag("subdivision", help="Descend into this subdivision."),
    Flag("subpart", help="Descend into this subpart."),
    Flag("subject_group", help="Descend into this subject group."),
)

SECTION_BODY_FLAGS = (
    Flag("format", help="Text format, for example html, plain or markdown."),
    Flag("structured", "b", "Also return the subsection tree."),
    Flag("pinpoint", help="A subsection such as (a)(1)."),
    Flag("as_of", help="Read the section as it stood on this date."),
)

CHANGES_FLAGS = (
    Flag("limit", "i", "Changes per page, 1 to 200."),
    Flag("since_id", "i", "Only changes with a larger id (use with --order asc)."),
    Flag("before_id", "i", "Only changes with a smaller id."),
    Flag("change_kind", "l", "Only this kind of change."),
    Flag("order", help="Newest first (desc, default) or oldest first.", choices=("asc", "desc")),
)


def _resolve_batch(s: Session) -> Result:
    a = s.args
    cites = _ids(a, "citations", "citation")
    options = kw(a, ("state", "corpus_type"))
    if a.all:
        return _flat(s.client.statutes.resolve_batch_all(cites, **options), "results")
    data = dump(s.client.statutes.resolve_batch(cites, **options))
    return result(data, list_key="results", cols=None)


def _sections(s: Session) -> Result:
    a = s.args
    ids = _ids(a, "act_ids", "act id")
    options = kw(a, ("include_body",))
    if a.all:
        return _flat(s.client.statutes.get_sections_all(ids, **options), "sections")
    data = dump(s.client.statutes.get_sections_batch(ids, **options))
    return result(data, list_key="sections")


def _count(s: Session) -> Result:
    a = s.args
    data = dump(s.client.statutes.count(query=a.query, **kw(a, names(COUNT_FLAGS))))
    return result(data)


def _divisions(s: Session) -> Result:
    a = s.args
    filters = kw(a, names(DIVISION_FLAGS))
    if wants_all(a):
        forbid(a, "cursor")
        pager = s.client.statutes.iter_divisions(a.corpus_type, **paging_kw(a), **filters)
        return all_pages(pager, "divisions", charged=True)
    data = dump(s.client.statutes.divisions(a.corpus_type, cursor=a.cursor, **filters))
    return result(data, list_key="divisions", notice=paging_notice(data, "divisions", cursor=True))


def _section_changes(s: Session) -> Result:
    a = s.args
    if wants_all(a):
        forbid(a, "since_id", "before_id")
        pager = s.client.statutes.iter_section_changes(
            a.act_id, **kw(a, ("limit", "change_kind", "order")), **paging_kw(a)
        )
        return all_pages(pager, "changes", charged=True)
    data = dump(s.client.statutes.section_changes(a.act_id, **kw(a, names(CHANGES_FLAGS))))
    return result(data, list_key="changes", notice=_changes_notice(data, a.order))


def _changes_notice(data: Any, order: str | None) -> str | None:
    if not more(data):
        return None
    changes = as_list(
        as_dict(data).get("changes") or as_dict(as_dict(data).get("data")).get("changes")
    )
    if not changes:
        return None
    flag = "--since-id" if order == "asc" else "--before-id"
    last = as_dict(changes[-1]).get("id")
    return more_notice("changes", f"Continue with {flag} {last}, or use --all.")


def _neighbors(s: Session) -> Result:
    data = dump(s.client.statutes.neighbors(s.args.act_id, **kw(s.args, ("limit",))))
    return result(data)


def _enactments(s: Session) -> Result:
    return result(dump(s.client.statutes.enactments(s.args.act_id)))


def _section_rulemaking(s: Session) -> Result:
    return result(dump(s.client.statutes.section_rulemaking(s.args.act_id)))


def _part_rulemaking(s: Session) -> Result:
    a = s.args
    return result(dump(s.client.statutes.part_rulemaking(a.title, a.part, **kw(a, ("years",)))))


def _cited_by(s: Session) -> Result:
    return result(dump(s.client.statutes.cited_by(s.args.act_id, **kw(s.args, ("limit",)))))


def _definitions(s: Session) -> Result:
    return result(dump(s.client.statutes.definitions(s.args.act_id)))


def _cross_state(s: Session) -> Result:
    return result(dump(s.client.statutes.cross_state(s.args.act_id, **kw(s.args, ("limit",)))))


def _extract(s: Session) -> Result:
    a = s.args
    if a.file and a.text:
        raise CLIError("Give the text or --file, not both.", USAGE)
    text = read_text(a.file) if a.file else a.text
    if not text:
        raise CLIError("Give the text to scan, or --file PATH (use - for stdin).", USAGE)
    options = kw(a, ("state", "resolve", "include_unresolved"))
    data = dump(s.client.statutes.extract_citations(text, **options))
    return result(data)


def register_statutes(group: Group, add: Add) -> Any:
    """Add the ``statutes`` group and return its subparser action (more can be added)."""
    parent = group("statutes", "Statute operations beyond search, resolve and section (charged).")
    sub = parent.add_subparsers(dest="action", required=True, metavar="ACTION")

    p = add(sub, "resolve-batch", _resolve_batch, "Resolve many citations (charged per citation).")
    _add_ids(p, "citations", "CITATION", "citations")
    p.add_argument("--state", help="Jurisdiction hint for bare citations.")
    p.add_argument("--corpus-type", help="Corpus hint such as STATE or REGULATION.")

    p = add(sub, "sections", _sections, "Fetch many sections at once (charged per section).")
    _add_ids(p, "act_ids", "ACT_ID", "section ids")
    p.add_argument(
        "--include-body",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Also return each section's text (costs more).",
    )

    p = add(sub, "count", _count, "Count sections in a scope or matching a query (charged).")
    p.add_argument("query", nargs="?", help="Optional text or boolean expression.")
    declare(p, COUNT_FLAGS)

    p = add(sub, "divisions", _divisions, "Browse one level of a corpus hierarchy (charged).")
    p.add_argument("corpus_type", metavar="CORPUS_TYPE")
    declare(p, DIVISION_FLAGS)
    p.add_argument("--cursor", help="The nextCursor of the previous page.")
    add_paging(p, "divisions")

    p = add(sub, "changes", _section_changes, "List observed changes to a section (charged).")
    p.add_argument("act_id", metavar="ACT_ID")
    declare(p, CHANGES_FLAGS)
    add_paging(p, "changes")

    p = add(sub, "neighbors", _neighbors, "Show sections related to a section (charged).")
    p.add_argument("act_id", metavar="ACT_ID")
    p.add_argument("--limit", type=int, help="Neighbours to return, 1 to 10.")

    p = add(
        sub, "enactments", _enactments, "Show the session laws that enacted a section (charged)."
    )
    p.add_argument("act_id", metavar="ACT_ID")

    p = add(
        sub,
        "rulemaking",
        _section_rulemaking,
        "Show Federal Register documents behind a CFR section (charged).",
    )
    p.add_argument("act_id", metavar="ACT_ID")

    p = add(
        sub,
        "part-rulemaking",
        _part_rulemaking,
        "Show Federal Register documents for a CFR part (charged).",
    )
    p.add_argument("title", type=int, metavar="TITLE", help="CFR title number.")
    p.add_argument("part", metavar="PART", help="CFR part.")
    p.add_argument("--years", type=int, help="How many years back to look.")

    p = add(sub, "cited-by", _cited_by, "List the sections that cite a section (charged).")
    p.add_argument("act_id", metavar="ACT_ID")
    p.add_argument("--limit", type=int, help="Sections to return, 1 to 100.")

    p = add(sub, "definitions", _definitions, "Show the terms a section defines or uses (charged).")
    p.add_argument("act_id", metavar="ACT_ID")

    p = add(sub, "cross-state", _cross_state, "Find comparable sections in other states (charged).")
    p.add_argument("act_id", metavar="ACT_ID")
    p.add_argument("--limit", type=int, help="States to return, 1 to 25.")

    p = add(
        sub, "extract-citations", _extract, "Find and resolve the citations in a text (charged)."
    )
    p.add_argument("text", nargs="?", help="The text to scan.")
    p.add_argument("--file", metavar="PATH", help="Read the text from a file (- for stdin).")
    p.add_argument("--state", help="Jurisdiction hint for bare citations.")
    p.add_argument(
        "--resolve",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Resolve each citation (default on; off only extracts, for free).",
    )
    p.add_argument(
        "--include-unresolved",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Keep citations that did not resolve.",
    )
    return sub


# ---- session laws ----------------------------------------------------------------------

SL_SEARCH_FLAGS = (
    Flag("jurisdiction", help="Lowercase state code."),
    Flag("session", help="Legislative session label."),
    Flag("series", "l", "Session law series."),
    Flag("instrument_type", "l", "Instrument type such as act or resolution."),
    Flag("approved_from", help="Earliest approval date, YYYY-MM-DD."),
    Flag("approved_to", help="Latest approval date, YYYY-MM-DD."),
    Flag("limit", "i", "Results per page, 1 to 25."),
)

SL_LIST_FLAGS = (
    Flag("session", help="Legislative session label."),
    Flag("series", "l", "Session law series."),
    Flag("instrument_type", "l", "Instrument type."),
    Flag("approved_from", help="Earliest approval date."),
    Flag("approved_to", help="Latest approval date."),
    Flag("effective_from", help="Earliest effective date."),
    Flag("effective_to", help="Latest effective date."),
    Flag("has_text", "b", "Only laws whose text is held (or not)."),
    Flag("text_status", help="Text status filter."),
    Flag("is_law", "b", "Only enacted laws (or only the rest)."),
    Flag("enactment_outcome", "l", "Enactment outcome."),
    Flag("updated_since", help="Only records updated after this timestamp."),
    Flag("q", help="Title text filter."),
    Flag("limit", "i", "Rows per page, 1 to 200."),
)

SL_BODY_FLAGS = (
    Flag("cursor", help="The nextCursor of the previous page."),
    Flag("start_char", "i", "Character offset to start from."),
    Flag("expect_text_sha256", help="Fail with 409 if the text changed since you hashed it."),
    Flag("version", "i", "A version number from the versions command."),
    Flag("include_unverified", "b", "Also serve text we have not verified."),
)


def _sl_search(s: Session) -> Result:
    a = s.args
    if wants_all(a):
        forbid(a, "offset")
        pager = s.client.session_laws.iter_search(
            a.query, **kw(a, names(SL_SEARCH_FLAGS)), **paging_kw(a)
        )
        return all_pages(pager, "results", charged=True)
    data = dump(s.client.session_laws.search(a.query, **kw(a, [*names(SL_SEARCH_FLAGS), "offset"])))
    return result(data, list_key="results", notice=paging_notice(data, "results", offset=True))


def _sl_list(s: Session) -> Result:
    a = s.args
    filters = kw(a, names(SL_LIST_FLAGS))
    if wants_all(a):
        forbid(a, "cursor")
        pager = s.client.session_laws.iter_list(a.jurisdiction, **paging_kw(a), **filters)
        return all_pages(pager, "results", charged=True)
    data = dump(s.client.session_laws.list(a.jurisdiction, cursor=a.cursor, **filters))
    return result(data, list_key="results", notice=paging_notice(data, "laws", cursor=True))


def _sl_get(s: Session) -> Result:
    a = s.args
    return result(dump(s.client.session_laws.get(a.session_law_id, **kw(a, ("jurisdiction",)))))


def _sl_body_all(s: Session) -> Result:
    """Stream every page: NDJSON with --json, else the concatenated text (progress on stderr)."""
    a = s.args
    forbid(a, "cursor")
    pager = s.client.session_laws.iter_body(
        a.session_law_id,
        max_pages=a.max_pages,
        **kw(a, ("start_char", "expect_text_sha256", "version", "include_unverified")),
    )
    pages = 0
    last = ""
    for page in pager:
        pages += 1
        data = dump(page)
        if a.json:
            sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        else:
            last = str(data.get("text") or "")
            sys.stdout.write(last)
            end, total = data.get("pageEnd"), data.get("totalChars")
            where = f", chars to {end} of {total}" if end is not None and total is not None else ""
            print(f"page {pages}{where}", file=sys.stderr)
        sys.stdout.flush()
    if pages and not a.json and not last.endswith("\n"):
        sys.stdout.write("\n")
        sys.stdout.flush()
    notice = None
    if pager.truncated:
        notice = "notice: stopped at --max-pages; more text exists. Raise --max-pages or use --all."
    return Result(None, lambda ui: "", charged=True, notice=notice, printed=True)


def _sl_body(s: Session) -> Result:
    a = s.args
    if a.all or a.max_pages is not None:
        return _sl_body_all(s)
    data = dump(s.client.session_laws.get_body(a.session_law_id, **kw(a, names(SL_BODY_FLAGS))))
    return Result(
        data,
        lambda ui: str(data.get("text") or data.get("content") or generic_human(data, ui)),
        charged=True,
        notice=paging_notice(data, "pages of text", cursor=True, all_flag=False),
    )


def _sl_versions(s: Session) -> Result:
    return result(dump(s.client.session_laws.versions(s.args.session_law_id)))


def _sl_batch(s: Session) -> Result:
    a = s.args
    ids = _ids(a, "ids", "session law id")
    options = kw(a, ("jurisdiction", "include_body"))
    if a.all:
        return _flat(s.client.session_laws.get_batch_all(ids, **options), "results")
    data = dump(s.client.session_laws.get_batch(ids, **options))
    return result(data, list_key="results")


def _sl_changes(s: Session) -> Result:
    a = s.args
    options = kw(a, ("jurisdiction", "limit"))
    if wants_all(a):
        pager = s.client.session_laws.iter_changes(
            since_id=a.since_id or 0, **options, **paging_kw(a)
        )
        return all_pages(pager, "changes", charged=True)
    data = dump(s.client.session_laws.changes(**kw(a, ("since_id",)), **options))
    return result(data, list_key="changes", notice=paging_notice(data, "changes"))


def register_session_laws(group: Group, add: Add) -> None:
    parent = group("session-laws", "Session laws, acts as enacted (charged).")
    sub = parent.add_subparsers(dest="action", required=True, metavar="ACTION")

    p = add(sub, "search", _sl_search, "Search session laws by topic or wording.")
    p.add_argument("query")
    declare(p, SL_SEARCH_FLAGS)
    p.add_argument("--offset", type=int, help="Results to skip.")
    add_paging(p, "results")

    p = add(sub, "list", _sl_list, "List a state's session laws with filters.")
    p.add_argument("jurisdiction", metavar="JURISDICTION", help="Lowercase state code.")
    declare(p, SL_LIST_FLAGS)
    p.add_argument("--cursor", help="The nextCursor of the previous page.")
    add_paging(p, "laws")

    p = add(sub, "get", _sl_get, "Show one session law's record, without text.")
    p.add_argument("session_law_id", metavar="ID", help="A session law id or citation.")
    p.add_argument("--jurisdiction", help="State, needed when a citation has none.")

    p = add(sub, "body", _sl_body, "Print a session law's text, one page or all pages with --all.")
    p.add_argument("session_law_id", metavar="ID")
    declare(p, SL_BODY_FLAGS)
    g = p.add_argument_group("paging")
    g.add_argument("--all", action="store_true", help="Stream every page (6 credits each).")
    g.add_argument("--max-pages", type=int, metavar="N", help="Stop after N pages (implies --all).")

    p = add(sub, "versions", _sl_versions, "List every version of a session law.")
    p.add_argument("session_law_id", metavar="ID")

    p = add(sub, "batch", _sl_batch, "Fetch many session laws at once.")
    _add_ids(p, "ids", "ID", "session law ids or citations")
    p.add_argument("--jurisdiction", help="Default state for citations.")
    p.add_argument(
        "--include-body",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include the text of each law.",
    )

    p = add(sub, "changes", _sl_changes, "List session law changes since a cursor, oldest first.")
    p.add_argument("--since-id", type=int, help="Last id you have seen; 0 starts at the beginning.")
    p.add_argument("--jurisdiction", help="Only this state.")
    p.add_argument("--limit", type=int, help="Entries per page, 1 to 200.")
    add_paging(p, "changes")


# ---- boards and watches ----------------------------------------------------------------


def _boards(s: Session) -> Result:
    a = s.args
    filters = kw(a, ("corpus_type", "state", "limit"))
    if wants_all(a):
        forbid(a, "offset")
        pager = s.client.boards.iter_list(**filters, **paging_kw(a))
        return all_pages(pager, "boards", charged=False)
    data = dump(s.client.boards.list(**filters, **kw(a, ("offset",))))
    return result(
        data, charged=False, list_key="boards", notice=paging_notice(data, "boards", offset=True)
    )


def register_boards(sub: Any, add: Add) -> None:
    p = add(sub, "boards", _boards, "List the sources a watch can follow (free).")
    p.add_argument("--corpus-type", help="Only this corpus type.")
    p.add_argument("--state", help="Only this jurisdiction, for example wa.")
    p.add_argument("--limit", type=int, help="Page size, 1 to 500.")
    p.add_argument("--offset", type=int, help="Rows to skip.")
    add_paging(p, "boards")


def _watch_update(s: Session) -> Result:
    a = s.args
    options = kw(a, ("webhook_url", "webhook_secret", "is_active"))
    if a.email is not None:
        options["email_address"] = a.email
    auth = webhook_auth(a)
    if auth is not None:
        options["webhook_auth"] = auth
    scope = json_object(a.scope, "--scope")
    if scope is not None:
        options["scope"] = scope
    if not options:
        raise CLIError("Nothing to update. Pass at least one option.", USAGE)
    data = dump(s.client.watches.update(a.watch_id, **options))
    return result(data, charged=False)


def _watch_test(s: Session) -> Result:
    return result(dump(s.client.watches.test(s.args.watch_id)), charged=False)


def _watch_diff(s: Session) -> Result:
    a = s.args
    data = dump(s.client.watches.change_diff(a.watch_id, a.change_id))
    return result(data)


def register_watches(sub: Any, add: Add) -> None:
    p = add(sub, "update", _watch_update, "Change a watch. Only the options you pass change.")
    p.add_argument("watch_id", metavar="WATCH_ID")
    p.add_argument("--webhook-url")
    p.add_argument("--webhook-secret")
    p.add_argument("--email", help="Recipient for the email channel.")
    p.add_argument(
        "--active",
        dest="is_active",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Switch the watch on or off.",
    )
    declare(p, AUTH_FLAGS)
    p.add_argument("--scope", metavar="JSON", help="Narrow the watch with a JSON object.")

    p = add(sub, "test", _watch_test, "Send a test event to the watch's channel.")
    p.add_argument("watch_id", metavar="WATCH_ID")

    p = add(sub, "diff", _watch_diff, "Show the before and after text of one change (charged).")
    p.add_argument("watch_id", metavar="WATCH_ID")
    p.add_argument("change_id", type=int, metavar="CHANGE_ID")
