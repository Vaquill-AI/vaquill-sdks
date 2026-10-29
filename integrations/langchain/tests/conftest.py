"""A fake Vaquill HTTP server driven by the real OpenAPI routes, and shared fixtures."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

SPEC_PATH = Path(__file__).resolve().parents[3] / "openapi" / "vaquill-us.json"
KEY = "vq_key_fakekey1234567890"  # pragma: allowlist secret


def load_spec() -> dict[str, Any]:
    if not SPEC_PATH.exists():
        pytest.skip(f"{SPEC_PATH} not found (run from the vaquill-sdks checkout)")
    return json.loads(SPEC_PATH.read_text())


def spec_operations() -> dict[str, tuple[str, str]]:
    """operationId -> (METHOD, path template)."""
    spec = load_spec()
    out = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                out[op["operationId"]] = (method.upper(), path)
    return out


def _regex(template: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$")


NOISE = {f"zzNoise{i}": "noise" for i in range(30)}
ROW: dict[str, Any] = {
    "actId": "USC_T42_C21_S1983",
    "citation": "42 U.S.C. § 1983",
    "sectionTitle": "Civil action for deprivation of rights",
    "state": "federal",
    "corpusType": "USC",
    "actStatus": "in_force",
    "excerpt": "Every person who, under color of any statute",
    "body": "Every person who, under color of any statute, ordinance, regulation...",
    "sourceUrl": "https://uscode.house.gov/view.xhtml?req=42+USC+1983",
    "effectiveDate": "1871-04-20",
    "lastAmendedDate": "1996-10-19",
    "currentThrough": "2025-03-15",
    "relevanceScore": 0.91,
    **NOISE,
}
LAW = {
    "citation": "Act 2025-127",
    "enactmentOutcome": "signed",
    "identityConfidence": "high",
    "instrumentType": "act",
    "jurisdiction": "al",
    "series": "acts",
    "session": {"code": "2025R"},
    "sessionLawId": "SSL_AL_2025R_G_Y2025_C2025-127",
    "textStatus": "verified",
    "title": "An act about sheriffs",
}
WATCH = {
    "id": "w_1",
    "channel": "webhook",
    "corpusType": "STATE",
    "createdAt": "2026-01-01T00:00:00Z",
    "isActive": True,
    "webhookUrl": "https://example.com/hook",
}
FM = {"creditsConsumed": 0.0, "processingTimeMs": 1.0}

CANNED: dict[str, tuple[int, Any]] = {
    "search_statutes": (
        200,
        {
            "query": "q",
            "count": 1,
            "hasMore": False,
            "results": [ROW],
            "creditsConsumed": 4,
            "processingTimeMs": 3.0,
            "parsedQuery": "x" * 50,
        },
    ),
    "get_section": (200, {"section": ROW, "creditsConsumed": 2}),
    "get_section_body": (
        200,
        {
            "actId": ROW["actId"],
            "available": True,
            "content": "OPERATIVE TEXT " * 100,
            "plain": "FULL BODY WITH NOTES " * 10,
            "sourceUrl": ROW["sourceUrl"],
            "creditsConsumed": 6,
        },
    ),
    "resolve_statute_citation": (
        200,
        {"inputCitation": "42 U.S.C. 1983", "resolved": True, "section": ROW, "creditsConsumed": 2},
    ),
    "resolve_statute_citations_batch": (
        200,
        {
            "results": [
                {"inputCitation": "42 U.S.C. 1983", "resolved": True, "section": ROW},
                {"inputCitation": "nonsense", "resolved": False, "missReason": "malformed"},
            ],
            "creditsConsumed": 4,
        },
    ),
    "extract_statute_citations": (
        200,
        {
            "counts": {"found": 1, "resolved": 0, "skipped": 0, "unresolved": 1},
            "extractorVersion": "1",
            "textChars": 20,
            "citations": [
                {
                    "raw": "42 U.S.C. 1983",
                    "citation": "42 U.S.C. 1983",
                    "resolved": False,
                    "subtype": "usc",
                    "type": "statute",
                }
            ],
            "creditsConsumed": 0,
        },
    ),
    "count_statute_sections": (200, {"count": 42, "isExact": True, "creditsConsumed": 1}),
    "list_statute_divisions": (
        200,
        {
            "corpusType": "STATE",
            "level": "title",
            "divisions": [{"name": "Title 1", "identifier": "1", "isLeaf": False, "kind": "title"}],
            "creditsConsumed": 1,
        },
    ),
    "get_section_changes": (
        200,
        {
            "actId": ROW["actId"],
            "coverage": "full",
            "changes": [
                {
                    "id": 9,
                    "changeKind": "amended",
                    "corpusType": "USC",
                    "detectedAt": "2026-01-01T00:00:00Z",
                }
            ],
            "creditsConsumed": 1,
        },
    ),
    "get_section_cited_by": (
        200,
        {
            "section": ROW,
            "citers": [{**ROW, "actId": "USC_T42_C21_S1988"}],
            "total": 1,
            "truncated": False,
            "creditsConsumed": 2,
        },
    ),
    "get_section_definitions": (
        200,
        {"section": ROW, "definitions": [{"term": "person"}], "creditsConsumed": 4},
    ),
    "get_section_neighbors": (200, {"section": ROW, "next": [ROW], "creditsConsumed": 2}),
    "get_section_cross_state": (200, {"section": ROW, "creditsConsumed": 6}),
    "get_section_enactments": (
        200,
        {"actId": ROW["actId"], "coverage": {"note": "n"}, "supported": True, "enactments": []},
    ),
    "get_section_rulemaking": (
        200,
        {
            "actId": "CFR_T17_P240",
            "cfrPart": "240",
            "cfrTitle": 17,
            "coverage": [],
            "federalRegisterDocuments": [],
            "legacyPrintedCitations": [],
            "noteIsStale": False,
            "printedNoteCitations": [],
            "processingTimeMs": 1.0,
            "unresolvedCitations": [],
            "versions": [],
        },
    ),
    "list_statutes_coverage": (
        200,
        {
            "data": {
                "corpusTypes": [],
                "jurisdictions": [],
                "stateCountWithData": 0,
                "totalSections": 0,
            },
            "meta": {"processingTimeMs": 1.0},
        },
    ),
    "search_session_laws": (
        200,
        {
            "parsed": {"text": "sheriff"},
            "query": "sheriff",
            "count": 1,
            "hasMore": False,
            "results": [
                {
                    **LAW,
                    "session": "2025R",
                    "href": "https://x",
                    "approvedDate": "2025-04-15",
                    "matchType": "text",
                    "matchedBy": ["query"],
                    "passage": {
                        "snippet": "sheriff pays",
                        "bodyHref": "x",
                        "ownEnd": 1,
                        "ownStart": 0,
                        "seq": 1,
                    },
                }
            ],
            "creditsConsumed": 4,
        },
    ),
    "get_session_law": (200, {**LAW, "creditsConsumed": 2}),
    "get_session_law_body": (
        200,
        {
            "available": True,
            "citation": "Act 2025-127",
            "jurisdiction": "al",
            "session": {"code": "2025R"},
            "sessionLawId": LAW["sessionLawId"],
            "textStatus": "verified",
            "text": "LAW TEXT " * 200,
            "hasMore": False,
            "creditsConsumed": 6,
        },
    ),
    "get_session_law_versions": (
        200,
        {
            "count": 1,
            "sessionLawId": LAW["sessionLawId"],
            "textStatus": "verified",
            "creditsConsumed": 1,
        },
    ),
    "get_credit_balance": (
        200,
        {
            "asOf": "2026-10-29T00:00:00Z",
            "creditsRemaining": 1234.0,
            "totalConsumed": 10.0,
            "totalPurchased": 1244.0,
            "usdRemaining": 12.34,
            "plan": "payg",
        },
    ),
    "get_pricing": (
        200,
        {
            "costs": [
                {
                    "category": "search",
                    "description": "Search",
                    "endpoint": "/us/statutes/search",
                    "usdCost": 0.04,
                    "credits": 4,
                    "operation": "search",
                }
            ],
            "dollarPerCredit": 0.01,
            "maxCredits": 100,
            "minCredits": 1,
        },
    ),
    "list_boards": (200, {"data": {"boards": [], "hasMore": False, "total": 0}, "meta": FM}),
    "list_watches": (200, {"data": {"watches": [WATCH]}, "meta": FM}),
    "create_watch": (200, {"data": {**WATCH, "webhookSecret": "whsec_leakme"}, "meta": FM}),
    "update_watch": (200, {"data": {**WATCH, "isActive": False}, "meta": FM}),
    "delete_watch": (204, None),
}


class FakeServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.overrides: dict[str, tuple[int, Any, dict[str, str]]] = {}
        self.routes = [(m, _regex(p), op) for op, (m, p) in spec_operations().items()]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )

    def override(
        self, op: str, status: int, body: Any, headers: dict[str, str] | None = None
    ) -> None:
        self.overrides[op] = (status, body, headers or {})

    def calls(self, op: str | None = None) -> list[dict[str, Any]]:
        return [r for r in self.requests if op is None or r["op"] == op]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _serve(self) -> None:
                parts = urlsplit(self.path)
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                op = next(
                    (o for m, rx, o in server.routes if m == self.command and rx.match(parts.path)),
                    None,
                )
                server.requests.append(
                    {
                        "op": op,
                        "method": self.command,
                        "path": parts.path,
                        "query": parse_qs(parts.query),
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "json": json.loads(raw) if raw else None,
                    }
                )
                if op in server.overrides:
                    status, body, headers = server.overrides[op]
                elif op in CANNED:
                    (status, body), headers = CANNED[op], {}
                else:
                    status, body, headers = 404, {"detail": "no such route"}, {}
                payload = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PATCH = do_DELETE = _serve

        return Handler


@pytest.fixture
def server() -> Iterator[FakeServer]:
    srv = FakeServer()
    srv.thread.start()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


@pytest.fixture
def provider_kwargs(server: FakeServer) -> dict[str, Any]:
    return {"api_key": KEY, "base_url": server.url, "max_retries": 0}


@pytest.fixture
def toolkit(provider_kwargs: dict[str, Any]) -> Any:
    from langchain_vaquill import VaquillToolkit

    return VaquillToolkit(**provider_kwargs, include_watch_tools=True)


@pytest.fixture
def tools(toolkit: Any) -> dict[str, Any]:
    return {t.name: t for t in toolkit.get_tools()}
