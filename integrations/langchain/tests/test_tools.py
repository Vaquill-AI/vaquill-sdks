"""Every tool, sync and async, against the fake server and the real OpenAPI routes."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from conftest import KEY, spec_operations
from langchain_core.tools import ToolException

from langchain_vaquill import READ_ONLY_TOOLS, WATCH_WRITE_TOOLS
from langchain_vaquill._operations import OPERATION_TOOLS
from langchain_vaquill.tools import tool_name

# tool name -> (arguments, substring expected in the output)
CASES: dict[str, tuple[dict[str, Any], str]] = {
    "vaquill_search_statutes": ({"query": "civil rights", "state": "federal"}, "USC_T42_C21_S1983"),
    "vaquill_get_statute_section": ({"act_id": "USC_T42_C21_S1983"}, "Civil action"),
    "vaquill_get_statute_text": ({"act_id": "USC_T42_C21_S1983"}, "OPERATIVE TEXT"),
    "vaquill_resolve_citation": ({"cite": "42 U.S.C. 1983"}, '"resolved":true'),
    "vaquill_resolve_citations": ({"citations": ["42 U.S.C. 1983", "nonsense"]}, "malformed"),
    "vaquill_extract_citations": ({"text": "See 42 U.S.C. 1983."}, "42 U.S.C. 1983"),
    "vaquill_count_sections": ({"state": "ca"}, '"count":42'),
    "vaquill_list_divisions": ({"corpus_type": "STATE", "state": "ca"}, "Title 1"),
    "vaquill_section_changes": ({"act_id": "USC_T42_C21_S1983"}, "amended"),
    "vaquill_section_cited_by": ({"act_id": "USC_T42_C21_S1983"}, "USC_T42_C21_S1988"),
    "vaquill_section_definitions": ({"act_id": "USC_T42_C21_S1983"}, "person"),
    "vaquill_section_neighbors": ({"act_id": "USC_T42_C21_S1983"}, "next"),
    "vaquill_section_cross_state": ({"act_id": "USC_T42_C21_S1983"}, "USC_T42_C21_S1983"),
    "vaquill_section_enactments": ({"act_id": "USC_T42_C21_S1983"}, "supported"),
    "vaquill_section_rulemaking": ({"act_id": "CFR_T17_P240"}, "cfrPart"),
    "vaquill_statutes_coverage": ({}, "{"),
    "vaquill_search_session_laws": ({"query": "sheriff", "jurisdiction": "al"}, "Act 2025-127"),
    "vaquill_get_session_law": ({"session_law_id": "SSL_AL_2025R_G_Y2025_C2025-127"}, "sheriffs"),
    "vaquill_get_session_law_text": (
        {"session_law_id": "SSL_AL_2025R_G_Y2025_C2025-127"},
        "LAW TEXT",
    ),
    "vaquill_session_law_versions": ({"session_law_id": "SSL_AL_2025R_G_Y2025_C2025-127"}, "count"),
    "vaquill_credit_balance": ({}, "1234"),
    "vaquill_get_pricing": ({}, "dollarPerCredit"),
    "vaquill_list_boards": ({}, "{"),
    "vaquill_list_watches": ({}, "w_1"),
    "vaquill_create_watch": (
        {"corpus_type": "STATE", "webhook_url": "https://example.com/hook"},
        "w_1",
    ),
    "vaquill_update_watch": ({"watch_id": "w_1", "is_active": False}, '"isActive":false'),
    "vaquill_delete_watch": ({"watch_id": "w_1"}, "deleted"),
}
OP_FOR_TOOL = {v: k for k, v in OPERATION_TOOLS.items()}


def test_every_tool_has_a_case() -> None:
    names = {tool_name(c) for c in READ_ONLY_TOOLS + WATCH_WRITE_TOOLS}
    assert names == set(CASES)


def _route_matches(request: dict[str, Any], op_id: str) -> bool:
    method, template = spec_operations()[op_id]
    rx = "^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$"
    return request["method"] == method and re.match(rx, request["path"]) is not None


@pytest.mark.parametrize("name", sorted(CASES))
def test_tool_sync(name: str, tools: dict[str, Any], server: Any) -> None:
    args, expected = CASES[name]
    out = tools[name].invoke(args)
    assert isinstance(out, str)
    assert expected in out
    assert len(server.requests) == 1
    assert _route_matches(server.requests[0], OP_FOR_TOOL[name])
    assert server.requests[0]["headers"]["authorization"] == f"Bearer {KEY}"
    assert KEY not in out


@pytest.mark.parametrize("name", sorted(CASES))
async def test_tool_async(name: str, tools: dict[str, Any], server: Any) -> None:
    args, expected = CASES[name]
    out = await tools[name].ainvoke(args)
    assert expected in out
    assert _route_matches(server.requests[0], OP_FOR_TOOL[name])


def test_descriptions_state_cost_and_return(tools: dict[str, Any]) -> None:
    for name, tool in tools.items():
        assert len(tool.description) > 40, name
        assert tool.args_schema is not None
        assert "." in tool.description
    for name in (
        "vaquill_search_statutes",
        "vaquill_get_statute_text",
        "vaquill_get_session_law_text",
    ):
        assert "COST" in tools[name].description.upper()
        assert "credit" in tools[name].description


def test_search_defaults_and_arguments_reach_the_wire(tools: dict[str, Any], server: Any) -> None:
    tools["vaquill_search_statutes"].invoke(
        {"query": "x", "corpus_type": ["STATE"], "exclude_repealed": True, "match_type": "phrase"}
    )
    body = server.requests[0]["json"]
    assert body["limit"] == 5
    assert body["corpusType"] == ["STATE"]
    assert body["excludeRepealed"] is True
    assert body["matchType"] == "phrase"
    assert "includeBody" not in body


def test_search_output_is_projected_and_clean(tools: dict[str, Any]) -> None:
    out = json.loads(tools["vaquill_search_statutes"].invoke({"query": "x"}))
    row = out["results"][0]
    assert row["actId"] == "USC_T42_C21_S1983"
    assert row["sourceUrl"].startswith("https://")
    assert "zzNoise0" not in row
    assert "processingTimeMs" not in out and "parsedQuery" not in out
    assert out["creditsConsumed"] == 4


def test_text_tool_prefers_operative_text_and_truncates(tools: dict[str, Any]) -> None:
    out = json.loads(
        tools["vaquill_get_statute_text"].invoke({"act_id": "USC_T42_C21_S1983", "max_chars": 500})
    )
    assert out["textKind"] == "operative"
    assert out["truncated"] is True
    assert len(out["text"]) == 500
    assert out["totalChars"] > 500


def test_text_tool_falls_back_to_full_body(tools: dict[str, Any], server: Any) -> None:
    server.override(
        "get_section_body", 200, {"actId": "X", "plain": "only plain", "creditsConsumed": 6}
    )
    out = json.loads(tools["vaquill_get_statute_text"].invoke({"act_id": "X"}))
    assert out["textKind"] == "full" and out["text"] == "only plain"
    assert "truncated" not in out


def test_text_tool_reports_missing_body(tools: dict[str, Any], server: Any) -> None:
    server.override(
        "get_section_body",
        200,
        {
            "actId": "X",
            "available": False,
            "bodyUnavailable": True,
            "bodyUnavailableReason": "image_only_source",
            "creditsConsumed": 0,
        },
    )
    out = json.loads(tools["vaquill_get_statute_text"].invoke({"act_id": "X"}))
    assert out["bodyUnavailable"] is True and "text" not in out


def test_extract_citations_is_free_by_default(tools: dict[str, Any], server: Any) -> None:
    tools["vaquill_extract_citations"].invoke({"text": "t"})
    assert server.requests[0]["json"]["resolve"] is False
    tools["vaquill_extract_citations"].invoke({"text": "t", "resolve": True})
    assert server.requests[1]["json"]["resolve"] is True


def test_session_law_text_truncates(tools: dict[str, Any]) -> None:
    out = json.loads(
        tools["vaquill_get_session_law_text"].invoke(
            {"session_law_id": "SSL_AL_2025R_G_Y2025_C2025-127", "max_chars": 500}
        )
    )
    assert len(out["text"]) == 500 and out["truncated"] is True


def test_secrets_never_reach_the_model(tools: dict[str, Any]) -> None:
    out = tools["vaquill_create_watch"].invoke(
        {"corpus_type": "STATE", "webhook_url": "https://e.com"}
    )
    assert "whsec_" not in out and "leakme" not in out


def test_output_is_capped(tools: dict[str, Any], server: Any) -> None:
    big = {"query": "q", "results": [{"actId": "A", "citation": "c", "excerpt": "w" * 90000}]}
    server.override("search_statutes", 200, big)
    tool = tools["vaquill_search_statutes"]
    tool.max_output_chars = 3000
    assert len(tool.invoke({"query": "q"})) <= 3000


def test_invalid_arguments_are_explained_to_the_model(tools: dict[str, Any], server: Any) -> None:
    out = tools["vaquill_search_statutes"].invoke({"query": "x", "limit": 999})
    assert out.startswith("Invalid arguments")
    assert "limit" in out
    assert server.requests == []


def test_run_raises_tool_exception_directly(tools: dict[str, Any], server: Any) -> None:
    server.override("get_section", 404, {"detail": "no such section"})
    with pytest.raises(ToolException) as info:
        tools["vaquill_get_statute_section"]._run(act_id="NOPE")
    assert "vaquill_resolve_citation" in str(info.value)


def test_tool_without_provider_explains_itself() -> None:
    from langchain_vaquill.tools import CreditBalanceTool

    with pytest.raises(ToolException, match="VaquillToolkit"):
        CreditBalanceTool()._run()
