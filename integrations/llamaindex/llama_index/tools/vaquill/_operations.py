"""Which Vaquill operations the tools cover. A test compares this with ``openapi/vaquill-us.json``."""

from typing import Dict, List

__all__ = ["READ_TOOL_OPERATIONS", "UNMAPPED_OPERATIONS", "WATCH_TOOL_OPERATIONS"]

# Tool name -> operationIds it calls. The retriever also calls search_statutes.
READ_TOOL_OPERATIONS: Dict[str, List[str]] = {
    "search_statutes": ["search_statutes"],
    "get_section": ["get_section", "get_section_body"],
    "resolve_citation": ["resolve_statute_citation"],
    "resolve_citations": ["resolve_statute_citations_batch"],
    "extract_citations": ["extract_statute_citations"],
    "count_sections": ["count_statute_sections"],
    "list_divisions": ["list_statute_divisions"],
    "get_section_changes": ["get_section_changes"],
    "get_cited_by": ["get_section_cited_by"],
    "get_definitions": ["get_section_definitions"],
    "get_neighbors": ["get_section_neighbors"],
    "search_session_laws": ["search_session_laws"],
    "get_session_law": ["get_session_law"],
    "get_credit_balance": ["get_credit_balance"],
}

# Only exposed with VaquillToolSpec(enable_watch_management=True).
WATCH_TOOL_OPERATIONS: Dict[str, List[str]] = {
    "create_watch": ["create_watch"],
    "update_watch": ["update_watch"],
    "delete_watch": ["delete_watch"],
}

_PLANNED = "Not exposed in 0.1.0 to keep the tool list small for the model; the SDK method exists."
UNMAPPED_OPERATIONS: Dict[str, str] = {
    "get_sections_batch": "Agents fetch one section at a time with get_section; the batch form invites large spends.",
    "get_section_cross_state": f"6 credits per call. {_PLANNED}",
    "get_section_enactments": f"Needs the session-law registry. {_PLANNED}",
    "get_section_rulemaking": _PLANNED,
    "get_part_rulemaking": _PLANNED,
    "get_session_law_changes": "Change feed for polling jobs, not for an agent turn.",
    "get_session_laws_batch": "Agents fetch one session law at a time with get_session_law.",
    "get_session_law_body": f"Long, paged text. {_PLANNED}",
    "get_session_law_versions": _PLANNED,
    "list_session_laws": "Bulk listing for ingestion jobs; search_session_laws covers discovery.",
    "get_watch_change_diff": "Charged and tied to webhook workflows, not to an agent turn.",
    "list_watch_changes": "Watch reads belong to webhook workflows; use the SDK directly.",
    "list_watch_deliveries": "Watch reads belong to webhook workflows; use the SDK directly.",
    "list_watches": "Watch reads belong to webhook workflows; use the SDK directly.",
    "test_watch": "Sends a real event to a customer endpoint, a side effect; use the SDK directly.",
    "list_boards": "Reference data for watch setup; use the SDK directly.",
    "list_statutes_coverage": "Large reference table that would flood the model context.",
    "get_pricing": "Large price matrix; the per-tool docstrings state the credit costs.",
}
