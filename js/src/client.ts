import {
  APIConnectionError,
  APITimeoutError,
  APIUserAbortError,
  makeStatusError,
  ResponseParseError,
  SpendGuardExceededError,
  VaquillError,
} from "./errors.js";
import { BoardsResource } from "./resources/boards.js";
import { CreditsResource } from "./resources/credits.js";
import { PricingResource } from "./resources/pricing.js";
import { SessionLawsResource } from "./resources/session-laws.js";
import { StatutesResource } from "./resources/statutes.js";
import { WatchesResource } from "./resources/watches.js";
import { APIPromise, buildMeta, deprecationInfo, type WithResponse } from "./response.js";
import { DEFAULT_MAX_RETRIES, retryDelayMs, shouldRetryStatus } from "./retry.js";
import type { Logger, LogLevel } from "./types.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://api.vaquill.ai";
export const DEFAULT_TIMEOUT_MS = 60_000;
const API_KEY_PREFIX = "vq_key_";

export type Query = Record<string, unknown>;

/** Options accepted by every method as its last argument. */
export interface RequestOptions {
  /**
   * Per-attempt timeout in milliseconds. `0`, `Infinity` or anything above 2^31-1 means no
   * timeout. Negative or NaN throws a TypeError.
   */
  timeout?: number;
  maxRetries?: number;
  /** Extra headers for this call. Names are case-insensitive. Authorization and Idempotency-Key cannot be overridden. */
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /**
   * Charged operations get one generated `Idempotency-Key` per logical call, reused on every
   * retry. Pass your own string (16 to 255 visible ASCII characters) to control it, or `false`
   * to send none. With no key, a charged call is never retried after a timeout, connection
   * error or 5xx, because it could charge twice. An empty string throws a TypeError.
   */
  idempotencyKey?: string | false;
}

export interface ClientOptions {
  /** Defaults to `process.env.VAQUILL_API_KEY`. Must start with `vq_key_`. */
  apiKey?: string;
  /** Defaults to `process.env.VAQUILL_BASE_URL`, then `https://api.vaquill.ai`. */
  baseURL?: string;
  /**
   * Per-attempt timeout in milliseconds. Default 60000. `0`, `Infinity` or anything above
   * 2^31-1 disables the timeout. Negative or NaN throws a TypeError.
   */
  timeout?: number;
  /** Default 2. */
  maxRetries?: number;
  /** Header names are case-insensitive. */
  defaultHeaders?: Record<string, string>;
  /** Injected `fetch` (proxies, test doubles). Defaults to the global. */
  fetch?: typeof fetch;
  /**
   * Spend guard. Once the credits reported by responses on this client reach this number,
   * further charged calls throw `SpendGuardExceededError` before any request is sent.
   * The check uses what was already spent, not the cost of the next call.
   *
   * Trade-off: when this is set, charged calls on the client (and clients derived from it) run
   * one at a time, from the check to the moment their credits are counted, so concurrent calls
   * cannot all pass the check and overshoot the cap. Leave it unset to keep full concurrency.
   */
  maxCredits?: number;
  /** Set `false` to send no `Idempotency-Key` on charged calls (and so never retry them after a 5xx or timeout). Default true. */
  idempotencyKeys?: boolean;
  /** Where log lines go. Any subset of `debug`, `info`, `warn`, `error`; defaults to `console`. */
  logger?: Partial<Logger>;
  /**
   * Minimum level to log. Default `warn`. `debug` logs each request and response, `info` adds
   * retries, `warn` reports deprecated endpoints (once per method and path). The API key is
   * always redacted.
   */
  logLevel?: LogLevel;
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
  /** Milliseconds, or Infinity for no timeout. */
  timeout: number;
  maxRetries: number;
  /** Lowercase header names. */
  defaultHeaders: Record<string, string>;
  fetch: typeof fetch;
  maxCredits: number | undefined;
  idempotencyKeys: boolean;
  logger: Logger;
  logLevel: LogLevel;
}

/** State shared by a client and every client derived from it with `withOptions`. */
export interface SharedState {
  credits: number;
  /** Tail of the promise chain that serializes charged calls when `maxCredits` is set. */
  tail: Promise<void>;
  /** `METHOD path` keys already warned about as deprecated. */
  deprecationWarned: Set<string>;
}

const INSPECT = Symbol.for("nodejs.util.inspect.custom");
let browserWarned = false;

const MAX_TIMER_MS = 2 ** 31 - 1;
const LEVELS: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3, off: 4 };
const NOOP = () => {};

/** Env access that never throws (Deno without `--allow-env` throws on read). */
function readEnv(): Record<string, string | undefined> {
  try {
    return globalThis.process?.env ?? {};
  } catch {
    return {};
  }
}

