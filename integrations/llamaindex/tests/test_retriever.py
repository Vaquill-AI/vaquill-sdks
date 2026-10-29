"""VaquillRetriever against the fake server."""

import json
from typing import Any, Dict, List

import pytest
from conftest import TEST_KEY
from fake_server import FakeVaquillServer

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.vector_stores.types import FilterOperator, MetadataFilter, MetadataFilters
from llama_index.retrievers.vaquill import VaquillRetriever
from llama_index.tools.vaquill import VaquillToolError

ROWS: List[Dict[str, Any]] = [
    {
        "actId": "USC_T42_S1983",
        "citation": "42 U.S.C. § 1983",
        "state": "federal",
        "corpusType": "USC",
        "actStatus": "in_force",
        "sectionTitle": "Civil action for deprivation of rights",
        "effectiveDate": "1996-10-19",
        "lastAmendedDate": "2023-01-05",
        "sourceUrl": "https://www.govinfo.gov/example",
        "relevanceScore": 0.91,
        "body": "Every person who, under color of any statute...",
        "excerpt": "Every person...",
    },
    {
        "actId": "CA_PEN_187",
        "citation": "Cal. Penal Code § 187",
        "state": "ca",
        "excerpt": "Murder is the unlawful killing.",
    },
    {"actId": "EMPTY", "citation": "Empty", "state": "ca"},
]


def _serve(server: FakeVaquillServer, rows: List[Dict[str, Any]] = ROWS) -> None:
    server.set(
        "search_statutes",
        200,
        {"creditsConsumed": 4, "count": len(rows), "hasMore": False, "offset": 0, "query": "q", "results": rows},
    )


@pytest.fixture
def retriever(server: FakeVaquillServer) -> VaquillRetriever:
    _serve(server)
    return VaquillRetriever(api_key=TEST_KEY, base_url=server.url, max_retries=0)


def test_returns_nodes_with_scores_and_metadata(retriever: VaquillRetriever) -> None:
    nodes = retriever.retrieve("civil rights")
    assert all(isinstance(n, NodeWithScore) and isinstance(n.node, TextNode) for n in nodes)
    assert [n.node.node_id for n in nodes] == ["USC_T42_S1983", "CA_PEN_187"]  # the empty row is skipped
    first = nodes[0]
    assert first.score == 0.91
    assert first.node.get_content().startswith("Every person who, under color")
    assert first.node.metadata == {
        "citation": "42 U.S.C. § 1983",
        "jurisdiction": "federal",
        "id": "USC_T42_S1983",
        "sourceUrl": "https://www.govinfo.gov/example",
        "effectiveDate": "1996-10-19",
        "lastAmendedDate": "2023-01-05",
        "corpusType": "USC",
        "actStatus": "in_force",
        "sectionTitle": "Civil action for deprivation of rights",
    }
    assert nodes[1].score is None
    assert nodes[1].node.get_content().startswith("Murder")  # falls back to the excerpt


async def test_async_retrieve_matches_sync(retriever: VaquillRetriever) -> None:
    sync_nodes = retriever.retrieve("civil rights")
    async_nodes = await retriever.aretrieve(QueryBundle("civil rights"))
    assert [n.node.node_id for n in async_nodes] == [n.node.node_id for n in sync_nodes]
    assert [n.node.metadata for n in async_nodes] == [n.node.metadata for n in sync_nodes]


def test_request_carries_top_k_body_flag_and_filters(server: FakeVaquillServer) -> None:
    _serve(server)
    retriever = VaquillRetriever(
        api_key=TEST_KEY,
        base_url=server.url,
        similarity_top_k=7,
        filters={"state": "ca", "corpusType": "STATE", "title_number": 5},
    )
    retriever.retrieve("homicide")
    body = server.last("search_statutes").body
    assert body == {
        "query": "homicide",
        "limit": 7,
        "includeBody": True,
        "state": "ca",
        "corpusType": "STATE",
        "titleNumber": 5,
    }


def test_include_body_false_sends_no_body_flag(server: FakeVaquillServer) -> None:
    _serve(server)
    VaquillRetriever(api_key=TEST_KEY, base_url=server.url, include_body=False).retrieve("x")
    assert "includeBody" not in server.last("search_statutes").body


def test_metadata_filters_are_translated(server: FakeVaquillServer) -> None:
    _serve(server)
    filters = MetadataFilters(
        filters=[
            MetadataFilter(key="state", value="ny", operator=FilterOperator.EQ),
            MetadataFilter(key="corpus_type", value=["STATE", "REGULATION"], operator=FilterOperator.IN),
        ]
    )
    retriever = VaquillRetriever(api_key=TEST_KEY, base_url=server.url, filters=filters)
    assert retriever.filters == {"state": "ny", "corpus_type": ["STATE", "REGULATION"]}
    retriever.retrieve("x")
    assert server.last("search_statutes").body["corpusType"] == ["STATE", "REGULATION"]


def test_bad_filters_are_rejected_early(server: FakeVaquillServer) -> None:
    with pytest.raises(ValueError, match="Unsupported filter"):
        VaquillRetriever(api_key=TEST_KEY, base_url=server.url, filters={"limit": 99})
    bad = MetadataFilters(filters=[MetadataFilter(key="state", value="x", operator=FilterOperator.GT)])
    with pytest.raises(ValueError, match="EQ and IN"):
        VaquillRetriever(api_key=TEST_KEY, base_url=server.url, filters=bad)


@pytest.mark.parametrize("top_k", [0, 51, -1])
def test_top_k_bounds(server: FakeVaquillServer, top_k: int) -> None:
    with pytest.raises(ValueError, match="similarity_top_k"):
        VaquillRetriever(api_key=TEST_KEY, base_url=server.url, similarity_top_k=top_k)


def test_row_without_act_id_gets_stable_node_id() -> None:
    payload = {"results": [{"citation": "X", "excerpt": "Some text"}]}
    first = VaquillRetriever._to_nodes(payload)[0].node.node_id
    assert first == VaquillRetriever._to_nodes(payload)[0].node.node_id
    assert len(first) == 32


def test_non_dict_payload_yields_no_nodes() -> None:
    assert VaquillRetriever._to_nodes([]) == []


def test_empty_results(server: FakeVaquillServer) -> None:
    _serve(server, [])
    assert VaquillRetriever(api_key=TEST_KEY, base_url=server.url).retrieve("q") == []


def test_api_errors_raise_sanitized_tool_error(server: FakeVaquillServer) -> None:
    server.set("search_statutes", 401, {"detail": f"bad key {TEST_KEY}"})
    retriever = VaquillRetriever(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    with pytest.raises(VaquillToolError, match="rejected the API key") as info:
        retriever.retrieve("q")
    assert TEST_KEY not in str(info.value)
    assert info.value.__cause__ is None


async def test_async_api_errors_raise(server: FakeVaquillServer) -> None:
    server.set("search_statutes", 402, {"detail": "none left"})
    retriever = VaquillRetriever(api_key=TEST_KEY, base_url=server.url, max_retries=0)
    with pytest.raises(VaquillToolError, match="Out of credits"):
        await retriever.aretrieve("q")


def test_works_inside_a_query_pipeline_shape(retriever: VaquillRetriever) -> None:
    nodes = retriever.retrieve(QueryBundle(query_str="rights"))
    assert json.dumps([n.node.metadata for n in nodes])
