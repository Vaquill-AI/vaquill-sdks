"""Every operation in openapi/vaquill-us.json is exposed by a tool or explicitly unmapped."""

from typing import Dict, Set

from fake_server import load_spec

from llama_index.tools.vaquill._operations import READ_TOOL_OPERATIONS, UNMAPPED_OPERATIONS, WATCH_TOOL_OPERATIONS
from llama_index.tools.vaquill.base import _READ_FUNCTIONS, _WATCH_FUNCTIONS, VaquillToolSpec

# Operations that change or trigger something outside the read path.
MUTATING = {"create_watch", "update_watch", "delete_watch", "test_watch"}


def _spec_operations() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path, ops in load_spec()["paths"].items():
        for method, operation in ops.items():
            out[operation["operationId"]] = f"{method.upper()} {path}"
    return out


def _mapped(table: Dict[str, list]) -> Set[str]:
    return {op for ops in table.values() for op in ops}


def test_every_spec_operation_is_exposed_or_unmapped() -> None:
    spec_ops = set(_spec_operations())
    covered = _mapped(READ_TOOL_OPERATIONS) | _mapped(WATCH_TOOL_OPERATIONS) | set(UNMAPPED_OPERATIONS)
    assert spec_ops - covered == set(), (
        f"new spec operations need a tool or an UNMAPPED reason: {sorted(spec_ops - covered)}"
    )
    assert covered - spec_ops == set(), f"mapped operations missing from the spec: {sorted(covered - spec_ops)}"


def test_no_operation_is_both_mapped_and_unmapped() -> None:
    mapped = _mapped(READ_TOOL_OPERATIONS) | _mapped(WATCH_TOOL_OPERATIONS)
    assert mapped & set(UNMAPPED_OPERATIONS) == set()


def test_unmapped_reasons_are_real_sentences() -> None:
    for op, reason in UNMAPPED_OPERATIONS.items():
        assert len(reason) > 20, op
        assert "—" not in reason


def test_read_tools_expose_no_mutating_operation() -> None:
    assert not MUTATING & _mapped(READ_TOOL_OPERATIONS)
    assert _mapped(WATCH_TOOL_OPERATIONS) <= MUTATING


def test_mapping_tables_match_the_spec_function_lists() -> None:
    assert [name for name, _ in _READ_FUNCTIONS] == list(READ_TOOL_OPERATIONS)
    assert [name for name, _ in _WATCH_FUNCTIONS] == list(WATCH_TOOL_OPERATIONS)
    for sync_name, async_name in [*_READ_FUNCTIONS, *_WATCH_FUNCTIONS]:
        assert async_name == f"{sync_name}_async"
        assert hasattr(VaquillToolSpec, sync_name) and hasattr(VaquillToolSpec, async_name)


def test_contract_version_is_the_one_we_were_built_against() -> None:
    assert load_spec()["info"]["version"] == "1.0.0"
