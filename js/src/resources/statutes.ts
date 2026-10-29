import type { RequestOptions, Transport } from "../client.js";
import {
  nextByBeforeId,
  nextByCursor,
  nextByOffset,
  nextBySinceId,
  PageIterator,
  type PaginationLimits,
} from "../pagination.js";
import type { APIPromise } from "../response.js";
import type { BodyOf, QueryOf, ResponseOf } from "../types.js";

const BASE = "/api/v1/us/statutes";
const sec = (actId: string) => `${BASE}/section/${encodeURIComponent(actId)}`;

/**
 * US statutes, regulations, rules and constitutions. Every method here except `coverage`
 * consumes credits. The `*All` iterators spend credits PER PAGE: set `maxPages`, `maxItems`
 * or a client `maxCredits`.
 */
export class StatutesResource {
  constructor(private readonly t: Transport) {}

  /** `search_statutes`. Charged. */
  search(
    body: BodyOf<"search_statutes">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"search_statutes">> {
    return this.t.request({ method: "POST", path: `${BASE}/search`, body, charged: true }, options);
  }

  /** Iterate every result of a search, following `nextOffset`. Each page is a new charged search. */
  searchAll(body: BodyOf<"search_statutes">, limits?: PaginationLimits, options?: RequestOptions) {
    return new PageIterator(
      body.offset ?? 0,
      (offset) => this.search({ ...body, offset }, options),
      (page) => page.results ?? [],
      (page, offset) => nextByOffset(page, offset),
      limits,
    );
  }

  /** `get_section`. Charged. */
  getSection(actId: string, options?: RequestOptions): APIPromise<ResponseOf<"get_section">> {
    return this.t.request({ method: "GET", path: sec(actId), charged: true }, options);
  }

  /** `get_section_body`. Charged. */
  getSectionBody(
    actId: string,
    query?: QueryOf<"get_section_body">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_body">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/body`, query, charged: true },
      options,
    );
  }

  /** `get_section_neighbors`. Charged. */
  getSectionNeighbors(
    actId: string,
    query?: QueryOf<"get_section_neighbors">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_neighbors">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/related`, query, charged: true },
      options,
    );
  }

  /** `get_sections_batch`. Charged per section returned. */
  getSections(
    body: BodyOf<"get_sections_batch">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_sections_batch">> {
    return this.t.request(
      { method: "POST", path: `${BASE}/sections`, body, charged: true },
      options,
    );
  }

  /** `count_statute_sections`. Charged. */
  count(
    body: BodyOf<"count_statute_sections">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"count_statute_sections">> {
    return this.t.request({ method: "POST", path: `${BASE}/count`, body, charged: true }, options);
  }

  /** `list_statutes_coverage`. Free. */
  coverage(
    query?: QueryOf<"list_statutes_coverage">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_statutes_coverage">> {
    return this.t.request({ method: "GET", path: `${BASE}/coverage`, query }, options);
  }

  /** `list_statute_divisions`. Charged. */
  listDivisions(
    query: QueryOf<"list_statute_divisions">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_statute_divisions">> {
    return this.t.request(
      { method: "GET", path: `${BASE}/divisions`, query, charged: true },
      options,
    );
  }

  /** Iterate divisions, following `nextCursor`. Charged per page. */
  listDivisionsAll(
    query: QueryOf<"list_statute_divisions">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    return new PageIterator(
      query.cursor ?? undefined,
      (cursor) => this.listDivisions({ ...query, cursor }, options),
      (page) => page.divisions ?? [],
      (page) => nextByCursor(page.nextCursor),
      limits,
    );
  }

  /** `get_section_changes`. Charged. */
  getSectionChanges(
    actId: string,
    query?: QueryOf<"get_section_changes">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_changes">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/changes`, query, charged: true },
      options,
    );
  }

  /**
   * Iterate a section's change history. Newest first (the default) walks back with `beforeId`;
   * `order: "asc"` or a `sinceId` walks forward. Charged per page.
   */
  getSectionChangesAll(
    actId: string,
    query?: QueryOf<"get_section_changes">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    const forward = query?.order === "asc" || (query?.sinceId ?? null) !== null;
    return new PageIterator(
      undefined as number | undefined,
      (id) =>
        this.getSectionChanges(
          actId,
          id === undefined
            ? query
            : { ...query, ...(forward ? { sinceId: id } : { beforeId: id }) },
          options,
        ),
      (page) => page.changes ?? [],
      (page) =>
        forward
          ? nextBySinceId(page.hasMore, page.cursor)
          : nextByBeforeId(page.hasMore, page.changes),
      limits,
    );
  }

  /** `get_section_enactments`. Charged. */
  getSectionEnactments(
    actId: string,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_enactments">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/enactments`, charged: true },
      options,
    );
  }

  /** `get_section_rulemaking`. Charged. Federal Register documents behind one CFR section. */
  getSectionRulemaking(
    actId: string,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_rulemaking">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/rulemaking`, charged: true },
      options,
    );
  }

  /** `get_part_rulemaking`. Charged. Every Federal Register document for a CFR part. */
  getPartRulemaking(
    title: number,
    part: string,
    query?: QueryOf<"get_part_rulemaking">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_part_rulemaking">> {
    return this.t.request(
      {
        method: "GET",
        path: `${BASE}/part/${encodeURIComponent(String(title))}/${encodeURIComponent(part)}/rulemaking`,
        query,
        charged: true,
      },
      options,
    );
  }

  /** `get_section_cited_by`. Charged. */
  getSectionCitedBy(
    actId: string,
    query?: QueryOf<"get_section_cited_by">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_cited_by">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/cited-by`, query, charged: true },
      options,
    );
  }

  /** `get_section_definitions`. Charged. */
  getSectionDefinitions(
    actId: string,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_definitions">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/definitions`, charged: true },
      options,
    );
  }

  /** `get_section_cross_state`. Charged. */
  getSectionCrossState(
    actId: string,
    query?: QueryOf<"get_section_cross_state">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_section_cross_state">> {
    return this.t.request(
      { method: "GET", path: `${sec(actId)}/cross-state`, query, charged: true },
      options,
    );
  }

  /** `resolve_statute_citation`. Charged. */
  resolve(
    query: QueryOf<"resolve_statute_citation">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"resolve_statute_citation">> {
    return this.t.request(
      { method: "GET", path: `${BASE}/resolve`, query, charged: true },
      options,
    );
  }

  /** `resolve_statute_citations_batch`. Charged per citation. */
  resolveBatch(
    body: BodyOf<"resolve_statute_citations_batch">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"resolve_statute_citations_batch">> {
    return this.t.request(
      { method: "POST", path: `${BASE}/resolve`, body, charged: true },
      options,
    );
  }

  /** `extract_statute_citations`. Charged per distinct citation. */
  extractCitations(
    body: BodyOf<"extract_statute_citations">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"extract_statute_citations">> {
    return this.t.request(
      { method: "POST", path: `${BASE}/extract-citations`, body, charged: true },
      options,
    );
  }
}
