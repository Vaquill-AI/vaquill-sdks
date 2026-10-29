"""Every operation: signature, request on the wire, charged rule and response model."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from pydantic import BaseModel

import vaquill.types as types
from vaquill import AsyncVaquill, Vaquill

from .conftest import KEY
from .spec import BY_ID, OPERATIONS, OPS, Op, resolve, sample, spec_server

OP_IDS = [o.op_id for o in OPS]
DOC = (Path(__file__).resolve().parent.parent / "docs" / "OPERATIONS.md").read_text()


def response_model(op: Op) -> type[BaseModel] | None:
    if op.response is None:
        return None
    return getattr(types, op.response["$ref"].rsplit("/", 1)[-1])


def call_args(op: Op, *, full: bool) -> tuple[list[Any], dict[str, Any]]:
    positional: list[Any] = []
    keywords: dict[str, Any] = {}
    for p in op.params:
        value = sample(p.schema, full=full)
        if p.required:
            positional.append(value)
        elif full:
            keywords[p.py] = value
    return positional, keywords


def expected_request(op: Op, args: list[Any], kwargs: dict[str, Any]) -> tuple[str, list[Any], Any]:
    """Path, sorted query pairs and JSON body the call must produce."""
    given = iter(args)
    values: dict[str, Any] = {}
    for p in op.params:
        if p.required:
            values[p.name] = next(given)
        elif p.py in kwargs:
            values[p.name] = kwargs[p.py]
    path = op.template
    query: list[tuple[str, str]] = []
    body: dict[str, Any] = {}
    for p in op.params:
        if p.name not in values:
            continue
        v = values[p.name]
        if p.where == "path":
            path = path.replace("{" + p.name + "}", quote(str(v), safe=""))
        elif p.where == "query":
            for item in v if isinstance(v, list) else [v]:  # pyright: ignore[reportUnknownVariableType]
                query.append((p.name, "true" if item is True else str(item)))  # pyright: ignore[reportUnknownArgumentType]
        else:
            body[p.name] = v
    return path, sorted(query), (body if any(p.where == "body" for p in op.params) else None)


def check(op: Op, request: httpx.Request, args: list[Any], kwargs: dict[str, Any]) -> None:
    path, query, body = expected_request(op, args, kwargs)
    assert request.method == op.http
    assert request.url.raw_path.decode().split("?")[0] == path
    assert sorted(request.url.params.multi_items()) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers.get("Authorization") == f"Bearer {KEY}"
    assert ("Idempotency-Key" in request.headers) == op.charged


def test_the_map_covers_the_spec_exactly() -> None:
    assert set(OPERATIONS) == set(OP_IDS)
    assert len(OPS) == 36
    assert len(set(OPERATIONS.values())) == 36


def test_charged_is_the_set_that_declares_idempotency_key() -> None:
    declared = {
        op["operationId"]
        for item in json.loads(
            (Path(__file__).resolve().parents[2] / "openapi/vaquill-us.json").read_text()
        )["paths"].values()
        for op in item.values()
        if any(p.get("name") == "Idempotency-Key" for p in op.get("parameters", []))
    }
    assert declared == {o.op_id for o in OPS if o.charged}
    assert len(declared) == 25
    free = {o.op_id for o in OPS if not o.charged}
    assert free == {
        "list_statutes_coverage", "list_boards", "list_watches", "create_watch", "update_watch",
        "delete_watch", "test_watch", "list_watch_changes", "list_watch_deliveries",
        "get_credit_balance", "get_pricing",
    }  # fmt: skip


@pytest.mark.parametrize("op_id", OP_IDS)
def test_docs_table_lists_every_operation(op_id: str) -> None:
    op = BY_ID[op_id]
    row = re.search(rf"^\| `{op_id}` \| `([^`]+)` \| [^|]+ \| (\w+) \|$", DOC, re.M)
    assert row, op_id
    assert row[1] == f"client.{op.namespace}.{op.method}"
    assert row[2] == ("charged" if op.charged else "free")


@pytest.mark.parametrize("op_id", OP_IDS)
def test_signature_matches_the_spec(op_id: str) -> None:
    op = BY_ID[op_id]
    client = Vaquill(api_key=KEY)
    fn = getattr(getattr(client, op.namespace), op.method)
    params = [p for p in inspect.signature(fn).parameters.values() if p.name != "options"]
    positional = [p.name for p in params if p.kind is p.POSITIONAL_OR_KEYWORD]
    keyword_only = {p.name: p for p in params if p.kind is p.KEYWORD_ONLY}
    assert positional == [p.py for p in op.params if p.required]
    assert set(keyword_only) == {p.py for p in op.params if not p.required}
    assert all(p.default is None for p in keyword_only.values())
    assert inspect.signature(fn).parameters["options"].kind is inspect.Parameter.VAR_KEYWORD
    assert fn.__doc__, f"{op_id} has no docstring"


@pytest.mark.parametrize("op_id", OP_IDS)
@pytest.mark.parametrize("full", [False, True], ids=["required", "all"])
def test_sync_request_on_the_wire(op_id: str, full: bool) -> None:
    op = BY_ID[op_id]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return spec_server(request)

    client = Vaquill(api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    args, kwargs = call_args(op, full=full)
    result = getattr(getattr(client, op.namespace), op.method)(*args, **kwargs)
    check(op, seen[0], args, kwargs)
    model = response_model(op)
    assert (result is None) if model is None else isinstance(result, model)


@pytest.mark.parametrize("op_id", OP_IDS)
async def test_async_request_on_the_wire(op_id: str) -> None:
    op = BY_ID[op_id]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return spec_server(request)

    client = AsyncVaquill(
        api_key=KEY, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    args, kwargs = call_args(op, full=True)
    result = await getattr(getattr(client, op.namespace), op.method)(*args, **kwargs)
    check(op, seen[0], args, kwargs)
    model = response_model(op)
    assert (result is None) if model is None else isinstance(result, model)


def test_credits_consumed_is_surfaced_and_counted() -> None:
    op = BY_ID["resolve_statute_citation"]
    client = Vaquill(
        api_key=KEY,
        max_credits=1,
        http_client=httpx.Client(transport=httpx.MockTransport(spec_server)),
    )
    first = client.statutes.resolve("42 U.S.C. 1983")
    assert first.credits_consumed is not None
    assert client.credits_spent == first.credits_consumed > 0
    from vaquill import SpendGuardExceeded

    with pytest.raises(SpendGuardExceeded):
        client.statutes.resolve("42 U.S.C. 1983")
    assert op.charged


def test_a_citation_passed_as_an_id_is_percent_encoded() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return spec_server(request)

    client = Vaquill(api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.session_laws.get("2023 Wash. Laws ch. 1/x")
    assert (
        seen[0].url.raw_path.decode() == "/api/v1/us/session-laws/2023%20Wash.%20Laws%20ch.%201%2Fx"
    )


def test_response_schema_resolution_helper_is_sane() -> None:
    assert resolve({"$ref": "#/components/schemas/CorpusType"})["type"] == "string"
