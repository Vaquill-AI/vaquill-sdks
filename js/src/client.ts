import {
  APIConnectionError,
  APITimeoutError,
  APIUserAbortError,
  makeStatusError,
  SpendGuardExceededError,
  VaquillError,
} from "./errors.js";
import { BoardsResource } from "./resources/boards.js";
import { CreditsResource } from "./resources/credits.js";
import { PricingResource } from "./resources/pricing.js";
import { SessionLawsResource } from "./resources/session-laws.js";
import { StatutesResource } from "./resources/statutes.js";
import { WatchesResource } from "./resources/watches.js";
import { APIPromise, buildMeta, type WithResponse } from "./response.js";
import { DEFAULT_MAX_RETRIES, retryDelayMs, shouldRetryStatus } from "./retry.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://api.vaquill.ai";
export const DEFAULT_TIMEOUT_MS = 60_000;
const API_KEY_PREFIX = "vq_key_";

export type Query = Record<string, unknown>;

/** Options accepted by every method as its last argument. */
export interface RequestOptions {
  /** Per-attempt timeout in milliseconds. */
  timeout?: number;
  maxRetries?: number;
  /** Extra headers for this call. */
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /**
   * Charged operations get one generated `Idempotency-Key` per logical call, reused on every
   * retry. Pass your own string to control it, or `false` to send none. With no key, a charged
   * call is never retried after a timeout, connection error or 5xx, because it could charge twice.
   */
  idempotencyKey?: string | false;
}

export interface ClientOptions {
  /** Defaults to `process.env.VAQUILL_API_KEY`. Must start with `vq_key_`. */
  apiKey?: string;
  /** Defaults to `process.env.VAQUILL_BASE_URL`, then `https://api.vaquill.ai`. */
  baseURL?: string;
  /** Per-attempt timeout in milliseconds. Default 60000. */
  timeout?: number;
  /** Default 2. */
  maxRetries?: number;
  defaultHeaders?: Record<string, string>;
  /** Injected `fetch` (proxies, test doubles). Defaults to the global. */
  fetch?: typeof fetch;
  /**
   * Spend guard. Once the credits reported by responses on this client reach this number,
   * further charged calls throw `SpendGuardExceededError` before any request is sent.
   * The check uses what was already spent, not the cost of the next call.
   */
  maxCredits?: number;
}

interface RequestSpec {
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  path: string;
  query?: Query;
  body?: unknown;
  /** The operation consumes credits (it declares an `Idempotency-Key` header in the spec). */
  charged?: boolean;
}

/** What resources need from the client. */
export interface Transport {
  request<T>(spec: RequestSpec, options?: RequestOptions): APIPromise<T>;
}

interface Resolved {
  apiKey: string;
  baseURL: string;
  timeout: number;
  maxRetries: number;
  defaultHeaders: Record<string, string>;
  fetch: typeof fetch;
  maxCredits: number | undefined;
}

const INSPECT = Symbol.for("nodejs.util.inspect.custom");
let browserWarned = false;

export class Vaquill implements Transport {
  // Private field: absent from Object.keys, JSON.stringify and util.inspect.
  readonly #apiKey: string;
  readonly #cfg: Omit<Resolved, "apiKey">;
  readonly #spent: { credits: number };

  readonly statutes: StatutesResource;
  readonly sessionLaws: SessionLawsResource;
  readonly watches: WatchesResource;
  readonly boards: BoardsResource;
  readonly credits: CreditsResource;
  readonly pricing: PricingResource;

