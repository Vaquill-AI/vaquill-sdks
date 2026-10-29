"""CLI global flags in either position, debug logging hygiene and a command for every operation."""

from __future__ import annotations

import io
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from vaquill import Vaquill
from vaquill.cli import main
from vaquill.cli._commands import OPERATION_COMMANDS, UNMAPPED
from vaquill.cli._main import (  # pyright: ignore[reportPrivateUsage]
    GLOBAL_DEFAULTS,
    _build_parser,  # pyright: ignore[reportPrivateUsage]
    _parse,  # pyright: ignore[reportPrivateUsage]
)

from .spec import BY_ID, find_op, resolve, sample, spec_server

KEY = "vq_key_test_0123456789abcdef"  # pragma: allowlist secret
OTHER_KEY = "vq_key_other_0123456789abcdef"  # pragma: allowlist secret
Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class Run:
    code: int
    out: str
    err: str
    requests: list[httpx.Request]
    factory_kwargs: list[dict[str, Any]]

    def json(self) -> Any:
        return json.loads(self.out)

    def body(self) -> Any:
        return json.loads(self.requests[-1].content)

    def query(self) -> dict[str, str]:
        return dict(self.requests[-1].url.params)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VAQUILL_API_KEY", "VAQUILL_BASE_URL", "NO_COLOR", "VAQUILL_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COLUMNS", "100")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Run]:
    def go(
        *argv: str,
        handler: Handler | None = spec_server,
        key: str | None = KEY,
        stdin: bytes = b"",
    ) -> Run:
        seen: list[httpx.Request] = []
        made: list[dict[str, Any]] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if handler is None:
                raise AssertionError("unexpected network call")
            return handler(request)

        def factory(**kwargs: Any) -> Vaquill:
            made.append(kwargs)
            http = httpx.Client(transport=httpx.MockTransport(record))
            return Vaquill(http_client=http, **kwargs)

        if key is not None:
            monkeypatch.setenv("VAQUILL_API_KEY", key)
        out, err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))
        code = main(list(argv), _client_factory=factory)
        return Run(code, out.getvalue(), err.getvalue(), seen, made)

    return go


def reply(body: Any, status: int = 200) -> Handler:
    return lambda request: httpx.Response(status, json=body)


# ---- global flags in either position ----------------------------------------------------

VALUE_FLAGS: list[tuple[str, str, str, str, Any, Any]] = [
    # flag, first value, second value, dest, first parsed, second parsed
    ("--api-key", KEY, OTHER_KEY, "api_key", KEY, OTHER_KEY),
    (
        "--base-url",
        "https://a.test",
        "https://b.test",
        "base_url",
        "https://a.test",
        "https://b.test",
    ),
    ("--timeout", "5", "7", "timeout", 5.0, 7.0),
    ("--max-retries", "1", "3", "max_retries", 1, 3),
    ("--max-credits", "11", "22", "max_credits", 11.0, 22.0),
]
SWITCHES = [("--json", "json"), ("--no-color", "no_color"), ("--debug", "debug")]
COMMANDS: list[list[str]] = [
    ["credits"],
    ["search", "q"],
    ["watches", "list"],
    ["statutes", "count"],
    ["session-laws", "versions", "x"],
    ["boards"],
]


def parse(*argv: str) -> Any:
    return _parse(_build_parser(), list(argv))


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: " ".join(c))
@pytest.mark.parametrize("flag,first,second,dest,parsed_first,parsed_second", VALUE_FLAGS)
def test_value_flags_work_before_and_after_the_command(
    command: list[str],
    flag: str,
    first: str,
    second: str,
    dest: str,
    parsed_first: Any,
    parsed_second: Any,
) -> None:
    assert getattr(parse(flag, first, *command), dest) == parsed_first
    assert getattr(parse(*command, flag, first), dest) == parsed_first
    # a flag given after the command wins over one given before it
    assert getattr(parse(flag, first, *command, flag, second), dest) == parsed_second
    # and an unset flag falls back to its default
    assert getattr(parse(*command), dest) == GLOBAL_DEFAULTS[dest]


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: " ".join(c))
@pytest.mark.parametrize("flag,dest", SWITCHES)
def test_switches_work_before_and_after_the_command(
    command: list[str], flag: str, dest: str
) -> None:
    assert getattr(parse(flag, *command), dest) is True
    assert getattr(parse(*command, flag), dest) is True
    assert getattr(parse(flag, *command, flag), dest) is True
    assert getattr(parse(*command), dest) is False


