export interface RateLimitInfo {
  /** `X-RateLimit-Limit`: requests per minute. */
  limit?: number;
  /** `X-RateLimit-Remaining`: requests left in the minute window. */
  remaining?: number;
  /** `X-RateLimit-Limit-Day`. */
  limitDay?: number;
  /** `X-RateLimit-Remaining-Day`. */
  remainingDay?: number;
  /** `X-RateLimit-Reset`: Unix timestamp at which the per-minute window resets. */
  reset?: number;
}

export interface ResponseMeta {
  status: number;
  headers: Headers;
  /** `X-Request-ID`, quote it to support. */
  requestId: string | null;
  /** Credits this response reports (`creditsConsumed` in the body), when it has one. */
  creditsConsumed: number | undefined;
  /** True when the server replayed a stored response (`Idempotent-Replayed`): nothing new was charged. */
  idempotentReplayed: boolean;
  rateLimit: RateLimitInfo;
  /** How many retries preceded this response. */
  retries: number;
}

export interface WithResponse<T> {
  data: T;
  /** The raw `Response`. Its body is already consumed; use `data`. */
  response: Response;
  meta: ResponseMeta;
}

function num(headers: Headers, name: string): number | undefined {
  const v = headers.get(name);
  if (v === null || v.trim() === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export function parseRateLimit(headers: Headers): RateLimitInfo {
  const info: RateLimitInfo = {};
  const set = (k: keyof RateLimitInfo, name: string) => {
    const v = num(headers, name);
    if (v !== undefined) info[k] = v;
  };
  set("limit", "x-ratelimit-limit");
  set("remaining", "x-ratelimit-remaining");
  set("limitDay", "x-ratelimit-limit-day");
  set("remainingDay", "x-ratelimit-remaining-day");
  set("reset", "x-ratelimit-reset");
  return info;
}

/** `creditsConsumed` from the body: top level for statutes and session laws, `meta` for watches. */
export function creditsFromBody(body: unknown): number | undefined {
  if (typeof body !== "object" || body === null) return undefined;
  const top = (body as { creditsConsumed?: unknown }).creditsConsumed;
  if (typeof top === "number") return top;
  const meta = (body as { meta?: { creditsConsumed?: unknown } }).meta;
  return typeof meta?.creditsConsumed === "number" ? meta.creditsConsumed : undefined;
}

/** The `Deprecation` and `Sunset` headers of a response, or null when it carries neither. */
export function deprecationInfo(
  headers: Headers,
): { deprecation?: string; sunset?: string } | null {
  const deprecation = headers.get("deprecation") ?? undefined;
  const sunset = headers.get("sunset") ?? undefined;
  if (deprecation === undefined && sunset === undefined) return null;
  return { deprecation, sunset };
}

export function buildMeta(response: Response, body: unknown, retries: number): ResponseMeta {
  const { headers } = response;
  return {
    status: response.status,
    headers,
    requestId: headers.get("x-request-id"),
    creditsConsumed: creditsFromBody(body),
    idempotentReplayed: headers.get("idempotent-replayed")?.toLowerCase() === "true",
    rateLimit: parseRateLimit(headers),
    retries,
  };
}

/**
 * A promise for the parsed body that also offers `.withResponse()`. Awaiting it yields the
 * typed body only; the extra metadata costs nothing unless asked for.
 */
export class APIPromise<T> extends Promise<T> {
  readonly #inner: Promise<WithResponse<T>>;

  constructor(inner: Promise<WithResponse<T>>) {
    super((resolve) => resolve(undefined as T));
    this.#inner = inner;
  }

  static override get [Symbol.species](): PromiseConstructor {
    return Promise;
  }

  /** Resolve to the body together with the response, request id, credits and rate limits. */
  withResponse(): Promise<WithResponse<T>> {
    return this.#inner;
  }

  // biome-ignore lint/suspicious/noThenProperty: APIPromise is a deliberate thenable
  override then<R1 = T, R2 = never>(
    onfulfilled?: ((value: T) => R1 | PromiseLike<R1>) | null,
    onrejected?: ((reason: unknown) => R2 | PromiseLike<R2>) | null,
  ): Promise<R1 | R2> {
    return this.#inner.then((r) => r.data).then(onfulfilled, onrejected);
  }

  override catch<R = never>(
    onrejected?: ((reason: unknown) => R | PromiseLike<R>) | null,
  ): Promise<T | R> {
    return this.then(undefined, onrejected);
  }

  override finally(onfinally?: (() => void) | null): Promise<T> {
    return this.#inner.then((r) => r.data).finally(onfinally);
  }
}
