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
import { type BatchAllOptions, chunkSizeFor, distinct, runChunks } from "./_batch.js";

/** Per-call cap from the OpenAPI spec (`maxItems` on `ids`). */
export const SESSION_LAWS_BATCH_MAX = 200;

type LawRow = NonNullable<ResponseOf<"get_session_laws_batch">["laws"]>[number];

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

  /**
   * Walk a law's text page by page. Each item is one body page (`text`, `pageStart`, `pageEnd`,
   * ...); concatenate their `text`. Every page is charged, and a long act is hundreds of pages:
   * set `maxPages` or a client `maxCredits`. Stops on a falsy `nextCursor`, `hasMore: false`, or
   * `pageEnd >= totalChars` (`totalPages` is only an estimate and is never a stop condition).
   * `startChar` applies to the first page only; the cursor carries the position after that.
   * `iter.truncated` is true when `maxPages` stopped it with text left.
   */
  iterBody(
    sessionLawId: string,
    query?: QueryOf<"get_session_law_body">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    return new PageIterator(
      query?.cursor ?? undefined,
      (cursor) => {
        const { startChar: _firstPageOnly, ...rest } = query ?? {};
        return this.getBody(
          sessionLawId,
          cursor === undefined ? query : { ...rest, cursor },
          options,
        );
      },
      (page) => [page],
      (page) => {
        if (!page.hasMore) return undefined;
        if (
          typeof page.pageEnd === "number" &&
          typeof page.totalChars === "number" &&
          page.pageEnd >= page.totalChars
        ) {
          return undefined;
        }
        return nextByCursor(page.nextCursor);
      },
      limits,
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

  /**
   * `get_session_laws_batch` over any number of ids or citations. Sends at most 200 (the spec's
   * per-call cap) per request, drops exact repeats, and returns the `laws` of every call as one
   * flat list in order. Ids with no match are dropped (use `getBatch` to see `notFound`).
   * Charged per law; the spend guard is checked before each chunk. Empty input sends nothing.
   */
  getBatchAll(
    ids: readonly string[],
    params?: Omit<BodyOf<"get_session_laws_batch">, "ids">,
    options?: BatchAllOptions,
  ): Promise<LawRow[]> {
    return runChunks(
      distinct(ids),
      chunkSizeFor(SESSION_LAWS_BATCH_MAX, options?.chunkSize),
      options,
      async (part, o) =>
        (await this.getBatch({ ...params, ids: part } as BodyOf<"get_session_laws_batch">, o)).laws,
    );
  }
}
