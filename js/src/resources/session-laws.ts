import type { RequestOptions, Transport } from "../client.js";
import {
  nextByCursor,
  nextByOffset,
  nextBySinceId,
  PageIterator,
  type PaginationLimits,
} from "../pagination.js";
import type { APIPromise } from "../response.js";
import type { BodyOf, QueryOf, ResponseOf } from "../types.js";

const BASE = "/api/v1/us/session-laws";
const one = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

/** US session laws (acts as enacted). Every method consumes credits. */
export class SessionLawsResource {
  constructor(private readonly t: Transport) {}

  /** `search_session_laws`. Charged per page. */
  search(
    body: BodyOf<"search_session_laws">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"search_session_laws">> {
    return this.t.request({ method: "POST", path: `${BASE}/search`, body, charged: true }, options);
  }

  /** Iterate every search result. Each page is a new charged search. */
  searchAll(
    body: BodyOf<"search_session_laws">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    return new PageIterator(
      body.offset ?? 0,
      (offset) => this.search({ ...body, offset }, options),
      (page) => page.results ?? [],
      (page, offset) => nextByOffset(page, offset),
      limits,
    );
  }

  /** `list_session_laws`. Charged per page. */
  list(
    query: QueryOf<"list_session_laws">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_session_laws">> {
    return this.t.request({ method: "GET", path: `${BASE}/list`, query, charged: true }, options);
  }

  /** Iterate the registry, following `nextCursor`. Charged per page. */
  listAll(
    query: QueryOf<"list_session_laws">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    return new PageIterator(
      query.cursor ?? undefined,
      (cursor) => this.list({ ...query, cursor }, options),
      (page) => page.results ?? [],
      (page) => (page.hasMore ? nextByCursor(page.nextCursor) : undefined),
      limits,
    );
  }

  /** `get_session_law`. Charged. */
  get(
    sessionLawId: string,
    query?: QueryOf<"get_session_law">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_session_law">> {
    return this.t.request(
      { method: "GET", path: one(sessionLawId), query, charged: true },
      options,
    );
  }

  /** `get_session_law_body`. Charged per page served. */
  getBody(
    sessionLawId: string,
    query?: QueryOf<"get_session_law_body">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_session_law_body">> {
    return this.t.request(
      { method: "GET", path: `${one(sessionLawId)}/body`, query, charged: true },
      options,
    );
  }

  /** `get_session_law_versions`. Charged. */
  getVersions(
    sessionLawId: string,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_session_law_versions">> {
    return this.t.request(
      { method: "GET", path: `${one(sessionLawId)}/versions`, charged: true },
      options,
    );
  }

  /** `get_session_law_changes`. Charged per page. */
  getChanges(
    query?: QueryOf<"get_session_law_changes">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_session_law_changes">> {
    return this.t.request(
      { method: "GET", path: `${BASE}/changes`, query, charged: true },
      options,
    );
  }

  /** Iterate the change feed forward with `sinceId`. Charged per page. */
  getChangesAll(
    query?: QueryOf<"get_session_law_changes">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    return new PageIterator(
      query?.sinceId ?? undefined,
      (sinceId) => this.getChanges({ ...query, sinceId }, options),
      (page) => page.changes ?? [],
      (page) => nextBySinceId(page.hasMore, page.cursor),
      limits,
    );
  }

  /** `get_session_laws_batch`. Charged per item. */
  getBatch(
    body: BodyOf<"get_session_laws_batch">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_session_laws_batch">> {
    return this.t.request({ method: "POST", path: `${BASE}/batch`, body, charged: true }, options);
  }
}
