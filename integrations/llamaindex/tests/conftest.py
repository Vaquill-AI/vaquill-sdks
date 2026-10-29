import sys
from pathlib import Path
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_server import FakeVaquillServer

from llama_index.tools.vaquill import VaquillToolSpec

TEST_KEY = "vq_key_unit_test_0123456789"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _hermetic_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The offline suite must never pick up a real key or base URL from the shell."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.delenv("VAQUILL_API_KEY", raising=False)
    monkeypatch.delenv("VAQUILL_BASE_URL", raising=False)


@pytest.fixture
def server() -> Iterator[FakeVaquillServer]:
    fake = FakeVaquillServer()
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def spec(server: FakeVaquillServer) -> VaquillToolSpec:
    return VaquillToolSpec(api_key=TEST_KEY, base_url=server.url, max_retries=0)
