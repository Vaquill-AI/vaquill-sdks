import type { RequestOptions, Transport } from "../client.js";
import {
  nextByBeforeId,
  nextBySinceId,
  PageIterator,
  type PaginationLimits,
} from "../pagination.js";
import type { APIPromise } from "../response.js";
import type { BodyOf, QueryOf, ResponseOf } from "../types.js";

const BASE = "/api/v1/watches";
const one = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

/** Law-change alerts (board watches). Free, except `getChangeDiff`. */
export class WatchesResource {
  constructor(private readonly t: Transport) {}

  /** `list_watches`. */
  list(
    query?: QueryOf<"list_watches">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_watches">> {
    return this.t.request({ method: "GET", path: BASE, query }, options);
  }

  /** Iterate all watches by offset. */
  listAll(query?: QueryOf<"list_watches">, limits?: PaginationLimits, options?: RequestOptions) {
    const size = query?.limit;
    return new PageIterator(
      query?.offset ?? 0,
      (offset) => this.list({ ...query, offset }, options),
      (page) => page.data?.watches ?? [],
      (page, offset) => {
        const n = page.data?.watches?.length ?? 0;
        // No hasMore on this envelope: a short or empty page is the last one.
        return n > 0 && (size === undefined || n >= size) ? offset + n : undefined;
      },
      limits,
    );
  }

  /** `create_watch`. Not idempotent: a failed attempt is not retried after an ambiguous failure. */
  create(
    body: BodyOf<"create_watch">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"create_watch">> {
    return this.t.request({ method: "POST", path: BASE, body }, options);
  }

  /** `update_watch`. */
  update(
    watchId: string,
    body: BodyOf<"update_watch">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"update_watch">> {
    return this.t.request({ method: "PATCH", path: one(watchId), body }, options);
  }

  /** `delete_watch`. Resolves to undefined (204). */
  delete(watchId: string, options?: RequestOptions): APIPromise<void> {
    return this.t.request({ method: "DELETE", path: one(watchId) }, options);
  }

  /** `test_watch`: sends a test delivery. Not retried after an ambiguous failure. */
  test(watchId: string, options?: RequestOptions): APIPromise<ResponseOf<"test_watch">> {
    return this.t.request({ method: "POST", path: `${one(watchId)}/test` }, options);
  }

  /** `list_watch_changes`. */
  listChanges(
    watchId: string,
    query?: QueryOf<"list_watch_changes">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_watch_changes">> {
    return this.t.request({ method: "GET", path: `${one(watchId)}/changes`, query }, options);
  }

  /** Iterate a watch's changes. `order: "asc"` or `sinceId` walks forward, else back by `beforeId`. */
  listChangesAll(
    watchId: string,
    query?: QueryOf<"list_watch_changes">,
    limits?: PaginationLimits,
    options?: RequestOptions,
  ) {
    const forward = query?.order === "asc" || (query?.sinceId ?? null) !== null;
    return new PageIterator(
      undefined as number | undefined,
      (id) =>
        this.listChanges(
          watchId,
          id === undefined
            ? query
            : { ...query, ...(forward ? { sinceId: id } : { beforeId: id }) },
          options,
        ),
      (page) => page.data?.changes ?? [],
      (page) =>
        forward
          ? nextBySinceId(page.meta?.hasMore, page.meta?.cursor)
          : nextByBeforeId(page.meta?.hasMore, page.data?.changes),
      limits,
    );
  }

  /** `get_watch_change_diff`. Charged. */
  getChangeDiff(
    watchId: string,
    changeId: string | number,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"get_watch_change_diff">> {
    return this.t.request(
      {
        method: "GET",
        path: `${one(watchId)}/changes/${encodeURIComponent(String(changeId))}/diff`,
        charged: true,
      },
      options,
    );
  }

  /** `list_watch_deliveries`. */
  listDeliveries(
    watchId: string,
    query?: QueryOf<"list_watch_deliveries">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_watch_deliveries">> {
    return this.t.request({ method: "GET", path: `${one(watchId)}/deliveries`, query }, options);
  }
}
