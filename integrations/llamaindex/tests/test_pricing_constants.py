"""Pin the planning prices used by the pre-call spend guard to the OpenAPI contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[3] / "openapi" / "vaquill-us.json"


def _search_description() -> str:
    spec = json.loads(SPEC.read_text())
    return spec["paths"]["/api/v1/us/statutes/search"]["post"]["description"]


def test_constants_are_the_documented_prices() -> None:
    from llama_index.retrievers.vaquill.base import BODY_CREDITS_PER_ROW, SEARCH_CREDITS

    assert SEARCH_CREDITS == 4.0
    assert BODY_CREDITS_PER_ROW == 6.0


def test_search_price_matches_the_contract() -> None:
    from llama_index.retrievers.vaquill.base import SEARCH_CREDITS

    if not SPEC.exists():
        pytest.skip(f"{SPEC} not found (run from the vaquill-sdks checkout)")
    assert f"{SEARCH_CREDITS:g} credits" in _search_description()
