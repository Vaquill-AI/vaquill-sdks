/**
 * Webhook verification (Standard Webhooks, decision D5).
 *
 * Uses WebCrypto only, so it runs unchanged on Node, Bun, Deno and edge runtimes. Signature
 * comparison goes through `crypto.subtle.verify`, which is constant time.
 *
 * Always pass the RAW request body (string or bytes), never re-serialised JSON.
 */
import { WebhookVerificationError } from "./errors.js";

export const DEFAULT_TOLERANCE_SECONDS = 300;
const SECRET_PREFIX = "whsec_"; // pragma: allowlist secret

export type HeaderBag = Headers | Record<string, string | string[] | undefined>;
export type WebhookSecret = string | readonly string[];

export interface VerifyOptions {
  /** Maximum clock difference in seconds, either direction. Default 300. */
  toleranceSeconds?: number;
  /**
   * Accept the legacy `X-Vaquill-Signature: sha256=<hex>` header when the Standard Webhooks
   * headers are absent. It signs the body only, so it gives NO replay protection: an attacker
   * who captures one delivery can resend it forever. Off by default.
   */
  allowLegacy?: boolean;
  /** Override "now" (Unix seconds), for tests. */
  now?: number;
}

/**
 * The envelope every delivery shares: the body is `{ event, ...payload, firedAt }` with
 * camelCase keys (see the Python SDK's `WebhookEvent`, which keeps the rest as extras).
 */
export interface WebhookEventBase {
  /** Event name, such as `board.updated`. */
  event: string;
  /** ISO-8601 time the delivery was fired. */
  firedAt?: string;
  /** Members this SDK version does not type are kept, not dropped. */
  [key: string]: unknown;
}

/** One change line inside a `board.updated` delivery. Shape follows the Law Change Alerts feed. */
export type WebhookChange = Record<string, unknown>;

/** A real law-change delivery for a watch. */
export interface BoardUpdatedEvent extends WebhookEventBase {
  event: "board.updated";
  /** Stable per (watch, refresh event): the key to deduplicate redeliveries on. */
  deliveryId?: string;
  corpusType?: string;
  state?: string | null;
  boardLabel?: string;
  /** Which population the `sections*` counters were counted over. */
  scope?: unknown;
  rowsAdded?: number;
  rowsUpdated?: number;
  rowsDeleted?: number;
  /** Present when section counts were computed for this refresh. */
  sectionsAdded?: number;
  sectionsAmended?: number;
  sectionsRemoved?: number;
  refreshLogId?: string | number | null;
  changes?: WebhookChange[];
  changesOverflowCount?: number;
}

/** The delivery `watches.test(...)` sends. */
export interface BoardTestEvent extends WebhookEventBase {
  event: "board.test";
  corpusType?: string;
  state?: string | null;
  boardLabel?: string;
  test: true;
}

/** An event name this SDK version does not know yet. */
export type UnknownWebhookEvent = WebhookEventBase;

/**
 * A verified delivery. Narrow on `event`; the last member keeps event names added later
 * usable instead of failing, so a narrowed branch still includes it.
 */
export type WebhookEvent = BoardUpdatedEvent | BoardTestEvent | UnknownWebhookEvent;

const enc = new TextEncoder();

/** Every value of a header, lower-case name lookup. A multi-valued header yields all its values. */
function headerValues(headers: HeaderBag, name: string): string[] | undefined {
  if (headers instanceof Headers) {
    const v = headers.get(name);
    return v === null ? undefined : [v];
  }
  const out: string[] = [];
  let found = false;
  for (const [k, v] of Object.entries(headers)) {
    if (k.toLowerCase() !== name || v === undefined) continue;
    found = true;
    if (Array.isArray(v)) out.push(...v);
    else out.push(v);
  }
  return found ? out : undefined;
}

/**
 * One value for a header that must be single (`webhook-id`, `webhook-timestamp`). Repeated
 * copies that agree are fine; copies that disagree are ambiguous, so the delivery is refused
 * instead of silently trusting the first.
 */
