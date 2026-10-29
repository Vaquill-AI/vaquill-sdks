import type { APIStatusError } from "./errors.js";

export const DEFAULT_MAX_RETRIES = 2;
export const INITIAL_RETRY_DELAY_S = 0.5;
export const MAX_RETRY_DELAY_S = 8;
/** A server-requested wait longer than this is not worth holding the caller for. */
export const MAX_RETRY_AFTER_S = 120;

const NEVER_RETRY_CODES = new Set(["insufficient_credits", "daily_cap_exceeded"]);

/**
 * Whether a received error response may be retried.
 *
 * `replaySafe` is true when repeating the request cannot double-charge or double-create:
 * a non-POST that is not charged, or any call carrying an `Idempotency-Key`. Without it,
 * only a 429 `rate_limited` (rejected before any work) is retried.
 */
export function shouldRetryStatus(err: APIStatusError, replaySafe: boolean): boolean {
  const { status, code } = err;
  if (status === 402 || (code && NEVER_RETRY_CODES.has(code))) return false;
  if (err.retryable === false) return false;
  // 501 Not Implemented is permanent: another attempt cannot succeed.
  if (status === 501) return false;
  if (status === 409) return code === "idempotency_in_progress" && replaySafe;
  if (status === 429) return true;
  if (status === 408 || status >= 500) return replaySafe;
  return false;
}

/**
 * Milliseconds to wait before retry number `attempt + 1`, or null when the server asked for a
 * wait above the cap (do not retry at all). Precedence: `retry-after-ms`, then `Retry-After`
 * (seconds or HTTP date), then the body's `retryAfterSeconds`, then exponential backoff
 * with jitter that scales the delay down by 0 to 25 percent.
 */
export function retryDelayMs(
  attempt: number,
  headers?: Headers,
  bodyRetryAfterSeconds?: number | null,
  random: () => number = Math.random,
  now: () => number = Date.now,
): number | null {
  let seconds = parseRetryAfter(headers, now);
  if (seconds === undefined && typeof bodyRetryAfterSeconds === "number") {
    seconds = bodyRetryAfterSeconds;
  }
  if (seconds !== undefined && seconds >= 0) {
    return seconds > MAX_RETRY_AFTER_S ? null : seconds * 1000;
  }
  const base = Math.min(INITIAL_RETRY_DELAY_S * 2 ** attempt, MAX_RETRY_DELAY_S);
  return base * (1 - 0.25 * random()) * 1000;
}

function parseRetryAfter(headers: Headers | undefined, now: () => number): number | undefined {
  if (!headers) return undefined;
  const ms = Number(headers.get("retry-after-ms"));
  if (headers.get("retry-after-ms") && Number.isFinite(ms)) return ms / 1000;
  const ra = headers.get("retry-after");
  if (!ra) return undefined;
  const secs = Number(ra);
  if (Number.isFinite(secs)) return secs;
  const date = Date.parse(ra);
  return Number.isNaN(date) ? undefined : Math.max(0, (date - now()) / 1000);
}
