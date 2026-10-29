"""The ``vaquill`` command, driven through ``main(argv)`` with a mock transport."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from vaquill import Vaquill, __version__
from vaquill.cli import main
from vaquill.cli._main import _build_parser  # pyright: ignore[reportPrivateUsage]

KEY = "vq_key_test_0123456789abcdef"  # pragma: allowlist secret
# Known-answer vector from the Standard Webhooks README.
SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # pragma: allowlist secret
MSG_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
TS = "1614265330"
PAYLOAD = b'{"test": 2432232314}'
SIG = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
FOREVER = str(10**10)

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class Run:
    code: int
    out: str
    err: str
    requests: list[httpx.Request]

    def json(self) -> Any:
        return json.loads(self.out)


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VAQUILL_API_KEY", "VAQUILL_BASE_URL", "NO_COLOR", "VAQUILL_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COLUMNS", "100")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Run]:
    def go(
        *argv: str,
        handler: Handler | None = None,
        key: str | None = KEY,
        stdin: bytes = b"",
        tty: bool = False,
    ) -> Run:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if handler is None:
                raise AssertionError("unexpected network call")
            return handler(request)

        def factory(**kwargs: Any) -> Vaquill:
            http = httpx.Client(transport=httpx.MockTransport(record))
            return Vaquill(http_client=http, **kwargs)

        if key is not None:
            monkeypatch.setenv("VAQUILL_API_KEY", key)
        out, err = (TTY(), TTY()) if tty else (io.StringIO(), io.StringIO())
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin)))
        code = main(list(argv), _client_factory=factory)
        return Run(code, out.getvalue(), err.getvalue(), seen)

    return go


def no_content(request: httpx.Request) -> httpx.Response:
    return httpx.Response(204)


def reply(body: Any, status: int = 200, **headers: str) -> Handler:
    return lambda request: httpx.Response(status, json=body, headers=headers)


SEARCH = {
    "creditsConsumed": 4,
    "results": [
        {"actId": "USC_42_1983", "citation": "42 U.S.C. 1983", "sectionTitle": "Civil action"},
        {"actId": "USC_42_1985", "citation": "42 U.S.C. 1985", "sectionTitle": "Conspiracy"},
    ],
    "totalMatches": 40,
    "hasMore": True,
    "nextOffset": 2,
}
SECTION = {"actId": "USC_42_1983", "citation": "42 U.S.C. 1983", "sectionTitle": "Civil action"}
WATCH = {
    "id": "w_1",
    "corpusType": "state",
    "state": "wa",
    "channel": "webhook",
    "createdAt": "2026-10-01T00:00:00Z",
    "isActive": True,
}
META = {"requestId": "req_9", "creditsConsumed": 0, "processingTimeMs": 1}
BALANCE = {
    "asOf": "2026-10-29T00:00:00Z",
    "creditsRemaining": 120.5,
    "totalConsumed": 10,
    "totalPurchased": 130.5,
    "usdRemaining": 1.2,
    "plan": "pro",
}


# ---- happy paths ---------------------------------------------------------------------


def test_version_needs_no_key_or_network(run: Callable[..., Run]) -> None:
    r = run("version", key=None)
    assert (r.code, r.requests) == (0, [])
    assert r.out.startswith(f"vaquill {__version__} (python ")
    assert run("version", "--json", key=None).json()["version"] == __version__


def test_search_table_json_credits_and_notice(run: Callable[..., Run]) -> None:
    h = reply(SEARCH)
    r = run("search", "civil rights", "--corpus-type", "STATE", "--corpus-type", "CFR", handler=h)
    assert r.code == 0
    assert "42 U.S.C. 1983" in r.out and "ACT ID" in r.out
    assert r.err.count("credits used: 4") == 1 and "--offset 2" in r.err
    assert "credits used" not in r.out and "notice" not in r.out
    assert json.loads(r.requests[0].content)["corpusType"] == ["STATE", "CFR"]
    j = run("search", "x", "--limit", "2", "--json", handler=h)
    assert j.json()["results"][0]["actId"] == "USC_42_1983"  # dumped by alias
    assert j.json()["creditsConsumed"] == 4 and j.json()["hasMore"] is True


def test_search_sends_limit_and_filters(run: Callable[..., Run]) -> None:
    r = run("search", "x", "--limit", "7", "--state", "ca", handler=reply({"results": []}))
    body = json.loads(r.requests[0].content)
    assert (body["query"], body["limit"], body["state"]) == ("x", 7, "ca")
    assert r.out.startswith("0 results")


def test_resolve_and_unresolved(run: Callable[..., Run]) -> None:
    ok = run(
        "resolve",
        "42 USC 1983",
        handler=reply(
            {"inputCitation": "x", "resolved": True, "section": SECTION, "creditsConsumed": 2}
        ),
    )
    assert ok.code == 0 and "USC_42_1983" in ok.out and "credits used: 2" in ok.err
    assert ok.requests[0].url.params["cite"] == "42 USC 1983"
    miss = run(
        "resolve",
        "zzz",
        handler=reply({"inputCitation": "zzz", "resolved": False, "missReason": "no_match"}),
    )
    assert miss.code == 0 and "no_match" in miss.out and "credits used: 0" in miss.err


def test_section_metadata_and_body(run: Callable[..., Run]) -> None:
    meta = run(
        "section",
        "USC_42_1983",
        handler=reply({"section": SECTION, "creditsConsumed": 2}),
    )
    assert "Civil action" in meta.out and meta.requests[0].url.path.endswith("/USC_42_1983")
    body = run(
        "section",
        "USC_42_1983",
        "--body",
        handler=reply(
            {"actId": "USC_42_1983", "plain": "Every person who...", "creditsConsumed": 6}
        ),
    )
    assert body.out.strip() == "Every person who..." and "credits used: 6" in body.err
    assert body.requests[0].url.path.endswith("/USC_42_1983/body")
    gone = run("section", "A", "--body", handler=reply({"actId": "A", "note": "not held"}))
    assert "not available" in gone.out and "not held" in gone.out


def test_free_commands(run: Callable[..., Run]) -> None:
    cov = run(
        "coverage",
        handler=reply(
            {
                "data": {
                    "totalSections": 100,
                    "stateCountWithData": 1,
                    "corpusTypes": [],
                    "jurisdictions": [
                        {
                            "code": "wa",
                            "name": "Washington",
                            "sectionCount": 60,
                            "hasData": True,
                            "kind": "state",
                        },
                        {
                            "code": "zz",
                            "name": "Nowhere",
                            "sectionCount": 0,
                            "hasData": False,
                            "kind": "state",
                        },
                    ],
                },
                "meta": META,
            }
        ),
    )
    assert "Washington" in cov.out and "Nowhere" not in cov.out and "credits used" not in cov.err
    bal = run("credits", handler=reply(BALANCE))
    assert "120.5" in bal.out and "pro" in bal.out and bal.err == ""
    price = run(
        "pricing",
        handler=reply(
            {
                "costs": [
                    {
                        "credits": 4,
                        "operation": "search_us_statutes",
                        "description": "Search",
                        "category": "search",
                        "usdCost": 0.04,
                        "endpoint": "/api/v1/us/statutes/search",
                    }
                ],
                "dollarPerCredit": 0.01,
                "minCredits": 1,
                "maxCredits": 10,
            }
        ),
    )
    assert "search_us_statutes" in price.out and "$0.01" in price.out


def test_watches_commands(run: Callable[..., Run]) -> None:
    lst = run(
        "watches",
        "list",
        "--limit",
        "1",
        handler=reply({"data": {"watches": [WATCH], "hasMore": True}, "meta": META}),
    )
    assert (
        "w_1" in lst.out and "--offset 1" in lst.err and lst.requests[0].url.params["limit"] == "1"
    )
    create = run(
        "watches",
        "create",
        "state",
        "--state",
        "wa",
        "--webhook-url",
        "https://example.com/hook",
        "--json",
        handler=reply({"data": WATCH, "meta": META}, 201),
    )
    sent = json.loads(create.requests[0].content)
    assert sent == {"corpusType": "state", "state": "wa", "webhookUrl": "https://example.com/hook"}
    assert create.json()["data"]["id"] == "w_1"
    deleted = run("watches", "delete", "w_1", "--json", handler=no_content)
    assert deleted.json() == {"deleted": True, "id": "w_1"}
    assert deleted.requests[0].method == "DELETE"
    change = {
        "id": 7,
        "actId": "A",
        "changeKind": "amended",
        "corpusType": "state",
        "detectedAt": "2026-10-02T00:00:00Z",
        "citation": "RCW 1.1",
    }
    ch = run(
        "watches",
        "changes",
        "w_1",
        handler=reply({"data": {"changes": [change], "hasMore": True}, "meta": META}),
    )
    assert "RCW 1.1" in ch.out and "--before-id 7" in ch.err
    asc = run(
        "watches",
        "changes",
        "w_1",
        "--order",
        "asc",
        handler=reply({"data": {"changes": [change], "hasMore": True}, "meta": META}),
    )
    assert "--since-id 7" in asc.err
    delivery = {
        "id": 1,
        "attemptNumber": 1,
        "attemptedAt": "2026-10-02T00:00:00Z",
        "success": False,
        "statusCode": 500,
        "watchId": "w_1",
        "error": "boom",
    }
    dl = run(
        "watches",
        "deliveries",
        "w_1",
        handler=reply(
            {
                "data": {
                    "deliveries": [delivery],
                    "consecutiveFailures": 1,
                    "consecutiveFailuresTruncated": False,
                    "deliveryHealth": "failing",
                },
                "meta": META,
            }
        ),
    )
    assert (
        "boom" in dl.out
        and "failing" in dl.out
        and dl.requests[0].url.path.endswith("/w_1/deliveries")
    )


def test_api_command(run: Callable[..., Run]) -> None:
    r = run(
        "api",
        "get",
        "/api/v1/things",
        "--query",
        "a=1",
        "--query",
        "t=x",
        "--query",
        "t=y",
        "--limit",
        "5",
        handler=reply({"data": {"hasMore": True, "nextCursor": "c2"}}),
    )
    req = r.requests[0]
    assert req.method == "GET" and req.url.params.get_list("t") == ["x", "y"]
    assert (req.url.params["a"], req.url.params["limit"]) == ("1", "5")
    assert "c2" in r.err and "credits used" not in r.err
    assert json.loads(r.out)["data"]["nextCursor"] == "c2"
    charged = run(
        "api",
        "POST",
        "/api/v1/things",
        "--data",
        '{"k": 1}',
        "--charged",
        handler=reply({"creditsConsumed": 3}),
    )
    assert json.loads(charged.requests[0].content) == {"k": 1}
    assert "Idempotency-Key" in charged.requests[0].headers and "credits used: 3" in charged.err
    from_stdin = run("api", "POST", "/x", "--data", "-", stdin=b'{"s": 1}', handler=reply({}))
    assert json.loads(from_stdin.requests[0].content) == {"s": 1}


# ---- webhook verify -------------------------------------------------------------------


def verify_args(sig: str = SIG) -> list[str]:
    return ["webhook", "verify", "--secret", SECRET, "--id", MSG_ID, "--timestamp", TS]


def test_webhook_verify_readme_vector_from_stdin(run: Callable[..., Run]) -> None:
    r = run(*verify_args(), "--signature", SIG, "--tolerance", FOREVER, stdin=PAYLOAD, key=None)
    assert (r.code, r.requests) == (0, []) and "signature valid" in r.out
    j = run(*verify_args(), "--signature", SIG, "--tolerance", FOREVER, "--json", stdin=PAYLOAD)
    assert j.json() == {"valid": True, "event": None}


def test_webhook_verify_failures(run: Callable[..., Run], tmp_path: Path) -> None:
    common = [*verify_args(), "--tolerance", FOREVER]
    bad = run(*common, "--signature", SIG, stdin=b'{"test": 1}')
    assert bad.code == 1 and "Verification failed" in bad.err and bad.out == ""
    stale = run(*verify_args(), "--signature", SIG, stdin=PAYLOAD)
    assert stale.code == 1 and "tolerance" in stale.err
    shown = run(*common, "--signature", SIG, "--json", stdin=b"x")
    assert shown.json()["valid"] is False and shown.code == 1
    missing = run("webhook", "verify", "--id", "a", "--timestamp", "1", "--signature", "v1,x")
    assert missing.code == 2 and "No secret" in missing.err
    unreadable = run(*common, "--signature", SIG, "--file", str(tmp_path / "nope"))
    assert unreadable.code == 2


def test_webhook_verify_file_and_event(run: Callable[..., Run], tmp_path: Path) -> None:
    body = b'{"event": "watch.changed", "firedAt": "2026-10-29T00:00:00Z"}'
    key = base64.b64decode(SECRET[6:])
    mac = hmac.new(key, f"{MSG_ID}.{TS}.".encode() + body, hashlib.sha256).digest()
    sig = "v1," + base64.b64encode(mac).decode()
    path = tmp_path / "body.json"
    path.write_bytes(body)
    r = run(*verify_args(), "--signature", sig, "--tolerance", FOREVER, "--file", str(path))
    assert r.code == 0 and "watch.changed" in r.out


def test_webhook_secret_from_environment(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAQUILL_WEBHOOK_SECRET", SECRET)
    argv = ["webhook", "verify", "--id", MSG_ID, "--timestamp", TS, "--signature", SIG]
    assert run(*argv, "--tolerance", FOREVER, stdin=PAYLOAD).code == 0


# ---- exit codes -----------------------------------------------------------------------


def status(code: int, error_code: str | None = None) -> Handler:
    body: dict[str, Any] = {"detail": "nope", "requestId": "req_42"}
    if error_code:
        body["code"] = error_code
    return reply(body, code)


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (status(401), 3),
        (status(403), 3),
        (status(402, "insufficient_credits"), 4),
        (status(429, "rate_limited"), 5),
        (status(429, "daily_cap_exceeded"), 5),
        (status(404), 6),
        (status(500), 1),
        (status(400), 1),
    ],
)
def test_api_errors_map_to_exit_codes(
    run: Callable[..., Run], handler: Handler, expected: int
) -> None:
    r = run("credits", "--max-retries", "0", handler=handler)
    assert r.code == expected
    assert r.out == "" and r.err.startswith("error: nope") and "request id req_42" in r.err
    assert len(r.err.strip().splitlines()) == 1 and "Traceback" not in r.err


@pytest.mark.parametrize(
    "exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")], ids=["connect", "timeout"]
)
def test_network_failures_exit_7(run: Callable[..., Run], exc: Exception) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise exc

    r = run("credits", "--max-retries", "0", handler=boom)
    assert r.code == 7 and r.err.startswith("error:") and "Traceback" not in r.err


def test_missing_and_malformed_key_exit_3(run: Callable[..., Run]) -> None:
    none = run("credits", key=None)
    assert none.code == 3 and "VAQUILL_API_KEY" in none.err and none.requests == []
    bad = run("credits", key="not-a-key")
    assert bad.code == 3 and "not-a-key" not in bad.err


def test_usage_errors_exit_2(run: Callable[..., Run]) -> None:
    assert run("search").code == 2
    assert run("nonsense").code == 2
    assert run("api", "FETCH", "/x").code == 2
    assert run("api", "GET", "no-slash", handler=reply({})).code == 2
    assert run("api", "GET", "/x", "--query", "novalue", handler=reply({})).code == 2
    assert run("api", "POST", "/x", "--data", "{oops", handler=reply({})).code == 2
    assert run("watches").code == 2
    assert run("--help").code == 0


def test_spend_guard_blocks_before_any_request(run: Callable[..., Run]) -> None:
    r = run("resolve", "42 USC 1983", "--max-credits", "0", handler=reply({}))
    assert r.code == 4 and r.requests == [] and "Spend guard" in r.err
    ok = run(
        "resolve",
        "x",
        "--max-credits",
        "10",
        handler=reply({"inputCitation": "x", "resolved": False}),
    )
    assert ok.code == 0


# ---- secrets, colour, layout ----------------------------------------------------------


def test_key_is_never_printed(run: Callable[..., Run]) -> None:
    def echo(request: httpx.Request) -> httpx.Response:
        sent = request.headers["Authorization"]
        return httpx.Response(401, json={"detail": f"bad credential {sent} {KEY}"})

    r = run("credits", "--max-retries", "0", "--debug", handler=echo)
    assert r.code == 3
    assert KEY not in r.out + r.err and "vq_key_[redacted]" in r.err
    ok = run("credits", "--debug", handler=reply(BALANCE))
    assert KEY not in ok.out + ok.err
    flag = run("credits", "--api-key", KEY, key=None, handler=reply(BALANCE))
    assert flag.code == 0 and KEY not in flag.out + flag.err


def test_debug_shows_traceback_only_when_asked(run: Callable[..., Run]) -> None:
    quiet = run("credits", "--max-retries", "0", handler=status(500))
    loud = run("credits", "--max-retries", "0", "--debug", handler=status(500))
    assert "Traceback" not in quiet.err and "Traceback" in loud.err
    assert KEY not in loud.err


def test_color_only_on_tty_and_never_with_no_color(
    run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch
) -> None:
    h = reply(BALANCE)
    assert "\x1b[" not in run("credits", handler=h).out  # not a tty
    assert "\x1b[" in run("credits", handler=h, tty=True).out
    assert "\x1b[" not in run("credits", "--no-color", handler=h, tty=True).out
    monkeypatch.setenv("NO_COLOR", "1")
    colored_err = run("credits", handler=status(500), tty=True)
    assert "\x1b[" not in run("credits", handler=h, tty=True).out
    assert "\x1b[" not in colored_err.err


def test_tables_fit_the_terminal(run: Callable[..., Run], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "60")
    long = {"results": [{"actId": "A", "citation": "C", "sectionTitle": "word " * 60}]}
    r = run("search", "x", handler=reply(long))
    assert max(len(line) for line in r.out.splitlines()) <= 60 and "..." in r.out


def test_help_text_is_plain_sentences() -> None:
    parser = _build_parser()
    seen: list[str] = []

    def walk(p: Any) -> None:
        text = p.format_help()
        seen.append(text)
        for action in p._actions:  # pyright: ignore[reportPrivateUsage]
            choices: Any = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for child in choices.values():  # pyright: ignore[reportUnknownVariableType]
                    walk(child)

    walk(parser)
    assert len(seen) > 12
    for text in seen:
        assert not {chr(0x2014), chr(0x2013)} & set(text)
    desc = parser.description or ""
    assert desc.endswith(".") and desc[0].isupper()
