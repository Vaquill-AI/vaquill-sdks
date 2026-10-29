"""Helpers that read openapi/vaquill-us.json: operations, sample values and a fake server."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "vaquill-us.json"
SPEC: dict[str, Any] = json.loads(SPEC_PATH.read_text())
METHODS = ("get", "post", "put", "patch", "delete")

# operationId -> (namespace, method). docs/OPERATIONS.md must list exactly these.
OPERATIONS: dict[str, tuple[str, str]] = {
    "search_statutes": ("statutes", "search"),
    "resolve_statute_citation": ("statutes", "resolve"),
    "resolve_statute_citations_batch": ("statutes", "resolve_batch"),
    "get_section": ("statutes", "get_section"),
    "get_section_body": ("statutes", "get_section_body"),
    "get_section_neighbors": ("statutes", "neighbors"),
    "get_sections_batch": ("statutes", "get_sections_batch"),
    "count_statute_sections": ("statutes", "count"),
    "list_statutes_coverage": ("statutes", "coverage"),
    "list_statute_divisions": ("statutes", "divisions"),
    "get_section_changes": ("statutes", "section_changes"),
    "get_section_enactments": ("statutes", "enactments"),
    "get_section_rulemaking": ("statutes", "section_rulemaking"),
    "get_part_rulemaking": ("statutes", "part_rulemaking"),
    "get_section_cited_by": ("statutes", "cited_by"),
    "get_section_definitions": ("statutes", "definitions"),
    "get_section_cross_state": ("statutes", "cross_state"),
    "extract_statute_citations": ("statutes", "extract_citations"),
    "search_session_laws": ("session_laws", "search"),
    "list_session_laws": ("session_laws", "list"),
    "get_session_law": ("session_laws", "get"),
    "get_session_law_body": ("session_laws", "get_body"),
    "get_session_law_versions": ("session_laws", "versions"),
    "get_session_laws_batch": ("session_laws", "get_batch"),
    "get_session_law_changes": ("session_laws", "changes"),
    "list_watches": ("watches", "list"),
    "create_watch": ("watches", "create"),
    "update_watch": ("watches", "update"),
    "delete_watch": ("watches", "delete"),
    "test_watch": ("watches", "test"),
    "list_watch_changes": ("watches", "changes"),
    "get_watch_change_diff": ("watches", "change_diff"),
    "list_watch_deliveries": ("watches", "deliveries"),
    "list_boards": ("boards", "list"),
    "get_credit_balance": ("credits", "balance"),
    "get_pricing": ("pricing", "get"),
}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def resolve(schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = SPEC["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def sample(schema: dict[str, Any], *, full: bool = False, depth: int = 0) -> Any:
    """A value valid for ``schema``. Objects carry required members only unless ``full``."""
    schema = resolve(schema)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema or "oneOf" in schema:
        options = [
            o for o in schema.get("anyOf", schema.get("oneOf", [])) if o.get("type") != "null"
        ]
        return sample(options[0], full=full, depth=depth)
    kind: Any = schema.get("type")
    if isinstance(kind, list):
        kind = next(k for k in cast("list[str]", kind) if k != "null")
    if kind == "string":
        return {"date": "2026-01-01", "date-time": "2026-01-01T00:00:00Z"}.get(
            schema.get("format", ""), "x"
        )
    if kind == "integer":
        return max(int(schema.get("minimum") or 0), 1)
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if kind == "array":
        return [sample(schema.get("items", {}), full=full, depth=depth + 1)]
    if kind == "object" or "properties" in schema:
        props: dict[str, Any] = schema.get("properties", {})
        names = list(props) if full and depth == 0 else schema.get("required", [])
        return {n: sample(props[n], full=full, depth=depth + 1) for n in names}
    return {}


@dataclass
class Param:
    name: str
    where: str  # path | query | body
    required: bool
    schema: dict[str, Any]

    @property
    def py(self) -> str:
        return snake(self.name)


@dataclass
class Op:
    op_id: str
    http: str
    template: str
    charged: bool
    params: list[Param] = field(default_factory=lambda: [])
    response: dict[str, Any] | None = None
    status: int = 200
    example: Any = None

    @property
    def namespace(self) -> str:
        return OPERATIONS[self.op_id][0]

    @property
    def method(self) -> str:
        return OPERATIONS[self.op_id][1]

    def ordered(self) -> list[Param]:
        """Required first (path, then query, then body, spec order), then optional."""
        return sorted(self.params, key=lambda p: not p.required)  # stable


def _ops() -> list[Op]:
    found: list[Op] = []
    for template, item in SPEC["paths"].items():
        for http in METHODS:
            raw = item.get(http)
            if not raw:
                continue
            declared = [p for p in raw.get("parameters", []) if p.get("name") != "api_key"]
            op = Op(
                raw["operationId"],
                http.upper(),
                template,
                charged=any(p["name"] == "Idempotency-Key" for p in declared),
            )
            for p in declared:
                if p["in"] in ("path", "query"):
                    op.params.append(
                        Param(p["name"], p["in"], bool(p.get("required")), p["schema"])
                    )
            request_body: Any = raw.get("requestBody") or {}
            body: Any = request_body.get("content", {}).get("application/json")
            if body:
                schema = resolve(body["schema"])
                for name, prop in schema.get("properties", {}).items():
                    op.params.append(Param(name, "body", name in schema.get("required", []), prop))
            for status, resp in raw["responses"].items():
                if status.startswith("2"):
                    op.status = int(status)
                    content = resp.get("content", {}).get("application/json")
                    if content:
                        op.response = content["schema"]
                        examples = content.get("examples")
                        op.example = content.get("example")
                        if op.example is None and examples:
                            op.example = next(iter(examples.values())).get("value")
            found.append(op)
    return found


OPS: list[Op] = _ops()
BY_ID = {o.op_id: o for o in OPS}


def response_body(op: Op) -> Any:
    if op.response is None:
        return None
    return op.example if op.example is not None else sample(op.response)


def template_regex(template: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$")


def find_op(request: httpx.Request) -> Op:
    path = request.url.raw_path.decode().split("?")[0]
    for op in OPS:
        if op.http == request.method and template_regex(op.template).match(path):
            return op
    raise AssertionError(f"No operation for {request.method} {path}")


def spec_server(request: httpx.Request) -> httpx.Response:
    """Answer any request with the spec's example (or a minimal valid body) for its operation."""
    op = find_op(request)
    body = response_body(op)
    if body is None:
        return httpx.Response(op.status)
    return httpx.Response(op.status, json=body)
