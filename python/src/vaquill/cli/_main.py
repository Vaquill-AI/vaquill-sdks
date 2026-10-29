"""Argument parsing, dispatch and error handling for the ``vaquill`` command."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import sys
import traceback
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from .. import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SpendGuardExceeded,
    Vaquill,
    WebhookVerificationError,
    __version__,
    verify_webhook,
)
from .._config import API_KEY_ENV, DEFAULT_MAX_RETRIES
from .._webhooks import WebhookPayloadError
from . import _commands
from ._commands import (
    AUTH_FLAGS,
    SEARCH_FLAGS,
    SECTION_BODY_FLAGS,
    all_pages,
    json_object,
    webhook_auth,
)
from ._core import (
    AUTH,
    CREDITS,
    GENERIC,
    NETWORK,
    NOT_FOUND,
    OK,
    RATE_LIMITED,
    USAGE,
    ClientFactory,
    CLIError,
    Handler,
    Result,
    Session,
    add_paging,
    as_dict,
    as_list,
    declare,
    dump,
    forbid,
    json_text,
    kw,
    more,
    more_notice,
    names,
    paging_kw,
    redact,
    split_csv,
    wants_all,
)
from ._render import UI, paint

__all__ = ["main"]

WEBHOOK_SECRET_ENV = "VAQUILL_WEBHOOK_SECRET"  # pragma: allowlist secret
_ = (GENERIC, USAGE, AUTH, CREDITS, RATE_LIMITED, NOT_FOUND, NETWORK, OK)


# ---- commands --------------------------------------------------------------------------


def _search_human(ui: UI, data: dict[str, Any]) -> str:
    hits = as_list(data.get("results"))
    total = data.get("totalMatches") or data.get("total")
    head = ui.bold(f"{len(hits)} results" + (f" of {total}" if total else ""))
    if not hits:
        return head
    rows = [(h.get("citation"), h.get("actId"), h.get("sectionTitle")) for h in map(as_dict, hits)]
    return head + "\n" + ui.table(["citation", "act id", "title"], rows)


def _search(s: Session) -> Result:
    a = s.args
    filters = kw(a, names(SEARCH_FLAGS))
    if "fields" in filters:
        filters["fields"] = split_csv(filters["fields"])
    if wants_all(a):
        forbid(a, "offset")
        filters.pop("offset", None)
        pager = s.client.statutes.iter_search(a.query, **paging_kw(a), **filters)
        return all_pages(pager, "results", charged=True, human=_search_human)
    data = dump(s.client.statutes.search(a.query, **filters))
    notice = None
    if data.get("hasMore"):
        nxt = data.get("nextOffset")
        notice = more_notice("results", f"Continue with --offset {nxt}." if nxt else "")
    return Result(data, lambda ui: _search_human(ui, data), charged=True, notice=notice)


def _resolve(s: Session) -> Result:
    data = dump(s.client.statutes.resolve(s.args.citation, **kw(s.args, ("state", "corpus_type"))))

    def human(ui: UI) -> str:
        sec = as_dict(data.get("section"))
        if not data.get("resolved") or not sec:
            return ui.kv([("resolved", False), ("reason", data.get("missReason"))])
        return ui.kv(
            [
                ("citation", sec.get("citation")),
                ("act id", sec.get("actId")),
                ("title", sec.get("sectionTitle")),
                ("match", data.get("matchLevel")),
            ]
        )

    return Result(data, human, charged=True)


def _section(s: Session) -> Result:
    a = s.args
    options = kw(a, names(SECTION_BODY_FLAGS))
    if options and not a.body:
        flags = ", ".join("--" + k.replace("_", "-") for k in options)
        raise CLIError(f"{flags} only applies with --body (the text costs more).", USAGE)
    if a.body:
        data = dump(s.client.statutes.get_section_body(a.act_id, **options))

        def human(ui: UI) -> str:
            text = data.get("plain") or data.get("markdown") or data.get("content")
            if not text:
                return ui.kv([("body", "not available"), ("note", data.get("note"))])
            return str(text)

        return Result(data, human, charged=True)
    data = dump(s.client.statutes.get_section(a.act_id))

    def meta(ui: UI) -> str:
        sec = as_dict(data.get("section"))
        keys = (
            "citation",
            "actId",
            "sectionTitle",
            "state",
            "corpusType",
            "actStatus",
            "sourceUrl",
        )
        return ui.kv([(k, sec.get(k)) for k in keys])

    return Result(data, meta, charged=True)


def _coverage(s: Session) -> Result:
    data = dump(s.client.statutes.coverage(**kw(s.args, ("state",))))

    def human(ui: UI) -> str:
        body = as_dict(data.get("data"))
        head = ui.kv(
            [
                ("sections", body.get("totalSections")),
                ("jurisdictions with data", body.get("stateCountWithData")),
                ("measured at", body.get("measuredAt")),
            ]
        )
        rows = [
            (j.get("code"), j.get("sectionCount"), j.get("name"))
            for j in map(as_dict, as_list(body.get("jurisdictions")))
            if j.get("hasData")
        ]
        return head + "\n\n" + ui.table(["code", "sections", "name"], rows) if rows else head

    return Result(data, human)


def _credits(s: Session) -> Result:
    data = dump(s.client.credits.balance())

    def human(ui: UI) -> str:
        keys = ("creditsRemaining", "usdRemaining", "plan", "totalConsumed", "nextExpiry")
        return ui.kv([(k, data.get(k)) for k in keys])

    return Result(data, human)


def _pricing(s: Session) -> Result:
    data = dump(s.client.pricing.get())

    def human(ui: UI) -> str:
        rows = [
            (c.get("credits"), c.get("operation") or c.get("endpoint"), c.get("description"))
            for c in map(as_dict, as_list(data.get("costs")))
        ]
        unit = f"1 credit = ${data.get('dollarPerCredit')}"
        return ui.dim(unit) + "\n" + ui.table(["credits", "operation", "description"], rows)

    return Result(data, human)


def _watch_rows_human(ui: UI, rows: list[Any]) -> str:
    table = [
        (w.get("id"), w.get("corpusType"), w.get("state"), w.get("channel"), w.get("isActive"))
        for w in map(as_dict, rows)
    ]
    return (
        ui.table(["id", "corpus", "state", "channel", "active"], table) if table else "no watches"
    )


def _watches_list(s: Session) -> Result:
    a = s.args
    if wants_all(a):
        forbid(a, "offset")
        pager = s.client.watches.iter_list(**kw(a, ("limit",)), **paging_kw(a))
        return all_pages(
            pager,
            "watches",
            charged=False,
            human=lambda ui, d: _watch_rows_human(ui, as_list(d.get("watches"))),
        )
    data = dump(s.client.watches.list(limit=a.limit, offset=a.offset))
    notice = None
    if more(data):
        count = len(as_list(as_dict(data.get("data")).get("watches")))
        notice = more_notice("watches", f"Continue with --offset {(a.offset or 0) + count}.")
    return Result(
        data,
        lambda ui: _watch_rows_human(ui, as_list(as_dict(data.get("data")).get("watches"))),
        notice=notice,
    )


def _watches_create(s: Session) -> Result:
    a = s.args
    data = dump(
        s.client.watches.create(
            a.corpus_type,
            state=a.state,
            channel=a.channel,
            webhook_url=a.webhook_url,
            webhook_secret=a.webhook_secret,
            webhook_auth=webhook_auth(a),
            email_address=a.email,
            scope=json_object(a.scope, "--scope"),
        )
    )

    def human(ui: UI) -> str:
        w = as_dict(data.get("data"))
        keys = ("id", "corpusType", "state", "channel", "webhookUrl", "emailAddress", "isActive")
        return ui.kv([(k, w.get(k)) for k in keys])

    return Result(data, human)


def _watches_delete(s: Session) -> Result:
    s.client.watches.delete(s.args.watch_id)
    return Result({"deleted": True, "id": s.args.watch_id}, lambda ui: f"deleted {s.args.watch_id}")


def _watch_changes_human(ui: UI, changes: list[Any]) -> str:
    rows = [
        (c.get("id"), c.get("detectedAt"), c.get("changeKind"), c.get("citation") or c.get("actId"))
        for c in map(as_dict, changes)
    ]
    return ui.table(["id", "detected", "kind", "citation"], rows) if rows else "no changes"


def _watches_changes(s: Session) -> Result:
    a = s.args
    if wants_all(a):
        forbid(a, "since_id", "before_id")
        pager = s.client.watches.iter_changes(
            a.watch_id, **kw(a, ("limit", "since", "change_kind", "order")), **paging_kw(a)
        )
        return all_pages(
            pager,
            "changes",
            charged=False,
            human=lambda ui, d: _watch_changes_human(ui, as_list(d.get("changes"))),
        )
    data = dump(
        s.client.watches.changes(
            a.watch_id,
            limit=a.limit,
            since_id=a.since_id,
            before_id=a.before_id,
            order=a.order,
            **kw(a, ("since", "change_kind")),
        )
    )
    changes = as_list(as_dict(data.get("data")).get("changes"))
    notice = None
    if more(data) and changes:
        last = as_dict(changes[-1]).get("id")
        flag = "--since-id" if a.order == "asc" else "--before-id"
        notice = more_notice("changes", f"Continue with {flag} {last}.")
    return Result(data, lambda ui: _watch_changes_human(ui, changes), notice=notice)


def _watches_deliveries(s: Session) -> Result:
    data = dump(s.client.watches.deliveries(s.args.watch_id, limit=s.args.limit))

    def human(ui: UI) -> str:
        body = as_dict(data.get("data"))
        rows = [
            (d.get("attemptedAt"), d.get("success"), d.get("statusCode"), d.get("error"))
            for d in map(as_dict, as_list(body.get("deliveries")))
        ]
        head = ui.kv([("health", body.get("deliveryHealth"))])
        return (head + "\n\n" if head else "") + (
            ui.table(["attempted", "ok", "status", "error"], rows) if rows else "no deliveries"
        )

    return Result(data, human)


def _read_input(path: str | None) -> bytes:
    if path in (None, "-"):
        return sys.stdin.buffer.read()
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise CLIError(f"Cannot read {path}: {exc.strerror}", USAGE) from exc


def _webhook_verify(s: Session) -> Result:
    a = s.args
    secret = a.secret or os.environ.get(WEBHOOK_SECRET_ENV)
    if not secret:
        raise CLIError(f"No secret. Pass --secret or set {WEBHOOK_SECRET_ENV}.", USAGE)
    headers = {
        "webhook-id": a.id,
        "webhook-timestamp": a.timestamp,
        "webhook-signature": a.signature,
    }
    event: str | None = None
    try:
        event = verify_webhook(
            _read_input(a.file), headers, secret, tolerance=a.tolerance, allow_legacy=False
        ).event
    except WebhookPayloadError:
        # The signature is checked before the body is parsed, so this one means it matched.
        pass
    except WebhookVerificationError as exc:
        raise CLIError(
            f"Verification failed: {exc}", GENERIC, {"valid": False, "error": str(exc)}
        ) from exc
    text = "signature valid" + (f" (event {event})" if event else "")
    return Result({"valid": True, "event": event}, lambda ui: text)


def _version(s: Session) -> Result:
    data = {"version": __version__, "python": platform.python_version()}
    return Result(data, lambda ui: f"vaquill {__version__} (python {data['python']})")


def _api(s: Session) -> Result:
    a = s.args
    if not a.path.startswith("/"):
        raise CLIError("PATH must start with '/', for example /api/v1/credits/balance.", USAGE)
    repeated: dict[str, list[str]] = {}
    queries: list[str] = a.query or []
    for item in queries:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise CLIError(f"--query expects key=value, got '{item}'.", USAGE)
        repeated.setdefault(name, []).append(value)
    params: dict[str, Any] = {k: v[0] if len(v) == 1 else v for k, v in repeated.items()}
    if a.limit is not None:
        params["limit"] = a.limit
    body: Any = None
    if a.data is not None:
        raw = sys.stdin.read() if a.data == "-" else a.data
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise CLIError(f"--data is not valid JSON: {exc}", USAGE) from exc
    response = s.client.raw_request(
        a.method, a.path, params=params or None, json=body, charged=a.charged
    )
    data = response.json()
    notice = None
    if more(data):
        d = as_dict(data) if "hasMore" in as_dict(data) else as_dict(as_dict(data).get("data"))
        nxt = d.get("nextCursor") or d.get("nextOffset")
        hint = f"The next page starts at {nxt}." if nxt else ""
        notice = more_notice("pages", f"Pass the next page parameter with --query. {hint}".strip())
    return Result(data, lambda ui: json_text(data), charged=a.charged, notice=notice)


# ---- parser ----------------------------------------------------------------------------


GLOBAL_DEFAULTS: dict[str, Any] = {
    "api_key": None,
    "base_url": None,
    "timeout": None,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_credits": None,
    "json": False,
    "no_color": False,
    "debug": False,
}


def _declare_search(p: argparse.ArgumentParser) -> None:
    p.add_argument("query")
    declare(p, SEARCH_FLAGS)
    add_paging(p, "results (each page is charged)")


def _declare_resolve(p: argparse.ArgumentParser) -> None:
    p.add_argument("citation")
    p.add_argument("--state", help="Jurisdiction hint for a bare citation.")
    p.add_argument("--corpus-type", help="Corpus hint such as STATE or REGULATION.")


def _declare_section(p: argparse.ArgumentParser) -> None:
    p.add_argument("act_id", metavar="ACT_ID")
    p.add_argument("--body", action="store_true", help="Fetch the text instead (costs more).")
    declare(p, SECTION_BODY_FLAGS)


def _declare_coverage(p: argparse.ArgumentParser) -> None:
    p.add_argument("--state", help="Only this jurisdiction.")


# Commands that exist at the top level and again inside the ``statutes`` group.
CORE_STATUTE_COMMANDS: tuple[tuple[str, Handler, str, Any], ...] = (
    ("search", _search, "Search statutes, regulations and rules (charged).", _declare_search),
    ("resolve", _resolve, "Resolve a citation to its section (charged).", _declare_resolve),
    ("section", _section, "Show a section's metadata or text (charged).", _declare_section),
    (
        "coverage",
        _coverage,
        "Show what the corpus holds per jurisdiction (free).",
        _declare_coverage,
    ),
)


def _build_parser() -> argparse.ArgumentParser:
    # Global options default to SUPPRESS: a default set on the top parser would be copied over
    # whatever the subparser parsed (and the reverse), so an unset flag must leave no trace.
    # _parse() fills GLOBAL_DEFAULTS in afterwards.
    S = argparse.SUPPRESS
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("global options")
    g.add_argument("--api-key", default=S, help=f"API key (default: the {API_KEY_ENV} variable).")
    g.add_argument("--base-url", default=S, help="API host (default: https://api.vaquill.ai).")
    g.add_argument("--timeout", type=float, default=S, help="Request timeout in seconds.")
    g.add_argument("--max-retries", type=int, default=S, help="Retries after the first attempt.")
    g.add_argument("--max-credits", type=float, default=S, help="Refuse charged calls past this.")
    g.add_argument("--json", action="store_true", default=S, help="Print machine-readable JSON.")
    g.add_argument("--no-color", action="store_true", default=S, help="Never use colour.")
    g.add_argument("--debug", action="store_true", default=S, help="Log requests, show tracebacks.")

    parser = argparse.ArgumentParser(
        prog="vaquill",
        parents=[common],
        description="Command line access to the Vaquill US primary law Data API.",
        epilog="Exit codes: 0 ok, 1 error, 2 usage, 3 auth, 4 no credits, 5 rate limited, "
        "6 not found, 7 network.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(
        parent: Any, name: str, run: Handler, text: str, *, extra: str = ""
    ) -> argparse.ArgumentParser:
        p = parent.add_parser(
            name, parents=[common], help=text, description=text + extra, add_help=True
        )
        p.set_defaults(run=run)
        return p

    def group(name: str, text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=text, description=text)

    for name, run, text, declare_flags in CORE_STATUTE_COMMANDS:
        declare_flags(add(sub, name, run, text))

    add(sub, "credits", _credits, "Show your credit balance (free).")
    add(sub, "pricing", _pricing, "Show the credit price of every endpoint (free).")

    statutes = _commands.register_statutes(group, add)
    for name, run, text, declare_flags in CORE_STATUTE_COMMANDS:
        declare_flags(add(statutes, name, run, text))
    _commands.register_session_laws(group, add)
    _commands.register_boards(sub, add)

    w = group("watches", "Manage law-change watches (free).")
    ws = w.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = add(ws, "list", _watches_list, "List your watches.")
    p.add_argument("--limit", type=int)
    p.add_argument("--offset", type=int)
    add_paging(p, "watches")
    p = add(ws, "create", _watches_create, "Create a watch on a corpus.")
    p.add_argument("corpus_type", metavar="CORPUS_TYPE")
    p.add_argument("--state")
    p.add_argument("--channel", choices=["webhook", "email", "both"])
    p.add_argument("--webhook-url")
    p.add_argument("--webhook-secret")
    p.add_argument("--email")
    declare(p, AUTH_FLAGS)
    p.add_argument("--scope", metavar="JSON", help="Narrow the watch with a JSON object.")
    p = add(ws, "delete", _watches_delete, "Delete a watch.")
    p.add_argument("watch_id", metavar="WATCH_ID")
    p = add(ws, "changes", _watches_changes, "List the changes a watch recorded.")
    p.add_argument("watch_id", metavar="WATCH_ID")
    p.add_argument("--limit", type=int)
    p.add_argument("--since-id", type=int)
    p.add_argument("--before-id", type=int)
    p.add_argument("--since", help="Only changes detected after this ISO timestamp.")
    p.add_argument("--change-kind", action="append", metavar="KIND", help="Repeatable filter.")
    p.add_argument("--order", choices=["asc", "desc"])
    add_paging(p, "changes")
    p = add(ws, "deliveries", _watches_deliveries, "List recent deliveries for a watch.")
    p.add_argument("watch_id", metavar="WATCH_ID")
    p.add_argument("--limit", type=int)
    _commands.register_watches(ws, add)

    h = group("webhook", "Webhook tools (offline).")
    hs = h.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = add(
        hs,
        "verify",
        _webhook_verify,
        "Verify a Standard Webhooks signature without any network call.",
        extra="\n\nThe body is read from --file or stdin and must be the exact bytes received.",
    )
    p.add_argument("--secret", help=f"Signing secret (default: the {WEBHOOK_SECRET_ENV} variable).")
    p.add_argument("--id", required=True, help="The webhook-id header.")
    p.add_argument("--timestamp", required=True, help="The webhook-timestamp header.")
    p.add_argument("--signature", required=True, help="The webhook-signature header.")
    p.add_argument("--file", help="Read the body from this file (default: stdin).")
    p.add_argument("--tolerance", type=int, default=300, help="Allowed clock skew in seconds.")

    add(sub, "version", _version, "Print the SDK and Python versions.")

    p = add(sub, "api", _api, "Call any endpoint and print the JSON response.")
    p.add_argument(
        "method",
        metavar="METHOD",
        type=str.upper,
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )
    p.add_argument("path", metavar="PATH")
    p.add_argument("--query", action="append", metavar="K=V", help="Query parameter, repeatable.")
    p.add_argument("--data", help="JSON request body, or - to read it from stdin.")
    p.add_argument("--limit", type=int, help="Sets the limit query parameter.")
    p.add_argument("--charged", action="store_true", help="Treat the call as charged.")
    return parser


def _parse(parser: argparse.ArgumentParser, argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse ``argv``; a global flag counts wherever it appears, the last one given wins."""
    args = parser.parse_args(argv)
    for name, default in GLOBAL_DEFAULTS.items():
        if not hasattr(args, name):
            setattr(args, name, default)
    return args


