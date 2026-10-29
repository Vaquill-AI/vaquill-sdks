"""The API surface cannot drift away from the toolkit unnoticed."""

from __future__ import annotations

import os
from typing import Any

import pytest
from conftest import SPEC_PATH, spec_operations

from langchain_vaquill import READ_ONLY_TOOLS, WATCH_WRITE_TOOLS
from langchain_vaquill._operations import OPERATION_TOOLS, UNMAPPED
from langchain_vaquill.tools import tool_name


@pytest.fixture(scope="module")
def operations() -> dict[str, tuple[str, str]]:
    if not SPEC_PATH.exists() and os.environ.get("CI"):
        pytest.fail(f"{SPEC_PATH} missing in CI; check out the whole vaquill-sdks repository")
    return spec_operations()


def test_every_operation_is_exposed_or_explained(operations: dict[str, Any]) -> None:
    known = set(OPERATION_TOOLS) | set(UNMAPPED)
    assert set(operations) - known == set(), "new API operation: add a tool or an UNMAPPED reason"
    assert known - set(operations) == set(), "operation no longer in the spec: remove it"


def test_mapped_and_unmapped_are_disjoint() -> None:
    assert not set(OPERATION_TOOLS) & set(UNMAPPED)


def test_unmapped_reasons_are_real_sentences() -> None:
    for op, reason in UNMAPPED.items():
        assert len(reason) > 25 and reason.endswith("."), op


def test_every_tool_maps_to_exactly_one_operation() -> None:
    tools = {tool_name(c) for c in READ_ONLY_TOOLS + WATCH_WRITE_TOOLS}
    assert sorted(OPERATION_TOOLS.values()) == sorted(tools)


def test_every_mutating_operation_is_an_opt_in_tool(operations: dict[str, Any]) -> None:
    mutating = {op for op, (method, _) in operations.items() if method in {"PATCH", "DELETE"}}
    mutating |= {op for op in operations if op in {"create_watch"}}
    opt_in = {tool_name(c) for c in WATCH_WRITE_TOOLS}
    for op in mutating:
        assert op in UNMAPPED or OPERATION_TOOLS[op] in opt_in


def test_spec_version_is_pinned(operations: dict[str, Any]) -> None:
    import json

    assert json.loads(SPEC_PATH.read_text())["info"]["version"].startswith("1.")
