/**
 * Auto-pagination. The API has four paging styles (offset with `nextOffset`, `cursor` /
 * `nextCursor`, `sinceId` / `beforeId`, and `meta.cursor`); the iterators hide them.
 *
 * Charged endpoints spend credits on EVERY page. An iterator without `maxPages`, `maxItems` or a
 * client-level `maxCredits` runs until the data ends.
 */
export interface PaginationLimits {
  /** Stop after this many pages (requests). */
  maxPages?: number;
  /** Stop after yielding this many items. */
  maxItems?: number;
}

export class PageIterator<Item, Page, Cursor> implements AsyncIterable<Item> {
  constructor(
    private readonly first: Cursor,
    private readonly fetchPage: (cursor: Cursor) => Promise<Page>,
    private readonly itemsOf: (page: Page) => readonly Item[],
    /** The cursor for the next page, or undefined when this was the last. */
    private readonly nextOf: (page: Page, cursor: Cursor) => Cursor | undefined,
    private readonly limits: PaginationLimits = {},
  ) {}

  /** Walk page by page, for callers who want to control cost. */
  async *pages(): AsyncGenerator<Page> {
    const { maxPages } = this.limits;
    let cursor: Cursor = this.first;
    for (let n = 0; maxPages === undefined || n < maxPages; n++) {
      const page = await this.fetchPage(cursor);
      yield page;
      const next = this.nextOf(page, cursor);
      // A cursor that does not advance would loop forever (and bill every time).
      if (next === undefined || next === cursor) return;
      cursor = next;
    }
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<Item> {
    const { maxItems } = this.limits;
    if (maxItems !== undefined && maxItems <= 0) return;
    let count = 0;
    for await (const page of this.pages()) {
      for (const item of this.itemsOf(page)) {
        yield item;
        if (maxItems !== undefined && ++count >= maxItems) return;
      }
    }
  }

  /** Collect everything into an array. Mind the cost of charged endpoints. */
  async toArray(): Promise<Item[]> {
    const out: Item[] = [];
    for await (const item of this) out.push(item);
    return out;
  }
}

type Maybe<T> = T | null | undefined;

/** Offset style: follow `nextOffset` when the server sends it, else `offset + count`. */
export function nextByOffset(
  page: {
    hasMore?: Maybe<boolean>;
    nextOffset?: Maybe<number>;
    count?: Maybe<number>;
    results?: Maybe<readonly unknown[]>;
  },
  offset: number,
): number | undefined {
  if (!page.hasMore) return undefined;
  if (typeof page.nextOffset === "number") return page.nextOffset;
  const count = page.count ?? page.results?.length ?? 0;
  return count > 0 ? offset + count : undefined;
}

/** Cursor style: follow `nextCursor` until it is null. */
export function nextByCursor(cursor: Maybe<string>): string | undefined {
  return cursor ? cursor : undefined;
}

/** Forward change feeds: send the highest `id` seen back as `sinceId`. */
export function nextBySinceId(hasMore: Maybe<boolean>, cursor: Maybe<number>): number | undefined {
  return hasMore && typeof cursor === "number" ? cursor : undefined;
}

/** Newest-first change feeds: send the smallest `id` seen back as `beforeId`. */
export function nextByBeforeId(
  hasMore: Maybe<boolean>,
  changes: Maybe<readonly { id?: Maybe<number> }[]>,
): number | undefined {
  if (!hasMore || !changes) return undefined;
  const ids = changes.map((c) => c.id).filter((id): id is number => typeof id === "number");
  return ids.length ? Math.min(...ids) : undefined;
}