  constructor(options: ClientOptions = {}, spent: { credits: number } = { credits: 0 }) {
    const env = globalThis.process?.env ?? {};
    const apiKey = options.apiKey || env.VAQUILL_API_KEY;
    if (!apiKey) {
      throw new VaquillError(
        "No API key. Pass `apiKey` or set the VAQUILL_API_KEY environment variable.",
      );
    }
    if (!apiKey.startsWith(API_KEY_PREFIX)) {
      throw new VaquillError(`Invalid API key: Vaquill keys start with "${API_KEY_PREFIX}".`);
    }
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") {
      throw new VaquillError("No global `fetch` found. Pass one in the `fetch` option.");
    }
    this.#apiKey = apiKey;
    this.#spent = spent;
    this.#cfg = {
      baseURL: (options.baseURL || env.VAQUILL_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
      timeout: options.timeout ?? DEFAULT_TIMEOUT_MS,
      maxRetries: options.maxRetries ?? DEFAULT_MAX_RETRIES,
      defaultHeaders: { ...options.defaultHeaders },
      fetch: fetchImpl.bind(globalThis),
      maxCredits: options.maxCredits,
    };
    if (!browserWarned && typeof window !== "undefined" && typeof document !== "undefined") {
      browserWarned = true;
      console.warn(
        "[vaquill] A vq_key_ API key is being used in a browser. Anyone can read it. " +
          "Call the API from your server instead.",
      );
    }
    this.statutes = new StatutesResource(this);
    this.sessionLaws = new SessionLawsResource(this);
    this.watches = new WatchesResource(this);
    this.boards = new BoardsResource(this);
    this.credits = new CreditsResource(this);
    this.pricing = new PricingResource(this);
  }

  /** Credits reported by responses on this client (and clients derived from it). */
  get creditsSpent(): number {
    return this.#spent.credits;
  }

  /** A derived client with some options replaced. It shares the key and the spend counter. */
  withOptions(options: Omit<ClientOptions, "apiKey"> = {}): Vaquill {
    return new Vaquill(
      {
        apiKey: this.#apiKey,
        baseURL: this.#cfg.baseURL,
        timeout: this.#cfg.timeout,
        maxRetries: this.#cfg.maxRetries,
        fetch: this.#cfg.fetch,
        maxCredits: this.#cfg.maxCredits,
        ...options,
        defaultHeaders: { ...this.#cfg.defaultHeaders, ...options.defaultHeaders },
      },
      this.#spent,
    );
  }

  /** Call an endpoint this SDK version does not wrap yet. Set `charged` if it consumes credits. */
  rawRequest<T = unknown>(
    method: RequestSpec["method"],
    path: string,
    init: { query?: Query; body?: unknown; charged?: boolean } & RequestOptions = {},
  ): APIPromise<T> {
    const { query, body, charged, ...options } = init;
    return this.request<T>({ method, path, query, body, charged }, options);
  }

  toJSON(): Record<string, unknown> {
    return { baseURL: this.#cfg.baseURL, timeout: this.#cfg.timeout, apiKey: "[redacted]" };
  }

  [INSPECT](): string {
    return `Vaquill { baseURL: '${this.#cfg.baseURL}', apiKey: '[redacted]' }`;
  }

  request<T>(spec: RequestSpec, options: RequestOptions = {}): APIPromise<T> {
    return new APIPromise<T>(this.#send<T>(spec, options));
  }

  async #send<T>(spec: RequestSpec, options: RequestOptions): Promise<WithResponse<T>> {
    const cfg = this.#cfg;
    const charged = spec.charged === true;
    if (charged && cfg.maxCredits !== undefined && this.#spent.credits >= cfg.maxCredits) {
      throw new SpendGuardExceededError(
        `Spend guard: ${this.#spent.credits} credits spent, limit is ${cfg.maxCredits}.`,
      );
    }
    const maxRetries = options.maxRetries ?? cfg.maxRetries;
    const timeout = options.timeout ?? cfg.timeout;

    let idemKey: string | undefined;
    if (charged && options.idempotencyKey !== false) {
      idemKey = options.idempotencyKey ?? globalThis.crypto.randomUUID();
    }
    // Repeating the call cannot double-charge or double-create.
    const replaySafe = idemKey !== undefined || (!charged && spec.method !== "POST");

    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(typeof window === "undefined" ? { "User-Agent": `vaquill-js/${VERSION}` } : {}),
      ...cfg.defaultHeaders,
      ...options.headers,
      Authorization: `Bearer ${this.#apiKey}`,
    };
    let payload: string | undefined;
    if (spec.body !== undefined) {
      payload = JSON.stringify(spec.body);
      headers["Content-Type"] = "application/json";
    }
    if (idemKey) headers["Idempotency-Key"] = idemKey;
    const url = buildURL(cfg.baseURL, spec.path, spec.query);

    for (let attempt = 0; ; attempt++) {
      const canRetry = attempt < maxRetries;
      let response: Response;
      let body: unknown;
      try {
        ({ response, body } = await fetchOnce(
          cfg.fetch,
          url,
          spec.method,
          headers,
          payload,
          timeout,
          options.signal,
        ));
      } catch (err) {
        if (err instanceof APIUserAbortError) throw err;
        if (canRetry && replaySafe) {
          const delay = retryDelayMs(attempt);
          if (delay !== null) {
            await sleep(delay, options.signal);
            continue;
          }
        }
        throw err;
      }

      if (response.ok) {
        const meta = buildMeta(response, body, attempt);
        if (meta.creditsConsumed && !meta.idempotentReplayed) {
          this.#spent.credits += meta.creditsConsumed;
        }
        return { data: body as T, response, meta };
      }
      const error = makeStatusError(response.status, body, response.headers);
      if (canRetry && shouldRetryStatus(error, replaySafe)) {
        const delay = retryDelayMs(attempt, response.headers, error.retryAfterSeconds);
        if (delay !== null) {
          await sleep(delay, options.signal);
          continue;
        }
      }
      throw error;
    }
  }
}

function buildURL(base: string, path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item === undefined || item === null) continue;
      params.append(key, typeof item === "object" ? JSON.stringify(item) : String(item));
    }
  }
  const qs = params.toString();
  return `${base}${path}${qs ? `?${qs}` : ""}`;
}

async function fetchOnce(
  fetchImpl: typeof fetch,
  url: string,
  method: string,
  headers: Record<string, string>,
  body: string | undefined,
  timeoutMs: number,
  userSignal: AbortSignal | undefined,
): Promise<{ response: Response; body: unknown }> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onUserAbort = () => controller.abort();
  if (userSignal?.aborted) onUserAbort();
  userSignal?.addEventListener("abort", onUserAbort, { once: true });
  try {
    const response = await fetchImpl(url, { method, headers, body, signal: controller.signal });
    return { response, body: await readBody(response) };
  } catch (err) {
    if (userSignal?.aborted) throw new APIUserAbortError({ cause: err });
    if (timedOut) throw new APITimeoutError({ cause: err });
    throw new APIConnectionError(undefined, { cause: err });
  } finally {
    clearTimeout(timer);
    userSignal?.removeEventListener("abort", onUserAbort);
  }
}

async function readBody(response: Response): Promise<unknown> {
  let text: string;
  try {
    text = await response.text();
  } catch (err) {
    throw new APIConnectionError("Failed to read the response body.", { cause: err });
  }
  if (text === "") return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Wait `ms`, but wake at once (and throw) when the caller's signal aborts mid-backoff. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new APIUserAbortError({ cause: signal.reason }));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new APIUserAbortError({ cause: signal?.reason }));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
