"""A local HTTP server that speaks enough of the Vaquill API for the offline test suite."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

SPEC_PATH = Path(__file__).resolve().parents[3] / "openapi" / "vaquill-us.json"

Response = Tuple[int, Any]
Handler = Callable[["Recorded"], Response]


class Recorded:
    def __init__(self, method: str, path: str, query: Dict[str, List[str]], body: Any, headers: Dict[str, str]) -> None:
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.headers = headers


def load_spec() -> Dict[str, Any]:
    return json.loads(SPEC_PATH.read_text())


def _resolve(spec: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    while "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _generate(spec: Dict[str, Any], schema: Dict[str, Any], depth: int = 0) -> Any:
    """A minimal valid value for a schema: required members only."""
    schema = _resolve(spec, schema)
    if "example" in schema:
        return schema["example"]
    if schema.get("examples"):
        return schema["examples"][0]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if _resolve(spec, o).get("type") != "null"]
            return _generate(spec, options[0], depth + 1) if options else None
    if "allOf" in schema:
        merged: Dict[str, Any] = {}
        for part in schema["allOf"]:
            value = _generate(spec, part, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        if depth > 6:
            return {}
        props = schema.get("properties", {})
        return {k: _generate(spec, props[k], depth + 1) for k in schema.get("required", []) if k in props}
    if kind == "array":
        return []
    if kind == "string":
        return {"date-time": "2026-01-01T00:00:00Z", "date": "2026-01-01"}.get(str(schema.get("format")), "x")
    if kind in ("integer", "number"):
        return 0
    if kind == "boolean":
        return False
    return None


def example_response(op_id: str) -> Tuple[int, Any]:
    """The first documented success example (or a generated minimal body) for an operation."""
    spec = load_spec()
    for ops in spec["paths"].values():
        for operation in ops.values():
            if operation.get("operationId") != op_id:
                continue
            status = next(code for code in operation["responses"] if code.startswith("2"))
            content = operation["responses"][status].get("content", {}).get("application/json")
            if not content:
                return int(status), None
            if "example" in content:
                return int(status), content["example"]
            if content.get("examples"):
                first = next(iter(content["examples"].values()))
                return int(status), first.get("value")
            return int(status), _generate(spec, content["schema"])
    raise KeyError(op_id)


class FakeVaquillServer:
    """Routes by (method, templated path). Records every request. No network beyond localhost."""

    def __init__(self) -> None:
        spec = load_spec()
        self._routes: List[Tuple[str, "re.Pattern[str]", str]] = []
        for path, ops in spec["paths"].items():
            pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")
            for method, operation in ops.items():
                self._routes.append((method.upper(), pattern, operation["operationId"]))
        self.overrides: Dict[str, Handler] = {}
        self.requests: List[Recorded] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _serve(self) -> None:
                parts = urlsplit(self.path)
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                rec = Recorded(
                    self.command,
                    parts.path,
                    parse_qs(parts.query),
                    body,
                    {k.lower(): v for k, v in self.headers.items()},
                )
                outer.requests.append(rec)
                status, payload = outer.respond(rec)
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_DELETE = _serve

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=lambda: self._httpd.serve_forever(poll_interval=0.01), daemon=True)

    def operation_for(self, method: str, path: str) -> Optional[str]:
        for route_method, pattern, op_id in self._routes:
            if route_method == method and pattern.match(path):
                return op_id
        return None

    def respond(self, rec: Recorded) -> Response:
        op_id = self.operation_for(rec.method, rec.path)
        if op_id is None:
            return 404, {"detail": "no such route"}
        if op_id in self.overrides:
            return self.overrides[op_id](rec)
        return example_response(op_id)

    def set(self, op_id: str, status: int, body: Any) -> None:
        self.overrides[op_id] = lambda _rec: (status, body)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host!s}:{port}"

    def last(self, op_id: Optional[str] = None) -> Recorded:
        for rec in reversed(self.requests):
            if op_id is None or self.operation_for(rec.method, rec.path) == op_id:
                return rec
        raise AssertionError(f"no request recorded for {op_id}")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
