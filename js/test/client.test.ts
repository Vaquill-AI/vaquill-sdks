import { readFileSync } from "node:fs";
import { inspect } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  APIUserAbortError,
  SpendGuardExceededError,
  Vaquill,
  VaquillError,
  VERSION,
} from "../src/index.js";
import { json, KEY, makeClient } from "./helpers.js";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("construction", () => {
  it("reads the key and base URL from the environment; arguments win", async () => {
    vi.stubEnv("VAQUILL_API_KEY", "vq_key_from_env_123456");
    vi.stubEnv("VAQUILL_BASE_URL", "https://env.test/");
    const a = makeClient([json(200, {})], { apiKey: undefined, baseURL: undefined });
    await a.client.credits.balance();
    expect(a.calls[0]?.url.origin).toBe("https://env.test");
    expect(a.calls[0]?.headers.get("authorization")).toBe("Bearer vq_key_from_env_123456");
    const b = makeClient([json(200, {})]);
    await b.client.credits.balance();
    expect(b.calls[0]?.url.origin).toBe("https://api.test");
    expect(b.calls[0]?.headers.get("authorization")).toBe(`Bearer ${KEY}`);
  });

  it("defaults the base URL to https://api.vaquill.ai", async () => {
    vi.stubEnv("VAQUILL_BASE_URL", "");
    const { client, calls } = makeClient([json(200, {})], { baseURL: "" });
    await client.credits.balance();
    expect(calls[0]?.url.origin).toBe("https://api.vaquill.ai");
  });

  it("rejects a missing key and a key without the vq_key_ prefix", () => {
    vi.stubEnv("VAQUILL_API_KEY", "");
    expect(() => new Vaquill({})).toThrow(VaquillError);
    expect(() => new Vaquill({ apiKey: "sk-live-secret-value" })).toThrow(/vq_key_/);
    try {
      new Vaquill({ apiKey: "sk-live-secret-value" });
    } catch (e) {
      expect(String(e)).not.toContain("sk-live-secret-value");
    }
  });

  it("sends default headers, a user agent and JSON content type", async () => {
    const { client, calls } = makeClient([json(200, {})], { defaultHeaders: { "X-Team": "a" } });
    await client.statutes.count({ query: "x" } as never, { headers: { "X-Call": "b" } });
    const h = calls[0]?.headers;
    expect(h?.get("x-team")).toBe("a");
    expect(h?.get("x-call")).toBe("b");
    expect(h?.get("content-type")).toBe("application/json");
    expect(h?.get("user-agent")).toBe(`vaquill-js/${VERSION}`);
  });

  it("keeps VERSION equal to package.json", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    expect(VERSION).toBe(pkg.version);
  });

  it("withOptions derives a client that shares the key and spend counter", async () => {
    const { client, calls } = makeClient([json(200, { creditsConsumed: 3 })]);
    const derived = client.withOptions({ maxRetries: 0, defaultHeaders: { "X-D": "1" } });
    await derived.statutes.getSection("A");
    expect(calls[0]?.headers.get("authorization")).toBe(`Bearer ${KEY}`);
    expect(calls[0]?.headers.get("x-d")).toBe("1");
    expect(client.creditsSpent).toBe(3);
  });
});

describe("key redaction", () => {
  it("never appears in JSON, inspect, String, own properties or errors", async () => {
    const { client } = makeClient([json(401, { detail: "bad key" })]);
    expect(JSON.stringify(client)).not.toContain(KEY);
    expect(inspect(client, { depth: 5, showHidden: true })).not.toContain(KEY);
    expect(`${client}`).not.toContain(KEY);
    expect(JSON.stringify(Object.getOwnPropertyNames(client))).not.toContain("apiKey");
    for (const res of [client.statutes, client.watches]) {
      expect(inspect(res, { depth: 5 })).not.toContain(KEY);
    }
    const err: unknown = await client.credits.balance().catch((e: unknown) => e);
    expect(JSON.stringify(err, Object.getOwnPropertyNames(err))).not.toContain(KEY);
    expect(inspect(err, { depth: 5 })).not.toContain(KEY);
  });
});

