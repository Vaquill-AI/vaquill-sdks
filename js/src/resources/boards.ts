import type { RequestOptions, Transport } from "../client.js";
import { PageIterator, type PaginationLimits } from "../pagination.js";
import type { APIPromise } from "../response.js";
import type { QueryOf, ResponseOf } from "../types.js";

/** The corpus sources a watch can subscribe to. Free. */
export class BoardsResource {
  constructor(private readonly t: Transport) {}

  /** `list_boards`. */
  list(
    query?: QueryOf<"list_boards">,
    options?: RequestOptions,
  ): APIPromise<ResponseOf<"list_boards">> {
    return this.t.request({ method: "GET", path: "/api/v1/boards", query }, options);
  }

  /** Iterate all boards by offset. */
  listAll(query?: QueryOf<"list_boards">, limits?: PaginationLimits, options?: RequestOptions) {
    return new PageIterator(
      query?.offset ?? 0,
      (offset) => this.list({ ...query, offset }, options),
      (page) => page.data?.boards ?? [],
      (page, offset) => {
        const n = page.data?.boards?.length ?? 0;
        return page.data?.hasMore && n > 0 ? offset + n : undefined;
      },
      limits,
    );
  }
}
