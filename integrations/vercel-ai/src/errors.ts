import {
  APIConnectionError,
  APIStatusError,
  APITimeoutError,
  APIUserAbortError,
  AuthenticationError,
  DailyCapExceededError,
  InsufficientCreditsError,
  isVaquillError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ResponseParseError,
  SpendGuardExceededError,
} from "@vaquill-ai/sdk";

export type ToolErrorKind =
  | "spend_limit"
  | "insufficient_credits"
  | "authentication"
  | "permission_denied"
  | "not_found"
  | "invalid_request"
  | "rate_limited"
  | "daily_cap"
  | "server_error"
  | "timeout"
  | "connection"
  | "bad_response"
  | "error"
  | "unexpected";

/** What a tool returns when a call fails. The model reads this, so it says what to do next. */
export interface ToolFailure {
  ok: false;
  error: {
    kind: ToolErrorKind;
    message: string;
    /** True when repeating the same call later may succeed. */
    retryable: boolean;
    /** What the model should do next. */
    hint: string;
    status?: number;
    code?: string;
    retryAfterSeconds?: number;
    /** Quote this to Vaquill support. */
    requestId?: string;
  };
}

const MAX_MESSAGE = 500;
const KEY_PATTERN = /vq_(?:key|ws)_[A-Za-z0-9_-]+/g;

/** Removes anything that looks like an API key, plus the configured key itself, and caps length. */
export function scrub(text: string, secrets: readonly string[] = []): string {
  let out = text.replace(KEY_PATTERN, "[redacted]");
  for (const secret of secrets) {
    if (secret.length >= 8) out = out.split(secret).join("[redacted]");
  }
  return out.length > MAX_MESSAGE ? `${out.slice(0, MAX_MESSAGE)}...` : out;
}

function validationSummary(err: APIStatusError, secrets: readonly string[]): string {
  const items = err.errors;
  if (!items?.length) return "";
  const parts: string[] = [];
  for (const item of items.slice(0, 5)) {
    if (item && typeof item === "object") {
      const rec = item as { loc?: unknown; msg?: unknown };
      const loc = Array.isArray(rec.loc) ? rec.loc.filter((p) => p !== "body").join(".") : "";
      const msg = typeof rec.msg === "string" ? rec.msg : "";
      if (msg) parts.push(loc ? `${loc}: ${msg}` : msg);
    }
  }
  return parts.length ? ` Details: ${scrub(parts.join("; "), secrets)}` : "";
}

function failure(
  kind: ToolErrorKind,
  message: string,
  retryable: boolean,
  hint: string,
  extra: Partial<ToolFailure["error"]> = {},
): ToolFailure {
  return { ok: false, error: { kind, message, retryable, hint, ...extra } };
}

/**
 * Turns anything a tool can throw into a structured, key-free result. Aborts are NOT mapped:
 * `isAbort` errors are rethrown by the caller so the agent loop stops.
 */
export function toToolFailure(err: unknown, secrets: readonly string[] = []): ToolFailure {
  if (!isVaquillError(err)) {
    const name = err instanceof Error ? err.name : "Error";
    return failure(
      "unexpected",
      `Unexpected ${name} while calling Vaquill.`,
      false,
      "Do not retry this call. Tell the user the lookup failed.",
    );
  }
  const message = scrub(err.message, secrets);

  if (err instanceof SpendGuardExceededError) {
    return failure(
      "spend_limit",
      message,
      false,
      "The credit limit for this session is used up. Do not call any more tools that cost credits. Answer from what you already have and tell the user the limit was reached.",
    );
  }
  if (err instanceof APIStatusError) {
    const extra: Partial<ToolFailure["error"]> = { status: err.status };
    if (err.code) extra.code = scrub(err.code, secrets);
    if (err.requestId) extra.requestId = scrub(err.requestId, secrets);
    if (err.retryAfterSeconds !== null) extra.retryAfterSeconds = err.retryAfterSeconds;
    if (err instanceof InsufficientCreditsError) {
      return failure(
        "insufficient_credits",
        message,
        false,
        "The account is out of credits. Stop calling paid tools and tell the user to add credits.",
        extra,
      );
    }
    if (err instanceof AuthenticationError) {
      return failure(
        "authentication",
        message,
        false,
        "The API key was rejected. Tell the user to check their Vaquill API key. Retrying will not help.",
        extra,
      );
    }
    if (err instanceof PermissionDeniedError) {
      return failure(
        "permission_denied",
        message,
        false,
        "This key is not allowed to do that. Tell the user; retrying will not help.",
        extra,
      );
    }
    if (err instanceof NotFoundError) {
      return failure(
        "not_found",
        message,
        false,
        "Nothing exists at that identifier. Find the right actId or sessionLawId with searchStatutes, resolveCitation or searchSessionLaws instead of guessing.",
        extra,
      );
    }
    if (err instanceof DailyCapExceededError) {
      return failure(
        "daily_cap",
        message,
        false,
        "The daily request cap is reached. Stop calling Vaquill tools and tell the user to try tomorrow.",
        extra,
      );
    }
    if (err instanceof RateLimitError) {
      return failure(
        "rate_limited",
        message,
        true,
        "Too many requests. Wait for retryAfterSeconds if given, make fewer calls, then try again.",
        extra,
      );
    }
    if (err.status === 400 || err.status === 422) {
      return failure(
        "invalid_request",
        `${message}${validationSummary(err, secrets)}`,
        false,
        "The request was rejected as invalid. Fix the arguments named in the message and call again.",
        extra,
      );
    }
    if (err.status >= 500) {
      return failure(
        "server_error",
        message,
        true,
        "Vaquill had a server problem. One retry later is reasonable; otherwise tell the user.",
        extra,
      );
    }
    return failure(
      "error",
      message,
      false,
      "The request failed. Do not repeat it unchanged.",
      extra,
    );
  }
  if (err instanceof APITimeoutError) {
    return failure(
      "timeout",
      message,
      true,
      "The request timed out. Retry once with a narrower request (smaller limit, fewer filters).",
    );
  }
  if (err instanceof APIConnectionError) {
    return failure(
      "connection",
      message,
      true,
      "Could not reach Vaquill. One retry later is reasonable; otherwise tell the user.",
    );
  }
  if (err instanceof ResponseParseError) {
    return failure(
      "bad_response",
      message,
      false,
      "Vaquill answered with something unreadable. Do not retry; tell the user.",
    );
  }
  return failure("error", message, false, "The request failed. Do not repeat it unchanged.");
}

/** True for the error the SDK raises when the caller aborts. The tools rethrow these. */
export function isAbort(err: unknown): boolean {
  return err instanceof APIUserAbortError;
}