def test_flags_between_group_and_action_are_accepted() -> None:
    assert parse("watches", "--api-key", KEY, "list").api_key == KEY
    assert parse("statutes", "--json", "count").json is True


def test_global_flags_before_the_command_reach_the_client(run: Callable[..., Run]) -> None:
    r = run(
        "--api-key", OTHER_KEY, "--base-url", "https://x.test", "--timeout", "9",
        "--max-retries", "0", "--max-credits", "50", "--json", "credits",
        key=None,
        handler=spec_server,
    )  # fmt: skip
    assert r.code == 0, r.err
    assert r.json()["creditsRemaining"] is not None
    kwargs = r.factory_kwargs[0]
    assert kwargs == {
        "api_key": OTHER_KEY,
        "base_url": "https://x.test",
        "timeout": 9.0,
        "max_retries": 0,
        "max_credits": 50.0,
    }
    assert r.requests[0].url.host == "x.test"


def test_global_flags_after_the_command_reach_the_client(run: Callable[..., Run]) -> None:
    r = run(
        "credits", "--api-key", OTHER_KEY, "--base-url", "https://y.test", "--timeout", "4",
        "--max-retries", "1", "--max-credits", "8", "--json",
        key=None,
    )  # fmt: skip
    assert r.code == 0, r.err
    assert r.factory_kwargs[0]["base_url"] == "https://y.test"
    assert r.factory_kwargs[0]["max_credits"] == 8.0
    assert r.json()["plan"]


def test_flag_after_the_command_wins_end_to_end(run: Callable[..., Run]) -> None:
    r = run("--api-key", "vq_key_before_000000", "credits", "--api-key", OTHER_KEY, key=None)
    assert r.code == 0 and r.factory_kwargs[0]["api_key"] == OTHER_KEY


def test_missing_key_is_still_exit_3(run: Callable[..., Run]) -> None:
    assert run("credits", key=None).code == 3


def test_max_credits_before_the_command_blocks_a_charged_call(run: Callable[..., Run]) -> None:
    r = run("--max-credits", "0", "resolve", "42 USC 1983")
    assert r.code == 4 and r.requests == []
    after = run("resolve", "42 USC 1983", "--max-credits", "0")
    assert after.code == 4 and after.requests == []


# ---- debug logging ----------------------------------------------------------------------


def test_debug_adds_and_removes_its_log_handler(run: Callable[..., Run]) -> None:
    logger = logging.getLogger("vaquill")
    handlers, level = list(logger.handlers), logger.level
    for _ in range(3):
        assert run("credits", "--debug").code == 0
        assert logger.handlers == handlers and logger.level == level
    failed = run("--debug", "credits", handler=reply({"detail": "no"}, 500), key=KEY)
    assert failed.code != 0
    assert logger.handlers == handlers and logger.level == level


# ---- one command per operation ----------------------------------------------------------