function singleHeader(headers: HeaderBag, name: string): string | undefined {
  const values = headerValues(headers, name);
  if (!values || values.length === 0) return undefined;
  const distinct = new Set(values.map((v) => v.trim()));
  if (distinct.size > 1) {
    throw new WebhookVerificationError(`Conflicting ${name} header values.`);
  }
  return values[0];
}

/** The signature header, with every element of a multi-valued header joined by a space. */
function signatureHeader(headers: HeaderBag): string | undefined {
  const values = headerValues(headers, "webhook-signature");
  if (!values || values.length === 0) return undefined;
  return values.join(" ");
}

/** Every `v1,<base64>` candidate in a signature header, however the copies were joined. */
function v1Signatures(value: string): string[] {
  const out: string[] = [];
  for (const m of value.matchAll(/(?:^|[\s,])v1,([A-Za-z0-9+/=]+)/g)) {
    if (m[1]) out.push(m[1]);
  }
  return out;
}

function toBytes(payload: string | Uint8Array): Uint8Array<ArrayBuffer> {
  if (typeof payload === "string") return enc.encode(payload) as Uint8Array<ArrayBuffer>;
  return new Uint8Array(payload);
}

function b64decode(s: string): Uint8Array<ArrayBuffer> | null {
  try {
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

function b64encode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function hexDecode(s: string): Uint8Array<ArrayBuffer> | null {
  if (s.length === 0 || s.length % 2 !== 0 || !/^[0-9a-fA-F]+$/.test(s)) return null;
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = Number.parseInt(s.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/**
 * HMAC key for a stored secret: base64 decoded after `whsec_`, otherwise the UTF-8 bytes.
 * A `whsec_` secret that is not valid base64 is refused, never used as literal text.
 */
export function deriveKey(secret: string): Uint8Array<ArrayBuffer> {
  if (secret.startsWith(SECRET_PREFIX)) {
    const decoded = b64decode(secret.slice(SECRET_PREFIX.length));
    if (!decoded) {
      throw new WebhookVerificationError(
        "The webhook secret starts with 'whsec_' but is not valid base64.",
      );
    }
    return decoded;
  }
  return enc.encode(secret) as Uint8Array<ArrayBuffer>;
}

function hmacKey(raw: Uint8Array<ArrayBuffer>, usage: "sign" | "verify"): Promise<CryptoKey> {
  return globalThis.crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, [
    usage,
  ]);
}

/** The `webhook-signature` value for a delivery: `v1,<base64>`. Useful for tests and local replays. */
export async function signWebhook(
  id: string,
  timestamp: number | string,
  payload: string | Uint8Array,
  secret: string,
): Promise<string> {
  if (typeof secret !== "string" || !usableSecret(secret)) {
    throw new WebhookVerificationError("No webhook secret configured.");
  }
  const body = toBytes(payload);
  const prefix = enc.encode(`${id}.${timestamp}.`);
  const signed = new Uint8Array(prefix.length + body.length);
  signed.set(prefix);
  signed.set(body, prefix.length);
  const key = await hmacKey(deriveKey(secret), "sign");
  const mac = await globalThis.crypto.subtle.sign("HMAC", key, signed);
  return `v1,${b64encode(new Uint8Array(mac))}`;
}

async function matches(
  secrets: readonly string[],
  signature: Uint8Array<ArrayBuffer>,
  data: Uint8Array<ArrayBuffer>,
  keyOf: (s: string) => Uint8Array<ArrayBuffer>,
): Promise<boolean> {
  let ok = false;
  for (const s of secrets) {
    const key = await hmacKey(keyOf(s), "verify");
    // Evaluate every secret and every candidate; do not short-circuit on the first hit.
    if (await globalThis.crypto.subtle.verify("HMAC", key, signature, data)) ok = true;
  }
  return ok;
}

/**
 * The usable secrets, or a throw. An empty, blank or non-string secret (an unset environment
 * variable is the usual cause) must never verify anything: an HMAC keyed with "" is computable
 * by anyone, so it would accept forged events.
 */
function normaliseSecrets(secret: WebhookSecret | null | undefined): string[] {
  const list: unknown[] =
    typeof secret === "string" ? [secret] : Array.isArray(secret) ? [...secret] : [];
  if (list.length === 0 || list.some((s) => typeof s !== "string" || usableSecret(s) === false)) {
    throw new WebhookVerificationError("No webhook secret configured.");
  }
  return list as string[];
}

function usableSecret(s: string): boolean {
  const t = s.trim();
  return t.length > 0 && t !== SECRET_PREFIX;
}

/**
 * Verify a delivery. Resolves on success and throws `WebhookVerificationError` on any failure.
 * `secret` may be a list during rotation: a signature made by any of them passes.
 */
export async function verifyWebhook(
  payload: string | Uint8Array,
  headers: HeaderBag,
  secret: WebhookSecret,
  options: VerifyOptions = {},
): Promise<void> {
  const secrets = normaliseSecrets(secret);
  const body = toBytes(payload);
  const id = singleHeader(headers, "webhook-id");
  const ts = singleHeader(headers, "webhook-timestamp");
  const sigHeader = signatureHeader(headers);

  if (id === undefined && ts === undefined && sigHeader === undefined) {
    const legacy = singleHeader(headers, "x-vaquill-signature");
    if (options.allowLegacy && legacy !== undefined) {
      await verifyLegacy(body, legacy, secrets);
      return;
    }
    throw new WebhookVerificationError("Missing webhook signature headers.");
  }
  if (!id || !ts || !sigHeader)
    throw new WebhookVerificationError("Missing webhook signature headers.");

  const seconds = Number(ts);
  if (!/^\d+$/.test(ts) || !Number.isSafeInteger(seconds)) {
    throw new WebhookVerificationError("Invalid webhook timestamp.");
  }
  const now = options.now ?? Date.now() / 1000;
  if (Math.abs(now - seconds) > (options.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS)) {
    throw new WebhookVerificationError("Webhook timestamp is outside the tolerance window.");
  }

  const prefix = enc.encode(`${id}.${ts}.`);
  const signed = new Uint8Array(prefix.length + body.length);
  signed.set(prefix);
  signed.set(body, prefix.length);

  let ok = false;
  for (const sig of v1Signatures(sigHeader)) {
    const bytes = b64decode(sig);
    if (bytes && (await matches(secrets, bytes, signed, deriveKey))) ok = true;
  }
  if (!ok) throw new WebhookVerificationError("No matching webhook signature.");
}

async function verifyLegacy(
  body: Uint8Array<ArrayBuffer>,
  header: string,
  secrets: readonly string[],
): Promise<void> {
  const sig = header.startsWith("sha256=") ? hexDecode(header.slice(7)) : null;
  // The legacy key is always the secret's UTF-8 bytes, even for a `whsec_` secret.
  if (
    !sig ||
    !(await matches(secrets, sig, body, (s) => enc.encode(s) as Uint8Array<ArrayBuffer>))
  ) {
    throw new WebhookVerificationError("No matching webhook signature.");
  }
}

/**
 * Verify, then parse the body as JSON and return it typed as a `WebhookEvent`.
 *
 * The signature is the trust boundary: `event` is not validated beyond the body being a JSON
 * object, so an event type added by the server later still arrives (as `UnknownWebhookEvent`).
 * Escape hatch: pass your own type, `unwrapWebhook<MyPayload>(...)`, to skip the built-in one.
 */
export async function unwrapWebhook<T = WebhookEvent>(
  payload: string | Uint8Array,
  headers: HeaderBag,
  secret: WebhookSecret,
  options?: VerifyOptions,
): Promise<T> {
  await verifyWebhook(payload, headers, secret, options);
  const text = typeof payload === "string" ? payload : new TextDecoder().decode(payload);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new WebhookVerificationError("Webhook body is not valid JSON.");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new WebhookVerificationError("Webhook body is not a JSON object.");
  }
  return parsed as T;
}

/** True for an object shaped like a Vaquill event: a string `event`. A runtime narrowing helper. */
export function isWebhookEvent(value: unknown): value is WebhookEvent {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as { event?: unknown }).event === "string"
  );
}

/** Namespace form: `webhooks.verify(...)`. */
export const webhooks = {
  verify: verifyWebhook,
  unwrap: unwrapWebhook,
  sign: signWebhook,
  isEvent: isWebhookEvent,
};
