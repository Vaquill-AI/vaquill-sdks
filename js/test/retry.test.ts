import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  InsufficientCreditsError,
  RateLimitError,
} from "../src/index.js";
import { retryDelayMs } from "../src/retry.js";
import { json, makeClient } from "./helpers.js";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const OK = json(200, { creditsConsumed: 2 });
const search = { query: "q" };

describe("retryDelayMs", () => {
  it("backs off 0.5, 1, 2, 4, 8, 8 seconds with no jitter", () => {
    const got = [0, 1, 2, 3, 4, 5].map((n) => retryDelayMs(n, undefined, null, () => 0));
    expect(got).toEqual([500, 1000, 2000, 4000, 8000, 8000]);
  });
  it("jitter scales the delay down by at most 25 percent", () => {
    expect(retryDelayMs(1, undefined, null, () => 1)).toBe(750);
    expect(retryDelayMs(1, undefined, null, () => 0.5)).toBe(875);
  });
  it("prefers retry-after-ms, then Retry-After seconds, then an HTTP date, then the body", () => {
    expect(retryDelayMs(0, new Headers({ "retry-after-ms": "250", "retry-after": "9" }))).toBe(250);
    expect(retryDelayMs(0, new Headers({ "retry-after": "7" }))).toBe(7000);
    const now = Date.parse("2026-01-01T00:00:00Z");
    expect(
      retryDelayMs(
        0,
        new Headers({ "retry-after": "Thu, 01 Jan 2026 00:00:05 GMT" }),
        null,
        Math.random,
        () => now,
      ),
    ).toBe(5000);
    expect(retryDelayMs(0, new Headers(), 4)).toBe(4000);
  });
  it("gives up when the server asks for more than 120 seconds", () => {
    expect(retryDelayMs(0, new Headers({ "retry-after": "121" }))).toBeNull();
  });
});

describe("retry loop", () => {
  it("retries a 503 on a free GET and then succeeds", async () => {
    const { client, calls } = makeClient([json(503, { detail: "x" }), json(500, {}), OK]);
    const p = client.credits.balance();
    await vi.runAllTimersAsync();
    await expect(p).resolves.toEqual({ creditsConsumed: 2 });
    expect(calls).toHaveLength(3);
  });

  it("gives up after maxRetries and throws the last error", async () => {
    const { client, calls } = makeClient([json(503, { detail: "x" })], { maxRetries: 1 });
    const p = client.credits.balance();
    const assertion = expect(p).rejects.toMatchObject({ status: 503 });
    await vi.runAllTimersAsync();
    await assertion;
    expect(calls).toHaveLength(2);
  });

  it("honours Retry-After on a 429 and does not retry before it", async () => {
    const { client, calls } = makeClient([
      json(429, { code: "rate_limited", detail: "x" }, { "retry-after": "3" }),
      OK,
    ]);
    const p = client.statutes.search(search);
    await vi.advanceTimersByTimeAsync(2900);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(200);
    await expect(p).resolves.toBeDefined();
    expect(calls).toHaveLength(2);
  });

  it("reuses one Idempotency-Key across every retry of a charged call", async () => {
    const { client, calls } = makeClient([json(500, {}), new APIConnectionError(), OK]);
    const p = client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    const keys = calls.map((c) => c.headers.get("idempotency-key"));
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(new Set(keys).size).toBe(1);
    expect(keys).toHaveLength(3);
  });

  it("uses a different key for each logical call", async () => {
    const { client, calls } = makeClient([OK]);
    await client.statutes.search(search);
    await client.statutes.search(search);
    expect(calls[0]?.headers.get("idempotency-key")).not.toBe(
      calls[1]?.headers.get("idempotency-key"),
    );
  });

  it("sends a caller-supplied key and none for free calls", async () => {
    const { client, calls } = makeClient([OK]);
    await client.statutes.search(search, { idempotencyKey: "my-key-0123456789" });
    await client.credits.balance();
    expect(calls[0]?.headers.get("idempotency-key")).toBe("my-key-0123456789");
    expect(calls[1]?.headers.has("idempotency-key")).toBe(false);
  });

  it("does not retry a charged POST after a timeout when keys are disabled", async () => {
    const { client, calls } = makeClient([new DOMException("t", "TimeoutError"), OK]);
    const p = client.statutes.search(search, { idempotencyKey: false, timeout: 50 });
    const assertion = expect(p).rejects.toBeInstanceOf(APIConnectionError);
    await vi.runAllTimersAsync();
    await assertion;
    expect(calls).toHaveLength(1);
    expect(calls[0]?.headers.has("idempotency-key")).toBe(false);
  });

  it("does not retry a charged POST on 5xx when keys are disabled, but does on 429", async () => {
    const a = makeClient([json(500, {}), OK]);
    await expect(a.client.statutes.search(search, { idempotencyKey: false })).rejects.toMatchObject(
      {
        status: 500,
      },
    );
    expect(a.calls).toHaveLength(1);

    const b = makeClient([json(429, { code: "rate_limited" }, { "retry-after": "1" }), OK]);
    const p = b.client.statutes.search(search, { idempotencyKey: false });
    await vi.runAllTimersAsync();
    await p;
    expect(b.calls).toHaveLength(2);
  });

  it("does not retry an unkeyed free POST (watch create) after a 5xx", async () => {
    const { client, calls } = makeClient([json(500, {}), OK]);
    await expect(client.watches.create({ corpusType: "state" } as never)).rejects.toMatchObject({
      status: 500,
    });
    expect(calls).toHaveLength(1);
  });

  it("never retries insufficient credits, even with a 429 status or retryable true", async () => {
    for (const status of [402, 429]) {
      const { client, calls } = makeClient([
        json(status, {
          code: "insufficient_credits",
          retryable: true,
          detail: "Insufficient credits",
        }),
        OK,
      ]);
      await expect(client.statutes.search(search)).rejects.toBeInstanceOf(InsufficientCreditsError);
      expect(calls).toHaveLength(1);
    }
  });

  it("never retries daily_cap_exceeded", async () => {
    const { client, calls } = makeClient([json(429, { code: "daily_cap_exceeded" }), OK]);
    await expect(client.statutes.resolve({ cite: "x" })).rejects.toBeInstanceOf(RateLimitError);
    expect(calls).toHaveLength(1);
  });

  it("retries 409 only for idempotency_in_progress", async () => {
    const a = makeClient([
      json(409, { code: "idempotency_in_progress" }, { "retry-after": "2" }),
      OK,
    ]);
    const p = a.client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    expect(a.calls).toHaveLength(2);

    for (const code of ["idempotency_replay_unavailable", "conflict"]) {
      const b = makeClient([json(409, { code }), OK]);
      await expect(b.client.statutes.search(search)).rejects.toMatchObject({ status: 409 });
      expect(b.calls).toHaveLength(1);
    }
  });

  it("does not retry 4xx client errors or a server retryable:false", async () => {
    for (const res of [json(404, {}), json(422, {}), json(500, { retryable: false })]) {
      const { client, calls } = makeClient([res, OK]);
      await expect(client.credits.balance()).rejects.toBeDefined();
      expect(calls).toHaveLength(1);
    }
  });

  it("retries a timeout on a keyed charged call", async () => {
    const { client, calls } = makeClient([new APITimeoutError(), OK]);
    const p = client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    expect(calls).toHaveLength(2);
  });

  it("maxRetries 0 disables retries", async () => {
    const { client, calls } = makeClient([json(500, {}), OK], { maxRetries: 0 });
    await expect(client.credits.balance()).rejects.toBeDefined();
    expect(calls).toHaveLength(1);
  });
});