ARGV: dict[str, list[str]] = {
    "search_statutes": ["search", "q"],
    "resolve_statute_citation": ["resolve", "42 USC 1983"],
    "resolve_statute_citations_batch": ["statutes", "resolve-batch", "42 USC 1983", "1 USC 1"],
    "get_section": ["section", "A"],
    "get_section_body": ["section", "A", "--body"],
    "get_section_neighbors": ["statutes", "neighbors", "A"],
    "get_sections_batch": ["statutes", "sections", "A", "B"],
    "count_statute_sections": ["statutes", "count", "q"],
    "list_statutes_coverage": ["coverage"],
    "list_statute_divisions": ["statutes", "divisions", "STATE", "--state", "wa"],
    "get_section_changes": ["statutes", "changes", "A"],
    "get_section_enactments": ["statutes", "enactments", "A"],
    "get_section_rulemaking": ["statutes", "rulemaking", "A"],
    "get_part_rulemaking": ["statutes", "part-rulemaking", "12", "1026"],
    "get_section_cited_by": ["statutes", "cited-by", "A"],
    "get_section_definitions": ["statutes", "definitions", "A"],
    "get_section_cross_state": ["statutes", "cross-state", "A"],
    "extract_statute_citations": ["statutes", "extract-citations", "see 42 USC 1983"],
    "search_session_laws": ["session-laws", "search", "q"],
    "list_session_laws": ["session-laws", "list", "wa"],
    "get_session_law": ["session-laws", "get", "us1_x"],
    "get_session_law_body": ["session-laws", "body", "us1_x"],
    "get_session_law_versions": ["session-laws", "versions", "us1_x"],
    "get_session_laws_batch": ["session-laws", "batch", "us1_x", "us1_y"],
    "get_session_law_changes": ["session-laws", "changes"],
    "list_watches": ["watches", "list"],
    "create_watch": ["watches", "create", "state", "--state", "wa"],
    "update_watch": ["watches", "update", "w_1", "--active"],
    "delete_watch": ["watches", "delete", "w_1"],
    "test_watch": ["watches", "test", "w_1"],
    "list_watch_changes": ["watches", "changes", "w_1"],
    "get_watch_change_diff": ["watches", "diff", "w_1", "5"],
    "list_watch_deliveries": ["watches", "deliveries", "w_1"],
    "list_boards": ["boards"],
    "get_credit_balance": ["credits"],
    "get_pricing": ["pricing"],
}


def command_paths() -> set[tuple[str, ...]]:
    """Every runnable command path in the parser, walked from its sub-parsers."""
    found: set[tuple[str, ...]] = set()

    def walk(parser: Any, prefix: tuple[str, ...]) -> None:
        for action in parser._actions:  # pyright: ignore[reportPrivateUsage]
            choices: Any = getattr(action, "choices", None)
            if not isinstance(choices, dict):
                continue
            for name, child in choices.items():  # pyright: ignore[reportUnknownVariableType]
                path = (*prefix, str(name))  # pyright: ignore[reportUnknownArgumentType]
                if child.get_default("run") is not None:  # pyright: ignore[reportUnknownMemberType]
                    found.add(path)
                walk(child, path)

    walk(_build_parser(), ())
    return found


def test_every_operation_has_a_command_or_a_documented_reason() -> None:
    spec_ids = set(BY_ID)
    covered, excused = set(OPERATION_COMMANDS), set(UNMAPPED)
    assert spec_ids <= covered | excused, f"no CLI command: {sorted(spec_ids - covered - excused)}"
    assert not covered & excused
    assert not (covered | excused) - spec_ids, "stale entries for operations the spec dropped"
    assert all(reason.strip() for reason in UNMAPPED.values())
    assert set(ARGV) == spec_ids, "add a sample command line to ARGV for every operation"


def test_every_mapped_command_exists_in_the_parser() -> None:
    paths = command_paths()
    for op_id, path in OPERATION_COMMANDS.items():
        assert path in paths, f"{op_id} maps to missing command {' '.join(path)}"


@pytest.mark.parametrize("op_id", sorted(BY_ID))
def test_command_calls_its_operation(op_id: str, run: Callable[..., Run]) -> None:
    argv = ARGV[op_id]
    assert tuple(argv[: len(OPERATION_COMMANDS[op_id])]) == OPERATION_COMMANDS[op_id]
    r = run(*argv, "--json")
    assert r.code == 0, r.err
    assert len(r.requests) == 1
    assert find_op(r.requests[0]).op_id == op_id
    assert r.json() is not None


