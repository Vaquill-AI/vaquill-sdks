"""Run every script in examples/ against a spec-driven fake server so they cannot rot."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import time
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from vaquill import Vaquill

from .conftest import KEY
from .spec import spec_server

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client() -> Vaquill:
    return Vaquill(
        api_key=KEY, http_client=httpx.Client(transport=httpx.MockTransport(spec_server))
    )


def test_every_example_file_is_covered() -> None:
    names = {p.stem for p in EXAMPLES.glob("*.py")}
    assert names == {"resolve_citation", "search_and_paginate", "watch_and_verify_webhook"}


def test_resolve_citation(client: Vaquill, capsys: pytest.CaptureFixture[str]) -> None:
    result = load("resolve_citation").main(client)
    assert result is not None
    assert "charged=" in capsys.readouterr().out


def test_search_and_paginate(client: Vaquill) -> None:
    rows = load("search_and_paginate").main(client)
    assert rows
    assert client.credits_spent > 0


def test_watch_and_verify_webhook(client: Vaquill) -> None:
    module = load("watch_and_verify_webhook")
    assert module.main(client)
    body = b'{"event": "corpus.refreshed", "firedAt": "2026-01-01T00:00:00Z"}'
    stamp = str(int(time.time()))
    key = base64.b64decode(module.SECRET[6:])
    mac = hmac.new(key, f"msg_1.{stamp}.".encode() + body, hashlib.sha256).digest()
    headers = {
        "webhook-id": "msg_1",
        "webhook-timestamp": stamp,
        "webhook-signature": "v1," + base64.b64encode(mac).decode(),
    }
    event = module.handle_delivery(body, headers)
    assert event is not None and event.event == "corpus.refreshed"
    assert module.handle_delivery(body + b" ", headers) is None