/**
 * 0, Infinity and anything a timer cannot hold mean "no timeout" (returned as Infinity).
 * Negative, NaN and non-numbers are mistakes worth failing loudly on.
 */
function normalizeTimeout(value: number, label: string): number {
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    throw new TypeError(`${label} must be a non-negative number of milliseconds, got ${value}.`);
  }
  return value === 0 || value > MAX_TIMER_MS ? Number.POSITIVE_INFINITY : value;
}

function lowerHeaders(
  ...bags: Array<Record<string, string | undefined> | undefined>
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const bag of bags) {
    for (const [name, value] of Object.entries(bag ?? {})) {
      if (value === undefined || value === null) continue;
      out[name.toLowerCase()] = String(value);
    }
  }
  return out;
}

function dropUndefined<T extends object>(obj: T): Partial<T> {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined)) as Partial<T>;
}

function resolveLogger(logger: Partial<Logger> | undefined): Logger {
  const target = logger ?? console;
  const pick = (name: keyof Logger) => {
    const fn = target[name];
    return typeof fn === "function" ? (fn.bind(target) as (m: string) => void) : NOOP;
  };
  return { debug: pick("debug"), info: pick("info"), warn: pick("warn"), error: pick("error") };
}

/** RFC 4122 v4. Falls back to `getRandomValues` where `randomUUID` is missing (non-secure contexts). */
export function newUUID(): string {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  if (typeof c?.getRandomValues !== "function") {
    throw new VaquillError("No Web Crypto available to generate an Idempotency-Key.");
  }
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40;
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0"));
  return `${h.slice(0, 4).join("")}-${h.slice(4, 6).join("")}-${h.slice(6, 8).join("")}-${h
    .slice(8, 10)
    .join("")}-${h.slice(10).join("")}`;
}

/** The server accepts 16 to 255 visible ASCII characters. */
function validateIdempotencyKey(key: unknown): string {
  if (
    typeof key !== "string" ||
    key.length < 16 ||
    key.length > 255 ||
    !/^[\x21-\x7e]+$/.test(key)
  ) {
    throw new TypeError(
      "idempotencyKey must be a string of 16 to 255 visible ASCII characters, or false.",
    );
  }
  return key;
}

export class Vaquill implements Transport {
  // Private field: absent from Object.keys, JSON.stringify and util.inspect.
  readonly #apiKey: string;
  readonly #cfg: Omit<Resolved, "apiKey">;
  readonly #state: SharedState;

  readonly statutes: StatutesResource;
  readonly sessionLaws: SessionLawsResource;
  readonly watches: WatchesResource;
  readonly boards: BoardsResource;
  readonly credits: CreditsResource;
  readonly pricing: PricingResource;

  constructor(options: ClientOptions = {}, shared?: { credits: number } & Partial<SharedState>) {
    const env = readEnv();
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
    const logLevel = options.logLevel ?? "warn";
    if (!(logLevel in LEVELS)) {
      throw new TypeError(`logLevel must be one of ${Object.keys(LEVELS).join(", ")}.`);
    }
    this.#apiKey = apiKey;
    const state = shared ?? { credits: 0 };
    state.tail ??= Promise.resolve();
    state.deprecationWarned ??= new Set();
    this.#state = state as SharedState;
    this.#cfg = {
      baseURL: (options.baseURL || env.VAQUILL_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, ""),
      timeout: normalizeTimeout(options.timeout ?? DEFAULT_TIMEOUT_MS, "timeout"),
      maxRetries: options.maxRetries ?? DEFAULT_MAX_RETRIES,
      defaultHeaders: lowerHeaders(options.defaultHeaders),
      fetch: fetchImpl.bind(globalThis),
      maxCredits: options.maxCredits,
      idempotencyKeys: options.idempotencyKeys ?? true,
      logger: resolveLogger(options.logger),
      logLevel,
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
    return this.#state.credits;
  }