describe("timeouts and aborts", () => {
  it("raises APITimeoutError when fetch hangs past the timeout", async () => {
    vi.useFakeTimers();
    const hang = ((_: unknown, init?: RequestInit) =>
      new Promise((_res, rej) => {
        init?.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError")));
      })) as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, fetch: hang, timeout: 1000, maxRetries: 0 });
    const p = client.credits.balance();
    const assertion = expect(p).rejects.toBeInstanceOf(APITimeoutError);
    await vi.advanceTimersByTimeAsync(1001);
    await assertion;
  });

  it("retries a timeout on a free GET, then raises", async () => {
    vi.useFakeTimers();
    let n = 0;
    const hang = ((_: unknown, init?: RequestInit) => {
      n++;
      return new Promise((_res, rej) => {
        init?.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError")));
      });
    }) as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, fetch: hang, timeout: 1000, maxRetries: 2 });
    const p = client.credits.balance();
    const assertion = expect(p).rejects.toBeInstanceOf(APITimeoutError);
    await vi.advanceTimersByTimeAsync(60_000);
    await assertion;
    expect(n).toBe(3);
  });

  it("a caller abort is APIUserAbortError and is never retried", async () => {
    const ctl = new AbortController();
    let n = 0;
    const fn = ((_: unknown, init?: RequestInit) => {
      n++;
      return new Promise((_res, rej) => {
        init?.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError")));
      });
    }) as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, fetch: fn });
    const p = client.credits.balance({ signal: ctl.signal });
    const assertion = expect(p).rejects.toBeInstanceOf(APIUserAbortError);
    ctl.abort();
    await assertion;
    expect(n).toBe(1);
  });

  it("a caller abort during a Retry-After wait ends the call at once, not after the wait", async () => {
    // Found live: production sent `Retry-After: 27` on a 429, and the old sleep ignored the signal.
    const { client, calls } = makeClient([
      json(429, { detail: "slow down" }, { "retry-after": "100" }),
      json(200, {}),
    ]);
    const ctl = new AbortController();
    const started = Date.now();
    const p = client.credits.balance({ signal: ctl.signal });
    const assertion = expect(p).rejects.toBeInstanceOf(APIUserAbortError);
    await new Promise((r) => setTimeout(r, 20));
    ctl.abort();
    await assertion;
    expect(Date.now() - started).toBeLessThan(2000);
    expect(calls).toHaveLength(1);
  });

  it("an abort that lands while a retry is pending never sends the retry", async () => {
    const ctl = new AbortController();
    const { client, calls } = makeClient([
      () => {
        ctl.abort();
        return json(503, { detail: "down" });
      },
      json(200, {}),
    ]);
    await expect(client.credits.balance({ signal: ctl.signal })).rejects.toBeInstanceOf(
      APIUserAbortError,
    );
    expect(calls).toHaveLength(1);
  });

  it("wraps a network failure in APIConnectionError with the cause", async () => {
    const cause = new TypeError("fetch failed");
    const { client } = makeClient([cause], { maxRetries: 0 });
    const err: unknown = await client.credits.balance().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(APIConnectionError);
    expect((err as Error).cause).toBe(cause);
  });
});

describe("responses", () => {
  const headers = {
    "x-request-id": "req_9",
    "x-ratelimit-limit": "60",
    "x-ratelimit-remaining": "59",
    "x-ratelimit-limit-day": "2000",
    "x-ratelimit-remaining-day": "1990",
    "x-ratelimit-reset": "1780000000",
  };

  it("withResponse exposes request id, credits and typed rate limits", async () => {
    const { client } = makeClient([json(200, { creditsConsumed: 4, results: [] }, headers)]);
    const { data, meta, response } = await client.statutes.search({ query: "q" }).withResponse();
    expect(data.creditsConsumed).toBe(4);
    expect(meta.creditsConsumed).toBe(4);
    expect(meta.requestId).toBe("req_9");
    expect(meta.idempotentReplayed).toBe(false);
    expect(meta.rateLimit).toEqual({
      limit: 60,
      remaining: 59,
      limitDay: 2000,
      remainingDay: 1990,
      reset: 1780000000,
    });
    expect(response.status).toBe(200);
  });

  it("reads creditsConsumed from meta on watch envelopes and flags replays", async () => {
    const { client } = makeClient([
      json(200, { data: {}, meta: { creditsConsumed: 4 } }, { "idempotent-replayed": "true" }),
    ]);
    const { meta } = await client.watches.getChangeDiff("w", 1).withResponse();
    expect(meta.creditsConsumed).toBe(4);
    expect(meta.idempotentReplayed).toBe(true);
    expect(client.creditsSpent).toBe(0);
  });

  it("awaiting yields only the body, and the promise composes", async () => {
    const { client } = makeClient([json(200, { creditsRemaining: 5 })]);
    expect(await client.credits.balance()).toEqual({ creditsRemaining: 5 });
    expect(await Promise.all([client.credits.balance()])).toHaveLength(1);
    expect(await client.credits.balance().then((b) => b.creditsRemaining)).toBe(5);
  });

  it("does not throw on unknown fields, enum values or an empty 204", async () => {
    const { client } = makeClient([
      json(200, { creditsConsumed: 0, newField: { x: 1 }, results: [{ corpusType: "FUTURE" }] }),
      new Response(null, { status: 204 }),
    ]);
    await expect(client.statutes.search({ query: "q" })).resolves.toMatchObject({
      newField: { x: 1 },
    });
    await expect(client.watches.delete("w")).resolves.toBeUndefined();
  });

  it("rawRequest reaches endpoints the SDK does not wrap", async () => {
    const { client, calls } = makeClient([json(200, { ok: 1 })]);
    const out = await client.rawRequest("POST", "/api/v1/us/new-thing", {
      query: { a: [1, 2], skip: undefined },
      body: { x: 1 },
      charged: true,
    });
    expect(out).toEqual({ ok: 1 });
    expect(calls[0]?.url.search).toBe("?a=1&a=2");
    expect(calls[0]?.body).toEqual({ x: 1 });
    expect(calls[0]?.headers.has("idempotency-key")).toBe(true);
  });
});

describe("spend guard", () => {
  it("stops charged calls once maxCredits is reached, but not free ones", async () => {
    const { client, calls } = makeClient([json(200, { creditsConsumed: 4 })], { maxCredits: 6 });
    await client.statutes.search({ query: "q" });
    await client.statutes.search({ query: "q" });
    expect(client.creditsSpent).toBe(8);
    await expect(client.statutes.search({ query: "q" })).rejects.toBeInstanceOf(
      SpendGuardExceededError,
    );
    expect(calls).toHaveLength(2);
    await client.credits.balance();
    expect(calls).toHaveLength(3);
  });
});