# ---- entry point -----------------------------------------------------------------------


def _exit_code(exc: BaseException) -> int:
    if isinstance(exc, AuthenticationError | PermissionDeniedError):
        return AUTH
    if isinstance(exc, InsufficientCreditsError | SpendGuardExceeded):
        return CREDITS
    if isinstance(exc, RateLimitError):
        return RATE_LIMITED
    if isinstance(exc, NotFoundError):
        return NOT_FOUND
    if isinstance(exc, APIConnectionError):
        return NETWORK
    return GENERIC


def _describe(exc: BaseException) -> str:
    if isinstance(exc, APIStatusError):
        extra = [f"status {exc.status_code}"]
        if exc.code:
            extra.append(f"code {exc.code}")
        if isinstance(exc, RateLimitError) and exc.retry_after_seconds is not None:
            extra.append(f"retry after {exc.retry_after_seconds:g}s")
        if exc.request_id:
            extra.append(f"request id {exc.request_id}")
        return f"{exc.message} ({', '.join(extra)})"
    if isinstance(exc, ValidationError):
        where = ".".join(str(part) for part in exc.errors()[0]["loc"])
        return f"The API response did not match the expected shape (at {where})."
    return (str(exc).splitlines() or [type(exc).__name__])[0]


class _RedactingFilter(logging.Filter):
    def __init__(self, key: str | None) -> None:
        super().__init__()
        self.key = key

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self.key)
        record.args = None
        return True


