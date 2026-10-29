from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from vaquill import AsyncVaquill, Vaquill, _retry

KEY = "vq_key_test_0123456789abcdef"  # pragma: allowlist secret
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace real sleeping and record each requested delay."""
    recorded: list[float] = []

    async def fake_asleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(_retry, "sleep", recorded.append)
    monkeypatch.setattr(_retry, "asleep", fake_asleep)
    return recorded


def make(handler: Handler, **kwargs: Any) -> Vaquill:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Vaquill(api_key=KEY, http_client=http, **kwargs)


def amake(handler: Handler, **kwargs: Any) -> AsyncVaquill:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AsyncVaquill(api_key=KEY, http_client=http, **kwargs)


def err(status: int, code: str | None = None, **headers: str) -> httpx.Response:
    body: dict[str, Any] = {"detail": "nope"}
    if code is not None:
        body.update(code=code, requestId="req_1", status=status)
    return httpx.Response(status, json=body, headers=headers)


class Script:
    """A handler that replays queued responses (or raises queued exceptions)."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        # Fresh copy: a response can only be consumed once and steps are shared.
        return httpx.Response(step.status_code, headers=step.headers, content=step.content)
