/**
 * Error hierarchy. Branch on `code` when present and fall back to the HTTP status, so the
 * client works against servers that predate the machine-code envelope. The code set is open:
 * an unknown code still produces the status-mapped class.
 */

/** Base class for every error raised by this SDK. */
export class VaquillError extends Error {
  override name = "VaquillError";
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

function messageFor(status: number, env: Record<string, unknown>): string {
  const detail = env.detail;
  if (typeof detail === "string" && detail) return detail;
  if (isRecord(detail)) {
    const m = str(detail.message) ?? str(detail.detail) ?? str(detail.reason);
    if (m) return m;
  }
  return str(env.title) ?? `HTTP ${status}`;
}