def test_statutes_group_repeats_the_core_commands(run: Callable[..., Run]) -> None:
    paths = command_paths()
    for name in ("search", "resolve", "section", "coverage"):
        assert ("statutes", name) in paths
    r = run("statutes", "search", "q", "--state", "wa")
    assert r.code == 0 and r.body()["state"] == "wa"


# ---- charged commands obey the spend guard and the error contract -----------------------

CHARGED = [op for op in ARGV if BY_ID[op].charged]


@pytest.mark.parametrize("op_id", CHARGED)
def test_charged_commands_respect_max_credits(op_id: str, run: Callable[..., Run]) -> None:
    r = run(*ARGV[op_id], "--max-credits", "0")
    assert r.code == 4 and r.requests == [], r.err


def test_new_commands_map_http_errors_to_exit_codes(run: Callable[..., Run]) -> None:
    missing = reply({"detail": "nope"}, 404)
    r = run("statutes", "definitions", "A", handler=missing)
    assert r.code == 6 and "error:" in r.err and r.out == ""
    assert run("session-laws", "get", "x", handler=reply({"detail": "x"}, 401)).code == 3
    assert run("boards", "--max-retries", "0", handler=reply({"detail": "x"}, 429)).code == 5


# ---- search: every filter reaches the wire ----------------------------------------------


def test_search_exposes_every_filter(run: Callable[..., Run]) -> None:
    r = run(
        "search", "trespass", "--state", "ca", "--corpus-type", "state", "--corpus-type", "rule",
        "--act-status", "in_force", "--agency", "epa", "--article", "2", "--changed-since", "2026-01-01",
        "--chapter", "5", "--code", "pen", "--document-type", "rule", "--excerpt-chars", "300",
        "--exclude-repealed", "--fields", "actId,citation", "--include-body", "--include-pinpoint",
        "--limit", "7", "--match-type", "phrase", "--offset", "14", "--part", "9",
        "--published-from", "2020-01-01", "--published-to", "2021-01-01", "--source", "gov",
        "--title-number", "42", "--year-from", "1990", "--year-to", "2000",
    )  # fmt: skip
    assert r.code == 0, r.err
    assert r.body() == {
        "query": "trespass",
        "state": "ca",
        "corpusType": ["state", "rule"],
        "actStatus": "in_force",
        "agency": ["epa"],
        "article": ["2"],
        "changedSince": "2026-01-01",
        "chapter": ["5"],
        "code": ["pen"],
        "documentType": "rule",
        "excerptChars": 300,
        "excludeRepealed": True,
        "fields": ["actId", "citation"],
        "includeBody": True,
        "includePinpoint": True,
        "limit": 7,
        "matchType": "phrase",
        "offset": 14,
        "part": ["9"],
        "publishedFrom": "2020-01-01",
        "publishedTo": "2021-01-01",
        "source": "gov",
        "titleNumber": 42,
        "yearFrom": 1990,
        "yearTo": 2000,
    }
    off = run("search", "x", "--no-exclude-repealed")
    assert off.body()["excludeRepealed"] is False


def test_search_filters_cover_the_sdk_signature() -> None:
    import inspect

    from vaquill.cli._commands import SEARCH_FLAGS
    from vaquill.resources.statutes import SyncStatutes

    params = set(inspect.signature(SyncStatutes.search).parameters)
    params -= {"self", "query", "options"}
    assert {f.dest for f in SEARCH_FLAGS} == params


def spec_page(
    request: httpx.Request, key: str, mutate: Callable[[dict[str, Any]], None]
) -> httpx.Response:
    """The spec's example for this request with one row under ``key``, edited by ``mutate``."""
    body: Any = json.loads(spec_server(request).content)
    scope: dict[str, Any] = body if key in body else body["data"]
    if not scope[key]:
        schema = resolve(find_op(request).response or {})
        props = schema["properties"]
        props = resolve(props["data"])["properties"] if key not in props else props
        scope[key] = [sample(resolve(props[key])["items"])]
    scope[key] = scope[key][:1]
    mutate(scope)
    return httpx.Response(200, json=body)


