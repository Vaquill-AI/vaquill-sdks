"""Opt-in smoke test against the real API. Skipped by default.

Run with ``make live`` (or ``pytest -m live -o addopts=""``) and VAQUILL_API_KEY set.
Spends at most 5 credits: one resolve (2) and one count (1), under a hard max_credits of 5.
The key is read from the environment and never printed.
"""

import os

import pytest

from llama_index.tools.vaquill import VaquillToolSpec

pytestmark = pytest.mark.live

_KEY = os.environ.get("VAQUILL_API_KEY")


@pytest.mark.skipif(not _KEY, reason="VAQUILL_API_KEY is not set")
def test_live_balance_resolve_and_count() -> None:
    tools = VaquillToolSpec(api_key=_KEY, max_credits=5, max_retries=0)
    balance = tools.get_credit_balance()
    assert not balance.startswith("Vaquill error"), balance
    resolved = tools.resolve_citation("42 U.S.C. 1983")
    assert not resolved.startswith("Vaquill error"), resolved
    counted = tools.count_sections(state="federal", title_number=42)
    assert not counted.startswith("Vaquill error"), counted
    assert tools.credits_spent <= 5
