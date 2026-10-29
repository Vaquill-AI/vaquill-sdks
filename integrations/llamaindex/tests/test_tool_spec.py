"""Every spec function, sync and async, against the fake server."""

import json
from typing import Any, Dict, List, Tuple

import pytest
from fake_server import FakeVaquillServer, example_response

from llama_index.tools.vaquill import VaquillToolSpec
from llama_index.tools.vaquill.base import _READ_FUNCTIONS, _WATCH_FUNCTIONS

Case = Tuple[str, Dict[str, Any], str]

READ_CASES: List[Case] = [
    (
        "search_statutes",
        {"query": "negligence", "state": "ca", "limit": 3, "corpus_type": ["STATE"]},
        "search_statutes",
    ),
    ("get_section", {"act_id": "USC_T42_S1983"}, "get_section"),
    ("get_section", {"act_id": "USC_T42_S1983", "include_body": True, "pinpoint": "(a)"}, "get_section_body"),
    ("resolve_citation", {"cite": "42 U.S.C. 1983", "state": "federal"}, "resolve_statute_citation"),
    (
        "resolve_citations",
        {"citations": ["42 U.S.C. 1983", "42 U.S.C. 1983", "17 C.F.R. 240.10b-5"]},
        "resolve_statute_citations_batch",
    ),
    ("extract_citations", {"text": "See 42 U.S.C. 1983."}, "extract_statute_citations"),
    ("count_sections", {"query": "privacy", "state": "ny"}, "count_statute_sections"),
    ("list_divisions", {"corpus_type": "STATE", "state": "ca", "cursor": "abc"}, "list_statute_divisions"),
    ("get_section_changes", {"act_id": "USC_T42_S1983", "limit": 4}, "get_section_changes"),
    ("get_cited_by", {"act_id": "USC_T42_S1983", "limit": 4}, "get_section_cited_by"),
    ("get_definitions", {"act_id": "USC_T42_S1983"}, "get_section_definitions"),
    ("get_neighbors", {"act_id": "USC_T42_S1983", "limit": 2}, "get_section_neighbors"),
    ("search_session_laws", {"query": "water rights", "jurisdiction": "ca", "limit": 2}, "search_session_laws"),
    ("get_session_law", {"session_law_id": "us1abc", "jurisdiction": "ca"}, "get_session_law"),
    ("get_credit_balance", {}, "get_credit_balance"),
]
WATCH_CASES: List[Case] = [
    (
        "create_watch",
        {"corpus_type": "STATE", "state": "ca", "webhook_url": "https://example.com/hook"},
        "create_watch",
    ),
    ("update_watch", {"watch_id": "w1", "is_active": False}, "update_watch"),
    ("delete_watch", {"watch_id": "w1"}, "delete_watch"),
]


@pytest.mark.parametrize(("name", "kwargs", "op_id"), READ_CASES, ids=lambda v: v if isinstance(v, str) else "")
def test_read_function_sync(
    spec: VaquillToolSpec, server: FakeVaquillServer, name: str, kwargs: Dict[str, Any], op_id: str
) -> None:
    result = getattr(spec, name)(**kwargs)
    assert not result.startswith("Vaquill error"), result
    json.loads(result)
    assert server.operation_for(server.last(op_id).method, server.last(op_id).path) == op_id


@pytest.mark.parametrize(("name", "kwargs", "op_id"), READ_CASES, ids=lambda v: v if isinstance(v, str) else "")
async def test_read_function_async_matches_sync(
    spec: VaquillToolSpec, server: FakeVaquillServer, name: str, kwargs: Dict[str, Any], op_id: str
) -> None:
    sync_result = getattr(spec, name)(**kwargs)
    async_result = await getattr(spec, f"{name}_async")(**kwargs)
    assert async_result == sync_result
    assert len([r for r in server.requests if server.operation_for(r.method, r.path) == op_id]) >= 2


@pytest.mark.parametrize(("name", "kwargs", "op_id"), WATCH_CASES, ids=lambda v: v if isinstance(v, str) else "")
async def test_watch_functions_when_enabled(
    server: FakeVaquillServer, name: str, kwargs: Dict[str, Any], op_id: str
) -> None:
    from conftest import TEST_KEY

    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, enable_watch_management=True)
    assert not getattr(tools, name)(**kwargs).startswith("Vaquill error")
    assert not (await getattr(tools, f"{name}_async")(**kwargs)).startswith("Vaquill error")
    assert server.last(op_id)


@pytest.mark.parametrize(("name", "kwargs", "op_id"), WATCH_CASES, ids=lambda v: v if isinstance(v, str) else "")
async def test_watch_functions_are_blocked_by_default(
    spec: VaquillToolSpec, server: FakeVaquillServer, name: str, kwargs: Dict[str, Any], op_id: str
) -> None:
    assert "disabled" in getattr(spec, name)(**kwargs)
    assert "disabled" in await getattr(spec, f"{name}_async")(**kwargs)
    assert not server.requests


def test_watch_blocked_can_raise(server: FakeVaquillServer) -> None:
    from conftest import TEST_KEY

    from llama_index.tools.vaquill import VaquillToolError

    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, raise_on_error=True)
    with pytest.raises(VaquillToolError, match="disabled"):
        tools.delete_watch("w1")


