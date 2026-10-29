/**
 * Error hierarchy. Branch on `code` when present and fall back to the HTTP status, so the
 * client works against servers that predate the machine-code envelope. The code set is open:
 * an unknown code still produces the status-mapped class.
 */

/**
 * Brand carried by every SDK error. `Symbol.for` is shared across module copies, so an error
 * built by an ESM copy of this package is still recognised by the CJS copy (dual-package hazard).
 * The value is the class-name chain, most specific first.
 */
export const VAQUILL_ERROR_BRAND: unique symbol = Symbol.for("vaquill.error");

function brandOf(value: unknown): readonly string[] | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const chain = (value as Record<symbol, unknown>)[VAQUILL_ERROR_BRAND];
  return Array.isArray(chain) ? (chain as string[]) : undefined;
}

/** True for any error raised by this SDK, including one created by another copy of the package. */
export function isVaquillError(value: unknown): value is VaquillError {
  return value instanceof Error && brandOf(value) !== undefined;
}

/** Base class for every error raised by this SDK. */
export class VaquillError extends Error {
  override name = "VaquillError";

  constructor(message?: string, options?: { cause?: unknown }) {
    super(message, options);
    const chain: string[] = [];
    for (
      let proto = Object.getPrototypeOf(this);
      proto && proto !== Error.prototype;
      proto = Object.getPrototypeOf(proto)
    ) {
      const ctor = (proto as { constructor?: { name?: string } }).constructor;
      if (ctor?.name) chain.push(ctor.name);
    }
    Object.defineProperty(this, VAQUILL_ERROR_BRAND, { value: chain, enumerable: false });
  }

  /** Same as the module-level `isVaquillError`. */
  static isVaquillError(value: unknown): value is VaquillError {
    return isVaquillError(value);
  }

  /**
   * Makes `instanceof` work across ESM and CJS copies of this package: an error from another
   * copy matches when its brand lists this class's name.
   */
  static override [Symbol.hasInstance](value: unknown): boolean {
    // biome-ignore lint/complexity/noThisInStatic: `this` is the subclass being tested
    if (Function.prototype[Symbol.hasInstance].call(this, value)) return true;
    const chain = brandOf(value);
    if (!chain || !(value instanceof Error)) return false;
    // biome-ignore lint/complexity/noThisInStatic: `this` is the subclass being tested
    return this === VaquillError || chain.includes(this.name);
  }
}

/** A success response whose body was not the JSON the endpoint promises. */
export class ResponseParseError extends VaquillError {
  override name = "ResponseParseError";
  readonly status: number;
  readonly requestId: string | null;
  /** The start of the unparseable body (at most 200 characters). */
  readonly bodyPreview: string;
  constructor(
    status: number,
    requestId: string | null,
    bodyPreview: string,
    options?: { cause?: unknown },
  ) {
    super(`Response was not valid JSON (HTTP ${status}).`, options);
    this.status = status;
    this.requestId = requestId;
    this.bodyPreview = bodyPreview.slice(0, 200);
  }
}

/** The client-side `maxCredits` cap was reached; no request was sent. */
export class SpendGuardExceededError extends VaquillError {
  override name = "SpendGuardExceededError";
}

/** A webhook delivery failed signature or timestamp verification. */
export class WebhookVerificationError extends VaquillError {
  override name = "WebhookVerificationError";
}

/** The request never produced an HTTP response. */
export class APIConnectionError extends VaquillError {
  override name = "APIConnectionError";
  constructor(message = "Connection error.", options?: { cause?: unknown }) {
    super(message, options);
  }
}

/** The request exceeded the configured timeout. */
export class APITimeoutError extends APIConnectionError {
  override name = "APITimeoutError";
  constructor(options?: { cause?: unknown }) {
    super("Request timed out.", options);
  }
}

/** The caller aborted the request through its own `AbortSignal`. Never retried. */
export class APIUserAbortError extends APIConnectionError {
  override name = "APIUserAbortError";
  constructor(options?: { cause?: unknown }) {
    super("Request was aborted.", options);
  }
}

/** The server answered with a 4xx or 5xx status. */
export class APIStatusError extends VaquillError {
  override name = "APIStatusError";
  readonly status: number;
  readonly requestId: string | null;
  /** Stable machine code (open set), or null when the server did not send one. */
  readonly code: string | null;
  /** The server's retry hint, or null when absent. */
  readonly retryable: boolean | null;
  readonly retryAfterSeconds: number | null;
  /** Parsed JSON body, raw text, or undefined when the body was empty. */
  readonly body: unknown;
  /** Legacy envelope member, unchanged by the server. */
  readonly detail: unknown;
  /** Legacy 422 member: list of `{loc, msg, type}`. */
  readonly errors: unknown[] | null;
  readonly headers: Headers;

  constructor(status: number, body: unknown, headers: Headers) {
    const env = isRecord(body) ? body : {};
    super(messageFor(status, env));
    this.status = status;
    this.body = body;
    this.headers = headers;
    this.requestId = str(env.requestId) ?? headers.get("x-request-id");
    this.code = str(env.code);
    this.retryable = typeof env.retryable === "boolean" ? env.retryable : null;
    this.retryAfterSeconds =
      typeof env.retryAfterSeconds === "number" ? env.retryAfterSeconds : null;
    this.detail = env.detail;
    this.errors = Array.isArray(env.errors) ? env.errors : null;
  }
}