def page(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"results": items, **extra}


def test_search_all_follows_pages_and_max_pages_stops(run: Callable[..., Run]) -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        offset = json.loads(request.content).get("offset", 0)
        row = {"actId": f"A{offset}", "citation": f"C{offset}", "sectionTitle": "t"}
        more = offset < 2
        extra: dict[str, Any] = {"nextOffset": offset + 1} if more else {}
        return httpx.Response(200, json=page([row], hasMore=more, creditsConsumed=4, **extra))

    full = run("search", "q", "--all", "--json", handler=pages)
    assert full.code == 0, full.err
    assert [r["actId"] for r in full.json()["results"]] == ["A0", "A1", "A2"]
    assert full.json()["truncated"] is False and len(full.requests) == 3
    limited = run("search", "q", "--max-pages", "2", "--json", handler=pages)
    assert len(limited.requests) == 2 and limited.json()["truncated"] is True
    assert "stopped" in limited.err
    human = run("search", "q", "--all", handler=pages)
    assert "A2" in human.out and "3 results" in human.out
    assert run("search", "q", "--all", "--offset", "3", handler=pages).code == 2


# ---- section flags ----------------------------------------------------------------------


def test_section_body_flags_use_the_real_parameter_names(run: Callable[..., Run]) -> None:
    r = run(
        "section", "A", "--body", "--as-of", "2020-01-01", "--pinpoint", "(a)(1)",
        "--format", "markdown", "--structured",
    )  # fmt: skip
    assert r.code == 0, r.err
    assert r.query() == {
        "asOf": "2020-01-01",
        "pinpoint": "(a)(1)",
        "format": "markdown",
        "structured": "true",
    }


def test_section_flags_without_body_are_a_usage_error(run: Callable[..., Run]) -> None:
    r = run("section", "A", "--as-of", "2020-01-01", handler=None)
    assert r.code == 2 and "--body" in r.err


def test_resolve_hints_and_coverage_state(run: Callable[..., Run]) -> None:
    r = run("resolve", "1 USC 1", "--state", "wa", "--corpus-type", "STATE")
    assert r.query()["state"] == "wa" and r.query()["corpusType"] == "STATE"
    assert run("coverage", "--state", "wa").query() == {"state": "wa"}


# ---- statutes group ----------------------------------------------------------------------


def test_resolve_batch_reads_arguments_file_and_stdin(
    run: Callable[..., Run], tmp_path: Any
) -> None:
    listing = tmp_path / "cites.txt"
    listing.write_text("b\n\nc\n")
    r = run("statutes", "resolve-batch", "a", "--file", str(listing), "--state", "wa")
    assert r.body() == {"citations": ["a", "b", "c"], "state": "wa"}
    piped = run("statutes", "resolve-batch", "--file", "-", stdin=b"x\ny\n")
    assert piped.body()["citations"] == ["x", "y"]
    assert run("statutes", "resolve-batch", handler=None).code == 2


def test_sections_count_and_extract(run: Callable[..., Run], tmp_path: Any) -> None:
    assert run("statutes", "sections", "A", "B", "--include-body").body() == {
        "actIds": ["A", "B"],
        "includeBody": True,
    }
    r = run(
        "statutes", "count", "--state", "wa", "--corpus-type", "state", "--title-number", "5",
        "--exclude-repealed", "--match-type", "boolean", "--act-status", "in_force",
    )  # fmt: skip
    assert r.body() == {
        "state": "wa",
        "corpusType": ["state"],
        "titleNumber": 5,
        "excludeRepealed": True,
        "matchType": "boolean",
        "actStatus": "in_force",
    }
    doc = tmp_path / "doc.txt"
    doc.write_text("see 42 USC 1983")
    e = run("statutes", "extract-citations", "--file", str(doc), "--no-resolve", "--state", "wa")
    assert e.body() == {"text": "see 42 USC 1983", "resolve": False, "state": "wa"}
    both = run("statutes", "extract-citations", "t", "--file", str(doc), handler=None)
    assert both.code == 2
    assert run("statutes", "extract-citations", handler=None).code == 2


