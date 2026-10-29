import type { RequestOptions } from "../client.js";

/** Options for the `*All` batch helpers: the usual request options plus the chunk size. */
export interface BatchAllOptions extends RequestOptions {
  /**
   * Items per request. Defaults to the API's per-call cap for that route. Values above the cap
   * are clamped to it, so the helper never sends a request the server would refuse.
   */
  chunkSize?: number;
}

/** Split a list into runs of at most `size`. */
export function chunk<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** Drop repeats, keeping the first spelling and the order (the server collapses them too). */
export function distinct<T>(items: readonly T[]): T[] {
  return [...new Set(items)];
}

/** The effective chunk size: the caller's value clamped to `[1, cap]`. */
export function chunkSizeFor(cap: number, requested: number | undefined): number {
  if (requested === undefined) return cap;
  if (!Number.isFinite(requested) || requested < 1) {
    throw new RangeError("chunkSize must be a positive number.");
  }
  return Math.min(Math.floor(requested), cap);
}

/**
 * Per-chunk request options. A caller-supplied idempotency key is kept for chunk 0 and suffixed
 * `-N` for later chunks, because one key cannot be reused for different bodies.
 */
export function chunkOptions(
  options: BatchAllOptions | undefined,
  index: number,
): RequestOptions | undefined {
  if (!options) return undefined;
  const { chunkSize: _ignored, ...rest } = options;
  // Chunk 0 keeps the caller's key as given, so a single-chunk call is the plain call.
  if (typeof rest.idempotencyKey === "string" && index > 0) {
    rest.idempotencyKey = `${rest.idempotencyKey}-${index}`;
  }
  return rest;
}

/**
 * Run `call` over each chunk, one at a time, and return the rows of every chunk as one flat
 * list in order. Sequential on purpose: each chunk goes through the normal request path, so
 * the client's spend guard is checked before every chunk and stops the run part way instead of
 * after all of them were in flight. Chunks that finished stay charged when a later one throws.
 * Empty input sends nothing.
 */
export async function runChunks<Item, Row>(
  items: readonly Item[],
  size: number,
  options: BatchAllOptions | undefined,
  call: (
    part: Item[],
    opts: RequestOptions | undefined,
  ) => Promise<readonly Row[] | null | undefined>,
): Promise<Row[]> {
  const out: Row[] = [];
  const chunks = chunk(items, size);
  for (let i = 0; i < chunks.length; i++) {
    const rows = await call(chunks[i] as Item[], chunkOptions(options, i));
    if (rows) out.push(...rows);
  }
  return out;
}
