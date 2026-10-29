"""Which API operations the toolkit exposes, and why the others are not.

``tests/test_drift.py`` compares these tables with ``openapi/vaquill-us.json`` so a new
operation in the API cannot appear without a decision here.
"""

from __future__ import annotations

__all__ = ["OPERATION_TOOLS", "UNMAPPED"]

#: operationId -> tool name.
OPERATION_TOOLS: dict[str, str] = {
    "search_statutes": "vaquill_search_statutes",
    "get_section": "vaquill_get_statute_section",
    "get_section_body": "vaquill_get_statute_text",
    "resolve_statute_citation": "vaquill_resolve_citation",
    "resolve_statute_citations_batch": "vaquill_resolve_citations",
    "extract_statute_citations": "vaquill_extract_citations",
    "count_statute_sections": "vaquill_count_sections",
    "list_statute_divisions": "vaquill_list_divisions",
    "get_section_changes": "vaquill_section_changes",
    "get_section_cited_by": "vaquill_section_cited_by",
    "get_section_definitions": "vaquill_section_definitions",
    "get_section_neighbors": "vaquill_section_neighbors",
    "get_section_cross_state": "vaquill_section_cross_state",
    "get_section_enactments": "vaquill_section_enactments",
    "get_section_rulemaking": "vaquill_section_rulemaking",
    "list_statutes_coverage": "vaquill_statutes_coverage",
    "search_session_laws": "vaquill_search_session_laws",
    "get_session_law": "vaquill_get_session_law",
    "get_session_law_body": "vaquill_get_session_law_text",
    "get_session_law_versions": "vaquill_session_law_versions",
    "get_credit_balance": "vaquill_credit_balance",
    "get_pricing": "vaquill_get_pricing",
    "list_boards": "vaquill_list_boards",
    "list_watches": "vaquill_list_watches",
    "create_watch": "vaquill_create_watch",
    "update_watch": "vaquill_update_watch",
    "delete_watch": "vaquill_delete_watch",
}

#: operationId -> reason it has no tool.
UNMAPPED: dict[str, str] = {
    "get_sections_batch": (
        "Bulk body fetch (up to 50 sections, 6 credits each). One call can spend hundreds of "
        "credits; the agent should read sections one at a time with vaquill_get_statute_text."
    ),
    "get_session_laws_batch": (
        "Bulk fetch of up to 200 session laws. Same unbounded spend risk as get_sections_batch."
    ),
    "get_part_rulemaking": (
        "Returns every Federal Register document for a whole CFR part, a large payload that "
        "does not fit a model's context. Use vaquill_section_rulemaking per section."
    ),
    "list_session_laws": (
        "Cursor-paged browse of the whole registry. Search (vaquill_search_session_laws) is the "
        "agent-shaped way in; the listing suits ETL, not an agent."
    ),
    "get_session_law_changes": "Change-feed polling for pipelines, not an agent question.",
    "list_watch_changes": "Watch event feed for webhook consumers; deferred from 0.1.0.",
    "list_watch_deliveries": "Delivery log for webhook operators; deferred from 0.1.0.",
    "get_watch_change_diff": "Charged diff of one watch change; deferred from 0.1.0.",
    "test_watch": (
        "Sends a real test delivery to the watch's webhook or inbox. An outbound side effect "
        "that an agent should not trigger on its own."
    ),
}