def test_divisions_and_changes_filters_and_all(run: Callable[..., Run]) -> None:
    r = run(
        "statutes", "divisions", "STATE", "--state", "wa", "--title-number", "9", "--code", "rcw",
        "--chapter", "1", "--part", "2", "--article", "3", "--exclude-repealed", "--act-status", "x",
        "--subchapter", "a", "--act", "b", "--title", "c", "--subtitle", "d", "--division", "e",
        "--subdivision", "f", "--subpart", "g", "--subject-group", "h", "--cursor", "cur",
    )  # fmt: skip
    assert r.code == 0, r.err
    assert r.query() == {
        "corpusType": "STATE", "state": "wa", "titleNumber": "9", "code": "rcw", "chapter": "1",
        "part": "2", "article": "3", "excludeRepealed": "true", "actStatus": "x",
        "subchapter": "a", "act": "b", "title": "c", "subtitle": "d", "division": "e",
        "subdivision": "f", "subpart": "g", "subjectGroup": "h", "cursor": "cur",
    }  # fmt: skip

    def divisions(request: httpx.Request) -> httpx.Response:
        first = request.url.params.get("cursor") is None

        def mutate(scope: dict[str, Any]) -> None:
            scope.update(hasMore=first, nextCursor="c2" if first else None)

        return spec_page(request, "divisions", mutate)

    walked = run("statutes", "divisions", "STATE", "--all", "--json", handler=divisions)
    assert walked.code == 0, walked.err
    assert len(walked.json()["divisions"]) == 2 and len(walked.requests) == 2
    assert run("statutes", "divisions", "STATE", "--all", "--cursor", "z", handler=None).code == 2

    c = run(
        "statutes", "changes", "A", "--limit", "5", "--since-id", "3", "--change-kind", "amended",
        "--change-kind", "repealed", "--order", "asc",
    )  # fmt: skip
    assert c.query() == {
        "limit": "5", "sinceId": "3", "order": "asc"
    } | {"changeKind": c.requests[-1].url.params.get_list("changeKind")[0]}  # fmt: skip
    assert c.requests[-1].url.params.get_list("changeKind") == ["amended", "repealed"]
    assert run("statutes", "changes", "A", "--all", "--since-id", "1", handler=None).code == 2


def test_section_extras_take_their_parameters(run: Callable[..., Run]) -> None:
    assert run("statutes", "neighbors", "A", "--limit", "4").query() == {"limit": "4"}
    assert run("statutes", "cited-by", "A", "--limit", "9").query() == {"limit": "9"}
    assert run("statutes", "cross-state", "A", "--limit", "6").query() == {"limit": "6"}
    pr = run("statutes", "part-rulemaking", "12", "1026", "--years", "3")
    assert pr.requests[-1].url.path.endswith("/part/12/1026/rulemaking")
    assert pr.query() == {"years": "3"}


# ---- session laws ------------------------------------------------------------------------


