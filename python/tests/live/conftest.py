"""Opt-in live tests against the production API. Skipped unless ``VAQUILL_LIVE=1``.

These spend real credits and read ``VAQUILL_API_KEY`` from the environment. The key is
never logged, printed or written: the report scrubs it before any write.
"""

# pyright: basic
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    if os.environ.get("VAQUILL_LIVE") == "1" and os.environ.get("VAQUILL_API_KEY"):
        return
    skip = pytest.mark.skip(reason="live tests: set VAQUILL_LIVE=1 and VAQUILL_API_KEY")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
