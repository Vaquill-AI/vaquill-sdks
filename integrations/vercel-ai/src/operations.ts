/**
 * Which OpenAPI operations each tool covers, and which read operations are deliberately not
 * exposed (with the reason). A test fails when the OpenAPI document gains a read operation that
 * is in neither list, so a new endpoint is a decision and never an accident.
 */
export const TOOL_OPERATIONS = {
  searchStatutes: "search_statutes",
  getStatuteSection: "get_section",
  getStatuteSectionText: "get_section_body",
  resolveCitation: "resolve_statute_citation",
  resolveCitations: "resolve_statute_citations_batch",
  extractCitations: "extract_statute_citations",
  countSections: "count_statute_sections",
  listDivisions: "list_statute_divisions",
  sectionChanges: "get_section_changes",
  citedBy: "get_section_cited_by",
  definitions: "get_section_definitions",
  neighbors: "get_section_neighbors",
  searchSessionLaws: "search_session_laws",
  getSessionLaw: "get_session_law",
  creditBalance: "get_credit_balance",
} as const;

/** Tools that exist only with `allowWrites: true`. */
export const WRITE_TOOL_OPERATIONS = {
  listWatches: "list_watches",
  createWatch: "create_watch",
  updateWatch: "update_watch",
  deleteWatch: "delete_watch",
  testWatch: "test_watch",
} as const;

/** Read operations with no tool, and why. */
export const UNMAPPED_OPERATIONS = {
  get_pricing:
    "Static price list. The tool descriptions already say which calls cost credits; creditBalance shows the effect.",
  list_boards:
    "Catalogue of watchable sources. Only useful for alert setup, which is a write flow the user drives.",
  list_statutes_coverage:
    "Large catalogue of what the corpus holds. Too big for a model context; use countSections or listDivisions.",
  get_sections_batch:
    "Bulk full-text fetch. Charged per section and easy to overspend in a loop; use getStatuteSectionText for the one or two sections an answer needs.",
  get_section_enactments:
    "Links a section to the session laws that enacted it. Reachable through getSessionLaw and searchSessionLaws; add when asked for.",
  get_section_rulemaking:
    "Federal Register history of a CFR section. Niche and potentially long; not part of the first tool set.",
  get_part_rulemaking:
    "Federal Register history of a CFR part. Niche and potentially long; not part of the first tool set.",
  get_section_cross_state:
    "Cross-state comparison of a section. Result size is unbounded for common topics; not part of the first tool set.",
  list_session_laws:
    "Registry listing, paged by cursor. searchSessionLaws covers discovery with a bounded page.",
  get_session_law_body:
    "Full session law text is paged and an act can be hundreds of pages, each charged. Too easy to overspend in an agent loop.",
  get_session_law_versions:
    "Version history of a session law. Niche; not part of the first tool set.",
  get_session_law_changes:
    "Change feed over the session law registry. A monitoring feed, not a research lookup.",
  get_session_laws_batch:
    "Bulk fetch charged per item. Easy to overspend in an agent loop; use getSessionLaw.",
  list_watch_changes:
    "Alert delivery history. Alert reading belongs in the user's own integration, not an agent loop.",
  get_watch_change_diff:
    "Charged diff of an alert change. Alert reading belongs in the user's own integration.",
  list_watch_deliveries:
    "Delivery log of an alert. Alert reading belongs in the user's own integration.",
} as const;