def test_session_law_search_list_and_body_flags(run: Callable[..., Run]) -> None:
    s = run(
        "session-laws", "search", "q", "--jurisdiction", "wa", "--session", "2025",
        "--series", "laws", "--instrument-type", "act", "--approved-from", "2025-01-01",
        "--approved-to", "2025-12-31", "--limit", "5", "--offset", "5",
    )  # fmt: skip
    assert s.body() == {
        "query": "q", "jurisdiction": "wa", "session": "2025", "series": ["laws"],
        "instrumentType": ["act"], "approvedFrom": "2025-01-01", "approvedTo": "2025-12-31",
        "limit": 5, "offset": 5,
    }  # fmt: skip
    lst = run(
        "session-laws", "list", "wa", "--session", "2025", "--series", "s", "--instrument-type", "i",
        "--approved-from", "a", "--approved-to", "b", "--effective-from", "c", "--effective-to", "d",
        "--has-text", "--text-status", "ok", "--no-is-law", "--enactment-outcome", "enacted",
        "--updated-since", "u", "--q", "title", "--cursor", "cur", "--limit", "3",
    )  # fmt: skip
    q = lst.requests[-1].url.params
    assert q["jurisdiction"] == "wa" and q["hasText"] == "true" and q["isLaw"] == "false"
    assert q["effectiveFrom"] == "c" and q["updatedSince"] == "u" and q["q"] == "title"
    assert q["cursor"] == "cur" and q["limit"] == "3" and q["enactmentOutcome"] == "enacted"
    body = run(
        "session-laws", "body", "us1_x", "--cursor", "c", "--start-char", "10",
        "--expect-text-sha256", "abc", "--version", "2", "--include-unverified",
    )  # fmt: skip
    assert body.query() == {
        "cursor": "c", "startChar": "10", "expectTextSha256": "abc", "version": "2",
        "includeUnverified": "true",
    }  # fmt: skip
    got = run("session-laws", "get", "wa 2025 c 1", "--jurisdiction", "wa")
    assert got.query() == {"jurisdiction": "wa"}


def test_session_law_batch_and_changes(run: Callable[..., Run]) -> None:
    b = run("session-laws", "batch", "a", "b", "--jurisdiction", "wa", "--include-body")
    assert b.body() == {"ids": ["a", "b"], "jurisdiction": "wa", "includeBody": True}
    assert run("session-laws", "batch", handler=None).code == 2

    def changes(request: httpx.Request) -> httpx.Response:
        since = int(request.url.params.get("sinceId", "0"))

        def mutate(scope: dict[str, Any]) -> None:
            scope["changes"][0]["id"] = since + 1
            scope["hasMore"] = since < 1

        return spec_page(request, "changes", mutate)

    r = run("session-laws", "changes", "--all", "--limit", "1", "--json", handler=changes)
    assert r.code == 0, r.err
    assert [c["id"] for c in r.json()["changes"]] == [1, 2]
    one = run("session-laws", "changes", "--since-id", "7", "--jurisdiction", "wa", "--limit", "2")
    assert one.query() == {"sinceId": "7", "jurisdiction": "wa", "limit": "2"}


def test_session_law_list_all_rejects_a_cursor(run: Callable[..., Run]) -> None:
    assert run("session-laws", "list", "wa", "--all", "--cursor", "c", handler=None).code == 2
    assert run("session-laws", "search", "q", "--all", "--offset", "3", handler=None).code == 2


# ---- boards and watches ------------------------------------------------------------------


def test_boards_filters_and_all(run: Callable[..., Run]) -> None:
    r = run("boards", "--corpus-type", "state", "--state", "wa", "--limit", "5", "--offset", "10")
    assert r.query() == {"corpusType": "state", "state": "wa", "limit": "5", "offset": "10"}

    def boards(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))

        def mutate(scope: dict[str, Any]) -> None:
            scope["boards"][0]["state"] = f"s{offset}"
            scope["hasMore"] = offset < 1

        return spec_page(request, "boards", mutate)

    walked = run("boards", "--all", "--json", handler=boards)
    assert walked.code == 0, walked.err
    assert [b["state"] for b in walked.json()["boards"]] == ["s0", "s1"]
    assert "credits used" not in walked.err


