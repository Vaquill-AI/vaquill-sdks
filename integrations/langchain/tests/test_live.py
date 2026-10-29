"""Optional live smoke test. Skipped by default; spends at most 5 credits."""

from __future__ import annotations

import os

import pytest

from langchain_vaquill import VaquillRetriever, VaquillToolkit

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("VAQUILL_API_KEY"), reason="VAQUILL_API_KEY not set"),
]


def test_live_balance_and_one_citation() -> None:
    kit = VaquillToolkit(max_credits=5)
    tools = {t.name: t for t in kit.get_tools()}
    assert "creditsRemaining" in tools["vaquill_credit_balance"].invoke({})  # free
    out = tools["vaquill_resolve_citation"].invoke({"cite": "42 U.S.C. 1983"})  # 2 credits
    assert "1983" in out
    assert kit.credits_spent <= 5


def test_live_retriever_one_excerpt_search() -> None:
    docs = VaquillRetriever(k=1, include_body=False, max_credits=5).invoke(
        "section 1983 civil action"
    )
    assert isinstance(docs, list)  # 4 credits