  /**
   * A derived client with some options replaced. It shares the key and the spend counter.
   * An option set to `undefined` keeps the parent's value.
   */
  withOptions(options: Omit<ClientOptions, "apiKey"> = {}): Vaquill {
    const given = dropUndefined(options);
    return new Vaquill(
      {
        apiKey: this.#apiKey,
        baseURL: this.#cfg.baseURL,
        timeout: this.#cfg.timeout,
        maxRetries: this.#cfg.maxRetries,
        fetch: this.#cfg.fetch,
        maxCredits: this.#cfg.maxCredits,
        idempotencyKeys: this.#cfg.idempotencyKeys,
        logger: this.#cfg.logger,
        logLevel: this.#cfg.logLevel,
        ...given,
        defaultHeaders: lowerHeaders(this.#cfg.defaultHeaders, options.defaultHeaders),
      },
      this.#state,
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

  #log(level: Exclude<LogLevel, "off">, message: string): void {
    if (LEVELS[level] < LEVELS[this.#cfg.logLevel]) return;
    try {
      this.#cfg.logger[level](message.split(this.#apiKey).join("[redacted]"));
    } catch {
      // A broken logger must never break a request.
    }
  }

  async #send<T>(spec: RequestSpec, options: RequestOptions): Promise<WithResponse<T>> {
    const cfg = this.#cfg;
    const charged = spec.charged === true;
    const maxRetries = options.maxRetries ?? cfg.maxRetries;
    const timeout =
      options.timeout === undefined ? cfg.timeout : normalizeTimeout(options.timeout, "timeout");

    let idemKey: string | undefined;
    if (options.idempotencyKey !== undefined && options.idempotencyKey !== false) {
      idemKey = validateIdempotencyKey(options.idempotencyKey);
    } else if (charged && options.idempotencyKey !== false && cfg.idempotencyKeys) {
      idemKey = newUUID();
    }
    // Repeating the call cannot double-charge or double-create.
    const replaySafe = idemKey !== undefined || (!charged && spec.method !== "POST");

    // Names are lowercased so a different case can never duplicate or override another header.
    const headers: Record<string, string> = {
      accept: "application/json",
      ...(typeof window === "undefined" ? { "user-agent": `vaquill-js/${VERSION}` } : {}),
      ...lowerHeaders(cfg.defaultHeaders, options.headers),
    };
    headers.authorization = `Bearer ${this.#apiKey}`;
    delete headers["idempotency-key"];
    if (idemKey) headers["idempotency-key"] = idemKey;
    let payload: string | undefined;
    if (spec.body !== undefined) {
      payload = JSON.stringify(spec.body);
      headers["content-type"] = "application/json";
    }
    const url = buildURL(cfg.baseURL, spec.path, spec.query);

    const run = () =>
      this.#attempts<T>(spec, options, {
        url,
        headers,
        payload,
        timeout,
        maxRetries,
        replaySafe,
        charged,
        idemKey,
      });
    if (charged && cfg.maxCredits !== undefined) return this.#serialized(options.signal, run);
    return run();
  }

  /**
   * Run `fn` after every earlier guarded call finished. The chain is shared with derived
   * clients, so the cap holds across them too. A caller abort while queued ends the wait.
   */
  async #serialized<R>(signal: AbortSignal | undefined, fn: () => Promise<R>): Promise<R> {
    const state = this.#state;
    const previous = state.tail;
    let release: () => void = NOOP;
    state.tail = new Promise<void>((resolve) => {
      release = resolve;
    });
    try {
      await waitFor(previous, signal);
    } catch (err) {
      // Never leave later callers waiting on a turn that will not be used.
      void previous.then(release, release);
      throw err;
    }
    try {
      return await fn();
    } finally {
      release();
    }
  }