def test_watch_update_test_and_diff(run: Callable[..., Run]) -> None:
    u = run(
        "watches", "update", "w_1", "--webhook-url", "https://h.test", "--webhook-secret", "s",
        "--email", "a@b.test", "--no-active", "--webhook-auth-scheme", "header",
        "--webhook-auth-header-name", "X-Key", "--webhook-auth-secret", "k",
        "--scope", '{"citations": ["x"]}',
    )  # fmt: skip
    assert u.code == 0, u.err
    assert u.requests[-1].method == "PATCH"
    assert u.body() == {
        "webhookUrl": "https://h.test",
        "webhookSecret": "s",
        "emailAddress": "a@b.test",
        "isActive": False,
        "webhookAuth": {"scheme": "header", "headerName": "X-Key", "secret": "k"},
        "scope": {"citations": ["x"]},
    }
    assert "credits used" not in u.err
    assert run("watches", "update", "w_1", handler=None).code == 2
    assert run("watches", "update", "w_1", "--scope", "[1]", handler=None).code == 2
    assert run("watches", "update", "w_1", "--webhook-auth-secret", "k", handler=None).code == 2
    t = run("watches", "test", "w_1")
    assert t.requests[-1].method == "POST" and t.requests[-1].url.path.endswith("/w_1/test")
    d = run("watches", "diff", "w_1", "42")
    assert d.requests[-1].url.path.endswith("/w_1/changes/42/diff") and "credits used" in d.err
    assert run("watches", "diff", "w_1", "notanumber", handler=None).code == 2


def test_watch_create_scope_and_auth(run: Callable[..., Run]) -> None:
    r = run(
        "watches", "create", "state", "--state", "wa", "--webhook-auth-scheme", "bearer",
        "--webhook-auth-secret", "tok", "--scope", '{"a": 1}',
    )  # fmt: skip
    assert r.body()["webhookAuth"] == {"scheme": "bearer", "secret": "tok"}
    assert r.body()["scope"] == {"a": 1}


def test_watch_list_and_changes_all(run: Callable[..., Run]) -> None:
    def listing(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))

        def mutate(scope: dict[str, Any]) -> None:
            scope["watches"][0]["id"] = f"w{offset}"
            scope["hasMore"] = offset < 1

        return spec_page(request, "watches", mutate)

    r = run("watches", "list", "--all", "--json", handler=listing)
    assert [w["id"] for w in r.json()["watches"]] == ["w0", "w1"]

    def changes(request: httpx.Request) -> httpx.Response:
        before = request.url.params.get("beforeId")

        def mutate(scope: dict[str, Any]) -> None:
            scope["changes"][0]["id"] = 5 if before is None else 4
            scope["hasMore"] = before is None

        return spec_page(request, "changes", mutate)

    c = run(
        "watches", "changes", "w1", "--all", "--since", "2026-01-01", "--change-kind", "amended",
        "--limit", "1", "--json", handler=changes,
    )  # fmt: skip
    assert [x["id"] for x in c.json()["changes"]] == [5, 4]
    assert c.requests[0].url.params["since"] == "2026-01-01"
    assert run("watches", "changes", "w1", "--all", "--before-id", "3", handler=None).code == 2


# ---- human output stays readable ---------------------------------------------------------


def test_new_commands_print_something_readable_without_json(run: Callable[..., Run]) -> None:
    for op_id, argv in ARGV.items():
        if op_id == "delete_watch":
            continue
        r = run(*argv)
        assert r.code == 0, (op_id, r.err)
        assert r.out.strip(), op_id
        assert not {chr(0x2014), chr(0x2013)} & set(r.out + r.err)


def test_help_for_every_new_command_is_plain() -> None:
    parser = _build_parser()
    seen = 0

    def walk(p: Any) -> None:
        nonlocal seen
        seen += 1
        text = p.format_help()
        assert not {chr(0x2014), chr(0x2013)} & set(text)
        for action in p._actions:  # pyright: ignore[reportPrivateUsage]
            choices: Any = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for child in choices.values():  # pyright: ignore[reportUnknownVariableType]
                    walk(child)

    walk(parser)
    assert seen > 40
