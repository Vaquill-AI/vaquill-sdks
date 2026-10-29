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

/** A stable identity for a cursor, so a cycle (A, B, A) or a repeated offset can be spotted. */
function cursorKey(cursor: unknown): string {
  if (cursor !== null && typeof cursor === "object") return `o:${JSON.stringify(cursor)}`;
  return `${typeof cursor}:${String(cursor)}`;
}

export class PageIterator<Item, Page, Cursor> implements AsyncIterable<Item> {
  #truncated = false;
  #stuck = false;
  /** True when the page last yielded has a (not yet visited) successor. */
  #moreAfterPage = false;

  constructor(
    private readonly first: Cursor,
    private readonly fetchPage: (cursor: Cursor) => Promise<Page>,
    private readonly itemsOf: (page: Page) => readonly Item[],
    /** The cursor for the next page, or undefined when this was the last. */
    private readonly nextOf: (page: Page, cursor: Cursor) => Cursor | undefined,
    private readonly limits: PaginationLimits = {},
  ) {}

  /**
   * True when the last walk stopped at `maxPages` or `maxItems` while the API still had more
   * data. Read it after the loop; it is reset at the start of every walk.
   */
  get truncated(): boolean {
    return this.#truncated;
  }

  /**
   * True when the last walk stopped because the API handed back a cursor or offset it had
   * already served (a cycle such as A, B, A, or an offset that does not advance). The walk
   * stops instead of looping and billing every time. The data may be incomplete.
   */
  get stuck(): boolean {
    return this.#stuck;
  }

  /** Walk page by page, for callers who want to control cost. */
  async *pages(): AsyncGenerator<Page> {
    const { maxPages } = this.limits;
    this.#truncated = false;
    this.#stuck = false;
    this.#moreAfterPage = false;
    if (maxPages !== undefined && maxPages <= 0) {
      this.#truncated = true;
      return;
    }
    const seen = new Set<string>([cursorKey(this.first)]);
    let cursor: Cursor = this.first;
    for (let n = 1; ; n++) {
      const page = await this.fetchPage(cursor);
      const next = this.nextOf(page, cursor);
      const repeated = next !== undefined && seen.has(cursorKey(next));
      this.#moreAfterPage = next !== undefined && !repeated;
      yield page;
      if (next === undefined) return;
      // A cursor or offset already served would loop forever (and bill every time).
      if (repeated) {
        this.#stuck = true;
        return;
      }
      if (maxPages !== undefined && n >= maxPages) {
        this.#truncated = true;
        return;
      }
      seen.add(cursorKey(next));
      cursor = next;
    }
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<Item> {
    const { maxItems } = this.limits;
    if (maxItems !== undefined && maxItems <= 0) {
      this.#truncated = true;
      this.#stuck = false;
      return;
    }
    let count = 0;
    for await (const page of this.pages()) {
      const items = this.itemsOf(page);
      for (let i = 0; i < items.length; i++) {
        yield items[i] as Item;
        if (maxItems !== undefined && ++count >= maxItems) {
          // The generator is closed here, so say now whether anything was left behind.
          this.#truncated = i < items.length - 1 || this.#moreAfterPage;
          return;
        }
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
