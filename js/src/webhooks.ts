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

const enc = new TextEncoder();

function header(headers: HeaderBag, name: string): string | undefined {
  if (headers instanceof Headers) return headers.get(name) ?? undefined;
  for (const [k, v] of Object.entries(headers)) {
    if (k.toLowerCase() === name) return Array.isArray(v) ? v[0] : v;
  }
  return undefined;
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

/** HMAC key for a stored secret: base64 decoded after `whsec_`, otherwise the UTF-8 bytes. */
export function deriveKey(secret: string): Uint8Array<ArrayBuffer> {
  if (secret.startsWith(SECRET_PREFIX)) {
    const decoded = b64decode(secret.slice(SECRET_PREFIX.length));
    if (decoded) return decoded;
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
 * Verify a delivery. Resolves on success and throws `WebhookVerificationError` on any failure.
 * `secret` may be a list during rotation: a signature made by any of them passes.
 */
export async function verifyWebhook(
  payload: string | Uint8Array,
  headers: HeaderBag,
  secret: WebhookSecret,
  options: VerifyOptions = {},
): Promise<void> {
  const secrets = typeof secret === "string" ? [secret] : [...secret];
  if (secrets.length === 0 || secrets.some((s) => !s)) {
    throw new WebhookVerificationError("No webhook secret configured.");
  }
  const body = toBytes(payload);
  const id = header(headers, "webhook-id");
  const ts = header(headers, "webhook-timestamp");
  const sigHeader = header(headers, "webhook-signature");

  if (id === undefined && ts === undefined && sigHeader === undefined) {
    const legacy = header(headers, "x-vaquill-signature");
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
  for (const part of sigHeader.split(" ")) {
    const [version, sig] = part.split(",", 2);
    if (version !== "v1" || !sig) continue;
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

/** Verify, then parse the body as JSON. */
export async function unwrapWebhook<T = unknown>(
  payload: string | Uint8Array,
  headers: HeaderBag,
  secret: WebhookSecret,
  options?: VerifyOptions,
): Promise<T> {
  await verifyWebhook(payload, headers, secret, options);
  const text = typeof payload === "string" ? payload : new TextDecoder().decode(payload);
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new WebhookVerificationError("Webhook body is not valid JSON.");
  }
}

/** Namespace form: `webhooks.verify(...)`. */
export const webhooks = { verify: verifyWebhook, unwrap: unwrapWebhook, sign: signWebhook };