def main(argv: Sequence[str] | None = None, *, _client_factory: ClientFactory | None = None) -> int:
    """Run the CLI and return the exit code. ``_client_factory`` is a test seam."""
    parser = _build_parser()
    try:
        args = _parse(parser, argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else GENERIC

    session = Session(args, _client_factory or Vaquill)
    out_color = not args.no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    err_color = not args.no_color and not os.environ.get("NO_COLOR") and sys.stderr.isatty()
    ui = UI(color=out_color, width=shutil.get_terminal_size((80, 24)).columns)

    def fail(message: str) -> None:
        print(paint("error: ", "red", err_color) + redact(message, session.key), file=sys.stderr)

    logger = logging.getLogger("vaquill")
    handler: logging.Handler | None = None
    previous_level = logger.level
    if args.debug:
        handler = logging.StreamHandler(sys.stderr)
        handler.addFilter(_RedactingFilter(session.key))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    try:
        try:
            result = args.run(session)
        except CLIError as exc:
            if args.json and exc.payload is not None:
                print(json_text(exc.payload))
            fail(str(exc))
            return exc.code
        except Exception as exc:
            fail(_describe(exc))
            if args.debug:
                print(redact(traceback.format_exc(), session.key), file=sys.stderr)
            return _exit_code(exc)
        finally:
            session.close()

        print(json_text(result.payload) if args.json else result.human(ui))
        if result.notice:
            print(paint(result.notice, "yellow", err_color), file=sys.stderr)
        if result.charged:
            print(f"credits used: {session.client.credits_spent:g}", file=sys.stderr)
        return OK
    finally:
        if handler is not None:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            handler.close()