export class BadRequestError extends APIStatusError {
  override name = "BadRequestError";
}
export class AuthenticationError extends APIStatusError {
  override name = "AuthenticationError";
}
/** Out of credits (402). Never retried. */
export class InsufficientCreditsError extends APIStatusError {
  override name = "InsufficientCreditsError";
}
export class PermissionDeniedError extends APIStatusError {
  override name = "PermissionDeniedError";
}
export class NotFoundError extends APIStatusError {
  override name = "NotFoundError";
}
export class ConflictError extends APIStatusError {
  override name = "ConflictError";
}
export class UnprocessableEntityError extends APIStatusError {
  override name = "UnprocessableEntityError";
}
/** 429. `retryAfterSeconds` is set when the server said how long to wait. */
export class RateLimitError extends APIStatusError {
  override name = "RateLimitError";
}
/** Per-key daily cap. Retrying cannot succeed until the cap resets. */
export class DailyCapExceededError extends RateLimitError {
  override name = "DailyCapExceededError";
}
export class InternalServerError extends APIStatusError {
  override name = "InternalServerError";
}
/** Base for the three idempotency codes. */
export class IdempotencyConflictError extends APIStatusError {
  override name = "IdempotencyConflictError";
}
/** Same `Idempotency-Key` sent with a different request (422). */
export class IdempotencyKeyReusedError extends IdempotencyConflictError {
  override name = "IdempotencyKeyReusedError";
}
/** The original request is still running (409). Retried automatically. */
export class IdempotencyInProgressError extends IdempotencyConflictError {
  override name = "IdempotencyInProgressError";
}
/** The original completed but its response was too large to replay (409). Not charged again. */
export class IdempotencyReplayUnavailableError extends IdempotencyConflictError {
  override name = "IdempotencyReplayUnavailableError";
}

const BY_CODE: Record<string, typeof APIStatusError> = {
  insufficient_credits: InsufficientCreditsError,
  daily_cap_exceeded: DailyCapExceededError,
  idempotency_key_reused: IdempotencyKeyReusedError,
  idempotency_in_progress: IdempotencyInProgressError,
  idempotency_replay_unavailable: IdempotencyReplayUnavailableError,
};

/** Build the most specific error class for a response. Unknown codes fall back to the status. */
export function makeStatusError(status: number, body: unknown, headers: Headers): APIStatusError {
  const code = isRecord(body) ? str(body.code) : null;
  const byCode = code ? BY_CODE[code] : undefined;
  if (byCode) return new byCode(status, body, headers);
  let cls: typeof APIStatusError;
  if (status === 400) cls = BadRequestError;
  else if (status === 401) cls = AuthenticationError;
  else if (status === 402) cls = InsufficientCreditsError;
  else if (status === 403) cls = PermissionDeniedError;
  else if (status === 404) cls = NotFoundError;
  else if (status === 409) cls = ConflictError;
  else if (status === 422) cls = UnprocessableEntityError;
  else if (status === 429) cls = RateLimitError;
  else if (status >= 500) cls = InternalServerError;
  else cls = APIStatusError;
  return new cls(status, body, headers);
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

/** "loc.path: msg" for the first few entries of a FastAPI-style validation list. */
function summariseValidation(items: unknown[]): string | null {
  const parts: string[] = [];
  for (const item of items) {
    if (typeof item === "string" && item) parts.push(item);
    else if (isRecord(item)) {
      const msg = str(item.msg) ?? str(item.message);
      if (!msg) continue;
      const path = Array.isArray(item.loc) ? item.loc : [];
      const where = ["body", "query", "path", "header"].includes(String(path[0])) ? 1 : 0;
      const loc = path.slice(path.length > 1 ? where : 0).join(".");
      parts.push(loc ? `${loc}: ${msg}` : msg);
    }
  }
  if (parts.length === 0) return null;
  const shown = parts.slice(0, 3).join("; ");
  const more = items.length - Math.min(parts.length, 3);
  return more > 0 ? `${shown} (+${more} more)` : shown;
}

function messageFor(status: number, env: Record<string, unknown>): string {
  const detail = env.detail;
  if (typeof detail === "string" && detail) {
    // A 422 envelope carries the reason in `errors[]`; the string is only a generic label.
    const why =
      status === 422 && Array.isArray(env.errors) ? summariseValidation(env.errors) : null;
    return why ? `${detail}: ${why}` : detail;
  }
  if (Array.isArray(detail)) {
    const summary = summariseValidation(detail);
    if (summary) return `HTTP ${status}: ${summary}`;
  }
  if (isRecord(detail)) {
    const m = str(detail.message) ?? str(detail.detail) ?? str(detail.reason);
    if (m) return m;
  }
  const title = str(env.title);
  if (title) return title;
  if (Array.isArray(env.errors)) {
    const summary = summariseValidation(env.errors);
    if (summary) return `HTTP ${status}: ${summary}`;
  }
  return `HTTP ${status}`;
}