  async #attempts<T>(
    spec: RequestSpec,
    options: RequestOptions,
    plan: {
      url: string;
      headers: Record<string, string>;
      payload: string | undefined;
      timeout: number;
      maxRetries: number;
      replaySafe: boolean;
      charged: boolean;
      idemKey: string | undefined;
    },
  ): Promise<WithResponse<T>> {
    const cfg = this.#cfg;
    const { url, headers, payload, timeout, maxRetries, replaySafe, charged, idemKey } = plan;
    if (charged && cfg.maxCredits !== undefined && this.#state.credits >= cfg.maxCredits) {
      throw new SpendGuardExceededError(
        `Spend guard: ${this.#state.credits} credits spent, limit is ${cfg.maxCredits}.`,
      );
    }
    // True once an earlier attempt of this logical call may have been charged without us
    // seeing the result (lost response, timeout, 5xx, request still running).
    let priorMaybeCharged = false;

    for (let attempt = 0; ; attempt++) {
      const canRetry = attempt < maxRetries;
      this.#log(
        "debug",
        `request ${spec.method} ${spec.path} attempt=${attempt + 1}${
          idemKey ? ` idempotency-key=${idemKey.slice(0, 8)}...` : ""
        } authorization=Bearer [redacted]`,
      );
      let response: Response;
      let text: string;
      let parsed: { ok: boolean; value: unknown };
      try {
        ({ response, text, parsed } = await fetchOnce(
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
        if (charged) priorMaybeCharged = true;
        if (canRetry && replaySafe) {
          const delay = retryDelayMs(attempt);
          if (delay !== null) {
            this.#log(
              "info",
              `retry ${spec.method} ${spec.path} after ${(err as Error).name} in ${Math.round(delay)}ms`,
            );
            await sleep(delay, options.signal);
            continue;
          }
        }
        throw err;
      }
      const requestId = response.headers.get("x-request-id");
      this.#log(
        "debug",
        `response ${spec.method} ${spec.path} status=${response.status}${
          requestId ? ` request-id=${requestId}` : ""
        }`,
      );
      this.#warnIfDeprecated(spec, response.headers);

      if (response.ok) {
        if (!parsed.ok) {
          const failure = new ResponseParseError(response.status, requestId, text);
          this.#log("error", `${spec.method} ${spec.path}: ${failure.message}`);
          throw failure;
        }
        const body = parsed.value;
        const meta = buildMeta(response, body, attempt);
        if (meta.creditsConsumed && (!meta.idempotentReplayed || priorMaybeCharged)) {
          this.#state.credits += meta.creditsConsumed;
        }
        return { data: body as T, response, meta };
      }
      const error = makeStatusError(response.status, parsed.value, response.headers);
      if (
        charged &&
        (response.status >= 500 || response.status === 408 || response.status === 409)
      ) {
        priorMaybeCharged = true;
      }
      if (canRetry && shouldRetryStatus(error, replaySafe)) {
        const delay = retryDelayMs(attempt, response.headers, error.retryAfterSeconds);
        if (delay !== null) {
          this.#log(
            "info",
            `retry ${spec.method} ${spec.path} after status ${response.status} in ${Math.round(delay)}ms`,
          );
          await sleep(delay, options.signal);
          continue;
        }
      }
      throw error;
    }
  }

  #warnIfDeprecated(spec: RequestSpec, headers: Headers): void {
    const info = deprecationInfo(headers);
    if (!info) return;
    const key = `${spec.method} ${spec.path}`;
    if (this.#state.deprecationWarned.has(key)) return;
    this.#state.deprecationWarned.add(key);
    const parts = [
      info.deprecation !== undefined ? `Deprecation: ${info.deprecation}` : undefined,
      info.sunset !== undefined ? `Sunset: ${info.sunset}` : undefined,
    ].filter(Boolean);
    this.#log("warn", `${key} is deprecated (${parts.join(", ")}).`);
  }
}

function buildURL(base: string, path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item === undefined || item === null) continue;
      params.append(
        key,
        item instanceof Date
          ? item.toISOString()
          : typeof item === "object"
            ? JSON.stringify(item)
            : String(item),
      );
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
): Promise<{ response: Response; text: string; parsed: { ok: boolean; value: unknown } }> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = Number.isFinite(timeoutMs)
    ? setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, timeoutMs)
    : undefined;
  const onUserAbort = () => controller.abort();
  if (userSignal?.aborted) onUserAbort();
  userSignal?.addEventListener("abort", onUserAbort, { once: true });
  // A fetch that ignores the signal must still end when we abort, so race it against the signal.
  let onAbort: () => void = NOOP;
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => reject(controller.signal.reason ?? new Error("aborted"));
    if (controller.signal.aborted) onAbort();
    else controller.signal.addEventListener("abort", onAbort, { once: true });
  });
  aborted.catch(NOOP);
  const work = (async () => {
    const response = await fetchImpl(url, { method, headers, body, signal: controller.signal });
    const text = await readText(response);
    return { response, text, parsed: parseJson(text) };
  })();
  work.catch(NOOP);
  try {
    return await Promise.race([work, aborted]);
  } catch (err) {
    if (userSignal?.aborted) throw new APIUserAbortError({ cause: err });
    if (timedOut) throw new APITimeoutError({ cause: err });
    if (err instanceof VaquillError) throw err;
    throw new APIConnectionError(undefined, { cause: err });
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    controller.signal.removeEventListener("abort", onAbort);
    userSignal?.removeEventListener("abort", onUserAbort);
  }
}

async function readText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch (err) {
    throw new APIConnectionError("Failed to read the response body.", { cause: err });
  }
}

/** Empty is `undefined` (ok). Unparseable is `ok: false` with the raw text as the value. */
function parseJson(text: string): { ok: boolean; value: unknown } {
  if (text === "") return { ok: true, value: undefined };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, value: text };
  }
}

/** Wait for `promise`, but give up at once (throwing) when the caller's signal aborts. */
function waitFor(promise: Promise<void>, signal?: AbortSignal): Promise<void> {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new APIUserAbortError({ cause: signal.reason }));
      return;
    }
    const onAbort = () => reject(new APIUserAbortError({ cause: signal.reason }));
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      () => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      },
      () => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      },
    );
  });
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