def test_spec_functions_are_read_only_by_default(spec: VaquillToolSpec) -> None:
    names = [pair[0] for pair in spec.spec_functions]  # type: ignore[index]
    assert names == [pair[0] for pair in _READ_FUNCTIONS]
    assert not {"create_watch", "update_watch", "delete_watch"} & set(names)
    tools = spec.to_tool_list()
    assert [t.metadata.name for t in tools] == names


def test_watch_tools_listed_only_when_enabled(server: FakeVaquillServer) -> None:
    from conftest import TEST_KEY

    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, enable_watch_management=True).to_tool_list()
    assert {t.metadata.name for t in tools} >= {name for name, _ in _WATCH_FUNCTIONS}
    assert len(tools) == len(_READ_FUNCTIONS) + len(_WATCH_FUNCTIONS)


def test_every_tool_has_async_twin_and_costs_in_docstring(spec: VaquillToolSpec) -> None:
    for sync_name, async_name in [*_READ_FUNCTIONS, *_WATCH_FUNCTIONS]:
        assert callable(getattr(spec, sync_name))
        assert callable(getattr(spec, async_name))
    for tool in spec.to_tool_list():
        assert tool.metadata.description
        assert tool.async_fn is not None
    for name in ("search_statutes", "get_section", "resolve_citation", "get_definitions", "get_cited_by"):
        assert "credit" in (getattr(spec, name).__doc__ or "")
    assert "Free" in (spec.get_credit_balance.__doc__ or "")


def test_agent_tools_run_through_function_tool(spec: VaquillToolSpec) -> None:
    tool = next(t for t in spec.to_tool_list() if t.metadata.name == "get_credit_balance")
    output = tool.call()
    assert "creditsRemaining" in str(output)


async def test_agent_tools_run_async_through_function_tool(spec: VaquillToolSpec) -> None:
    tool = next(t for t in spec.to_tool_list() if t.metadata.name == "get_credit_balance")
    output = await tool.acall()
    assert "creditsRemaining" in str(output)


def test_request_shapes(spec: VaquillToolSpec, server: FakeVaquillServer) -> None:
    spec.search_statutes("negligence", state="ca", corpus_type="STATE", limit=3, include_body=True, title_number=5)
    body = server.last("search_statutes").body
    assert body == {
        "query": "negligence",
        "state": "ca",
        "corpusType": "STATE",
        "limit": 3,
        "includeBody": True,
        "titleNumber": 5,
    }

    spec.get_section("USC_T42_S1983", include_body=True, as_of="2020-01-01", format="plain")
    rec = server.last("get_section_body")
    assert rec.path.endswith("/section/USC_T42_S1983/body")
    assert rec.query["asOf"] == ["2020-01-01"] and rec.query["format"] == ["plain"]

    spec.extract_citations("See 42 U.S.C. 1983.")
    assert server.last("extract_statute_citations").body["resolve"] is False
    spec.extract_citations("See 42 U.S.C. 1983.", resolve=True, include_unresolved=True)
    assert server.last("extract_statute_citations").body["resolve"] is True

    spec.resolve_citations(["a", "a", "b"])
    assert server.last("resolve_statute_citations_batch").body["citations"] == ["a", "b"]

    spec.list_divisions("STATE", state="ca")
    assert server.last("list_statute_divisions").query["corpusType"] == ["STATE"]

    spec.get_section("a/b c")
    assert "/section/a%2Fb%20c" in server.last("get_section").path


def test_search_rows_are_projected_and_long_text_is_cut(server: FakeVaquillServer) -> None:
    from conftest import TEST_KEY

    row = {"actId": "A1", "citation": "1 U.S.C. 1", "body": "x" * 500, "wordCount": 12, "history": "noise"}
    server.set(
        "search_statutes",
        200,
        {"creditsConsumed": 4, "count": 1, "hasMore": False, "offset": 0, "query": "q", "results": [row]},
    )
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_chars=100, max_retries=0)
    data = json.loads(tools.search_statutes("q"))
    hit = data["results"][0]
    assert "wordCount" not in hit and "history" not in hit
    assert hit["body"].startswith("x" * 100) and "truncated 400 characters" in hit["body"]
    assert data["creditsConsumed"] == 4


def test_body_text_is_surfaced_once_as_text(server: FakeVaquillServer) -> None:
    from conftest import TEST_KEY

    server.set(
        "get_section_body",
        200,
        {
            "actId": "A1",
            "creditsConsumed": 6,
            "available": True,
            "content": "The text.",
            "plain": "The text.",
            "html": "<p>The text.</p>",
        },
    )
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    data = json.loads(tools.get_section("A1", include_body=True))
    assert data["text"] == "The text."
    assert not {"content", "plain", "html", "markdown"} & set(data)


def test_secret_fields_are_redacted(server: FakeVaquillServer) -> None:
    from conftest import TEST_KEY

    status, body = example_response("create_watch")
    body["webhookSecret"] = "whsec_abc"  # pragma: allowlist secret
    server.set("create_watch", status, body)
    tools = VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0, enable_watch_management=True)
    out = tools.create_watch("STATE", webhook_url="https://example.com/h")
    assert "whsec_abc" not in out
    assert "[redacted]" in out
