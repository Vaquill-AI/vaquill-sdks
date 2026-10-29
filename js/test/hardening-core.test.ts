import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APIConnectionError,
  APIStatusError,
  APITimeoutError,
  ResponseParseError,
  SpendGuardExceededError,
  UnprocessableEntityError,
  Vaquill,
  VaquillError,
} from "../src/index.js";
import { json, KEY, makeClient, scripted } from "./helpers.js";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const search = { query: "q" };

describe("spend guard: lost first attempt", () => {
  it("counts a replayed response when an earlier attempt of the same call got no response", async () => {
    vi.useFakeTimers();
    const { client, calls } = makeClient(
      [
        new TypeError("socket hang up"),
        json(200, { creditsConsumed: 5 }, { "idempotent-replayed": "true" }),
      ],
      { maxCredits: 100 },
    );
    const p = client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    expect(calls).toHaveLength(2);
    expect(client.creditsSpent).toBe(5);
  });

  it("counts a replay after a 5xx attempt, but not a replay with no earlier lost attempt", async () => {
    vi.useFakeTimers();
    const a = makeClient([
      json(503, {}),
      json(200, { creditsConsumed: 3 }, { "idempotent-replayed": "true" }),
    ]);
    const p = a.client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    expect(a.client.creditsSpent).toBe(3);

    const b = makeClient([json(200, { creditsConsumed: 3 }, { "idempotent-replayed": "true" })]);
    await b.client.statutes.search(search);
    expect(b.client.creditsSpent).toBe(0);
  });

  it("does not count a replay after only a 429 (rejected before any work)", async () => {
    vi.useFakeTimers();
    const { client } = makeClient([
      json(429, { code: "rate_limited" }, { "retry-after": "1" }),
      json(200, { creditsConsumed: 3 }, { "idempotent-replayed": "true" }),
    ]);
    const p = client.statutes.search(search);
    await vi.runAllTimersAsync();
    await p;
    expect(client.creditsSpent).toBe(0);
  });
});

describe("spend guard: concurrency", () => {
  it("serializes charged calls when maxCredits is set, so the cap holds", async () => {
    let inFlight = 0;
    let peak = 0;
    const fn = (async () => {
      inFlight++;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight--;
      return json(200, { creditsConsumed: 4 });
    }) as typeof fetch;
    const client = new Vaquill({
      apiKey: KEY,
      baseURL: "https://api.test",
      fetch: fn,
      maxCredits: 4,
    });
    const results = await Promise.allSettled(
      [1, 2, 3, 4].map(() => client.statutes.search(search)),
    );
    expect(results.filter((r) => r.status === "fulfilled")).toHaveLength(1);
    for (const r of results.slice(1)) {
      expect(r.status === "rejected" && r.reason).toBeInstanceOf(SpendGuardExceededError);
    }
    expect(peak).toBe(1);
    expect(client.creditsSpent).toBe(4);
  });

  it("keeps concurrency when maxCredits is unset", async () => {
    let inFlight = 0;
    let peak = 0;
    const fn = (async () => {
      inFlight++;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight--;
      return json(200, { creditsConsumed: 1 });
    }) as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, baseURL: "https://api.test", fetch: fn });
    await Promise.all([1, 2, 3].map(() => client.statutes.search(search)));
    expect(peak).toBe(3);
  });

  it("an aborted queued call leaves the queue moving", async () => {
    const { fn } = scripted([json(200, { creditsConsumed: 1 })]);
    const slow = (async (...a: Parameters<typeof fetch>) => {
      await new Promise((r) => setTimeout(r, 10));
      return fn(...a);
    }) as typeof fetch;
    const client = new Vaquill({
      apiKey: KEY,
      baseURL: "https://api.test",
      fetch: slow,
      maxCredits: 100,
    });
    const ctl = new AbortController();
    const first = client.statutes.search(search);
    const queued = client.statutes.search(search, { signal: ctl.signal });
    const third = client.statutes.search(search);
    ctl.abort();
    await expect(queued).rejects.toMatchObject({ name: "APIUserAbortError" });
    await first;
    await third;
    expect(client.creditsSpent).toBe(2);
  });
});

describe("header names", () => {
  function capture() {
    const seen: Array<Record<string, string>> = [];
    const fn = (async (_u: unknown, init?: RequestInit) => {
      seen.push(init?.headers as Record<string, string>);
      return json(200, { creditsConsumed: 0 });
    }) as typeof fetch;
    return { seen, fn };
  }

  it("lowercases and merges default and per-call headers; sensitive ones cannot be overridden", async () => {
    const { seen, fn } = capture();
    const client = new Vaquill({
      apiKey: KEY,
      baseURL: "https://api.test",
      fetch: fn,
      defaultHeaders: { "User-Agent": "mine/1", AUTHORIZATION: "Bearer evil", "X-Team": "a" },
    });
    await client.statutes.search(search, {
      headers: {
        "user-AGENT": "call/2",
        authorization: "Bearer evil2",
        "Idempotency-Key": "caller-key-0000000000",
        "Content-Type": "text/plain",
        "x-team": "b",
      },
    });
    const h = seen[0] as Record<string, string>;
    const keys = Object.keys(h);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.every((k) => k === k.toLowerCase())).toBe(true);
    expect(h["user-agent"]).toBe("call/2");
    expect(h["x-team"]).toBe("b");
    expect(h.authorization).toBe(`Bearer ${KEY}`);
    expect(h["content-type"]).toBe("application/json");
    expect(h["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("a caller Idempotency-Key header is dropped when keys are off", async () => {
    const { seen, fn } = capture();
    const client = new Vaquill({ apiKey: KEY, baseURL: "https://api.test", fetch: fn });
    await client.statutes.search(search, {
      idempotencyKey: false,
      headers: { "IDEMPOTENCY-KEY": "caller-key-0000000000" },
    });
    expect(seen[0]).not.toHaveProperty("idempotency-key");
  });

  it("withOptions merges default headers case-insensitively", async () => {
    const { seen, fn } = capture();
    const base = new Vaquill({
      apiKey: KEY,
      baseURL: "https://api.test",
      fetch: fn,
      defaultHeaders: { "X-A": "1" },
    });
    await base.withOptions({ defaultHeaders: { "x-a": "2" } }).credits.balance();
    expect((seen[0] as Record<string, string>)["x-a"]).toBe("2");
  });
});

describe("timeout normalisation", () => {
  function noTimerClient(timeout: number) {
    const fn = (async () => json(200, { ok: 1 })) as typeof fetch;
    return new Vaquill({ apiKey: KEY, baseURL: "https://api.test", fetch: fn, timeout });
  }

  it.each([0, Number.POSITIVE_INFINITY, 2 ** 31])("timeout %s creates no timer", async (t) => {
    const spy = vi.spyOn(globalThis, "setTimeout");
    await noTimerClient(t).credits.balance();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("a normal timeout still creates one", async () => {
    const spy = vi.spyOn(globalThis, "setTimeout");
    await noTimerClient(5000).credits.balance();
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it.each([-1, Number.NaN])("timeout %s throws a TypeError at construction", (t) => {
    expect(() => noTimerClient(t)).toThrow(TypeError);
  });

  it("a bad per-call timeout rejects with a TypeError", async () => {
    await expect(noTimerClient(1000).credits.balance({ timeout: -5 })).rejects.toBeInstanceOf(
      TypeError,
    );
  });
});

describe("environment access", () => {
  it("does not throw when reading process.env throws (Deno without --allow-env)", () => {
    const real = globalThis.process;
    const hostile = new Proxy(real, {
      get(target, prop, recv) {
        if (prop === "env") throw new Error("NotCapable: env access denied");
        return Reflect.get(target, prop, recv);
      },
    });
    vi.stubGlobal("process", hostile);
    expect(() => new Vaquill({ apiKey: KEY, fetch: scripted([json(200, {})]).fn })).not.toThrow();
    expect(() => new Vaquill({ fetch: scripted([json(200, {})]).fn })).toThrow(/No API key/);
  });
});

describe("withOptions", () => {
  it("an undefined option does not reset the parent's value", async () => {
    const { fn, calls } = scripted([json(200, {})]);
    const base = new Vaquill({
      apiKey: KEY,
      baseURL: "https://other.test",
      fetch: fn,
      maxRetries: 7,
    });
    const derived = base.withOptions({
      baseURL: undefined,
      fetch: undefined,
      maxRetries: undefined,
    });
    await derived.credits.balance();
    expect(calls[0]?.url.origin).toBe("https://other.test");
    expect(JSON.stringify(derived)).toContain("other.test");
  });
});

describe("query dates", () => {
  it("serialises a Date with toISOString and no JSON quotes", async () => {
    const { client, calls } = makeClient([json(200, {})]);
    await client.rawRequest("GET", "/x", {
      query: { since: new Date("2026-01-02T03:04:05.000Z"), many: [new Date(0)] },
    });
    expect(calls[0]?.url.searchParams.get("since")).toBe("2026-01-02T03:04:05.000Z");
    expect(calls[0]?.url.searchParams.get("many")).toBe("1970-01-01T00:00:00.000Z");
  });
});

describe("idempotency keys", () => {
  it("rejects an empty or short or non-ASCII key with a TypeError, sending nothing", async () => {
    const { client, calls } = makeClient([json(200, {})]);
    for (const bad of ["", "short", "x".repeat(256), "has space 0123456789"]) {
      await expect(client.statutes.search(search, { idempotencyKey: bad })).rejects.toBeInstanceOf(
        TypeError,
      );
    }
    expect(calls).toHaveLength(0);
  });

  it("accepts the 16 and 255 character bounds", async () => {
    const { client, calls } = makeClient([json(200, { creditsConsumed: 0 })]);
    await client.statutes.search(search, { idempotencyKey: "a".repeat(16) });
    await client.statutes.search(search, { idempotencyKey: "b".repeat(255) });
    expect(calls).toHaveLength(2);
  });

  it("client-level idempotencyKeys:false sends no key and never retries a 5xx on a charged call", async () => {
    const { client, calls } = makeClient([json(500, {}), json(200, { creditsConsumed: 1 })], {
      idempotencyKeys: false,
    });
    await expect(client.statutes.search(search)).rejects.toMatchObject({ status: 500 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.headers.has("idempotency-key")).toBe(false);
  });

  it("a per-call key still wins when the client default is off", async () => {
    const { client, calls } = makeClient([json(200, { creditsConsumed: 0 })], {
      idempotencyKeys: false,
    });
    await client.statutes.search(search, { idempotencyKey: "explicit-key-0123456" });
    expect(calls[0]?.headers.get("idempotency-key")).toBe("explicit-key-0123456");
  });

  it("withOptions keeps idempotencyKeys", async () => {
    const { client, calls } = makeClient([json(200, { creditsConsumed: 0 })], {
      idempotencyKeys: false,
    });
    await client.withOptions({ maxRetries: 1 }).statutes.search(search);
    expect(calls[0]?.headers.has("idempotency-key")).toBe(false);
  });

  it("falls back to getRandomValues when crypto.randomUUID is missing", async () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: real.getRandomValues.bind(real) });
    const { client, calls } = makeClient([json(200, { creditsConsumed: 0 })]);
    await client.statutes.search(search);
    expect(calls[0]?.headers.get("idempotency-key")).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});

describe("retry policy", () => {
  it("never retries a 501, even on a free GET", async () => {
    vi.useFakeTimers();
    const { client, calls } = makeClient([json(501, {}), json(200, {})]);
    await expect(client.credits.balance()).rejects.toMatchObject({ status: 501 });
    expect(calls).toHaveLength(1);
  });

  it("a 5xx on a charged call is not retried when keys are off", async () => {
    const { client, calls } = makeClient([json(502, {}), json(200, { creditsConsumed: 1 })]);
    await expect(client.statutes.search(search, { idempotencyKey: false })).rejects.toMatchObject({
      status: 502,
    });
    expect(calls).toHaveLength(1);
  });
});

describe("a fetch that ignores the AbortSignal", () => {
  it("still ends with APITimeoutError", async () => {
    vi.useFakeTimers();
    const never = (() => new Promise(() => {})) as unknown as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, fetch: never, timeout: 500, maxRetries: 0 });
    const p = client.credits.balance();
    const assertion = expect(p).rejects.toBeInstanceOf(APITimeoutError);
    await vi.advanceTimersByTimeAsync(501);
    await assertion;
  });

  it("a caller abort ends it too", async () => {
    const never = (() => new Promise(() => {})) as unknown as typeof fetch;
    const client = new Vaquill({ apiKey: KEY, fetch: never, timeout: 0, maxRetries: 0 });
    const ctl = new AbortController();
    const p = client.credits.balance({ signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toMatchObject({ name: "APIUserAbortError" });
  });
});

describe("non-JSON success bodies", () => {
  it("throws ResponseParseError with status and request id", async () => {
    const html = new Response("<html>gateway</html>", {
      status: 200,
      headers: { "x-request-id": "req_9", "content-type": "text/html" },
    });
    const { client } = makeClient([html]);
    const err = await client.credits.balance().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ResponseParseError);
    expect(err).toBeInstanceOf(VaquillError);
    expect(err).toMatchObject({ status: 200, requestId: "req_9" });
  });

  it("does not retry it and keeps 204 and empty as undefined", async () => {
    const bad = new Response("nope", { status: 200 });
    const a = makeClient([bad, json(200, {})]);
    await expect(a.client.credits.balance()).rejects.toBeInstanceOf(ResponseParseError);
    expect(a.calls).toHaveLength(1);
    const b = makeClient([new Response(null, { status: 204 })]);
    await expect(b.client.watches.delete("w")).resolves.toBeUndefined();
  });

  it("error responses with a non-JSON body still map to a status error", async () => {
    const { client } = makeClient([new Response("Bad Gateway", { status: 400 })]);
    await expect(client.credits.balance()).rejects.toBeInstanceOf(APIStatusError);
  });
});

describe("422 validation detail", () => {
  it("summarises the first errors in the message and keeps detail intact", async () => {
    const detail = [
      { loc: ["body", "query"], msg: "Field required", type: "missing" },
      { loc: ["body", "limit"], msg: "Input should be <= 50", type: "less_than_equal" },
      { loc: ["body", "a"], msg: "bad a", type: "x" },
      { loc: ["body", "b"], msg: "bad b", type: "x" },
    ];
    const { client } = makeClient([json(422, { detail })]);
    const err = (await client.statutes
      .search(search)
      .catch((e: unknown) => e)) as UnprocessableEntityError;
    expect(err).toBeInstanceOf(UnprocessableEntityError);
    expect(err.message).toContain("query: Field required");
    expect(err.message).toContain("limit: Input should be <= 50");
    expect(err.message).toContain("(+1 more)");
    expect(err.message).not.toBe("HTTP 422");
    expect(err.detail).toEqual(detail);
  });
});

describe("dual-package hazard", () => {
  it("instanceof and isVaquillError work across two module instances", async () => {
    const copyPath = "../src/errors.js?second";
    const a = await import("../src/errors.js");
    vi.resetModules();
    const b = (await import(/* @vite-ignore */ copyPath)) as typeof a;
    expect(a.VaquillError).not.toBe(b.VaquillError);

    const fromB = new b.RateLimitError(429, { code: "rate_limited" }, new Headers());
    expect(fromB instanceof a.VaquillError).toBe(true);
    expect(fromB instanceof a.APIStatusError).toBe(true);
    expect(fromB instanceof a.RateLimitError).toBe(true);
    expect(fromB instanceof a.NotFoundError).toBe(false);
    expect(a.VaquillError.isVaquillError(fromB)).toBe(true);
    expect(a.isVaquillError(new b.APITimeoutError())).toBe(true);
    expect(new b.APITimeoutError() instanceof a.APIConnectionError).toBe(true);
    expect(a.isVaquillError(new Error("x"))).toBe(false);
    expect(a.isVaquillError({ name: "VaquillError" })).toBe(false);
    expect(new Error("x") instanceof a.VaquillError).toBe(false);
  });
});

describe("logging", () => {
  function logged(
    options: ConstructorParameters<typeof Vaquill>[0],
    steps: Parameters<typeof makeClient>[0],
  ) {
    const lines: Record<string, string[]> = { debug: [], info: [], warn: [], error: [] };
    const logger = {
      debug: (m: string) => lines.debug?.push(m),
      info: (m: string) => lines.info?.push(m),
      warn: (m: string) => lines.warn?.push(m),
      error: (m: string) => lines.error?.push(m),
    };
    const made = makeClient(steps, { logger, ...options });
    return { ...made, lines };
  }

  it("debug level logs requests and responses without the API key", async () => {
    const { client, lines } = logged({ logLevel: "debug" }, [
      json(200, { creditsConsumed: 0 }, { "x-request-id": "r1" }),
    ]);
    await client.statutes.search(search);
    const all = JSON.stringify(lines);
    expect(lines.debug?.some((l) => l.startsWith("request POST"))).toBe(true);
    expect(lines.debug?.some((l) => l.includes("status=200") && l.includes("request-id=r1"))).toBe(
      true,
    );
    expect(all).not.toContain(KEY);
    expect(all).not.toMatch(/Bearer vq_key/);
  });

  it("redacts the key even when a message embeds it", async () => {
    const { client, lines } = logged({ logLevel: "info" }, [json(200, {})]);
    await client.rawRequest("GET", `/p/${KEY}`);
    expect(JSON.stringify(lines)).not.toContain(KEY);
  });

  it("info level logs retries", async () => {
    vi.useFakeTimers();
    const { client, lines } = logged({ logLevel: "info" }, [json(503, {}), json(200, {})]);
    const p = client.credits.balance();
    await vi.runAllTimersAsync();
    await p;
    expect(lines.info?.some((l) => l.includes("retry GET") && l.includes("503"))).toBe(true);
    expect(lines.debug).toHaveLength(0);
  });

  it("warns once per method and path on Deprecation or Sunset", async () => {
    const dep = json(200, {}, { deprecation: "true", sunset: "Wed, 01 Jul 2027 00:00:00 GMT" });
    const { client, lines } = logged({}, [dep]);
    await client.credits.balance();
    await client.credits.balance();
    await client.rawRequest("GET", "/other");
    expect(lines.warn).toHaveLength(2);
    expect(lines.warn?.[0]).toContain("Sunset: Wed, 01 Jul 2027");
    const derived = client.withOptions({ maxRetries: 0 });
    await derived.credits.balance();
    expect(lines.warn).toHaveLength(2);
  });

  it("logLevel off silences everything and a partial logger is accepted", async () => {
    const { client, lines } = logged({ logLevel: "off" }, [json(200, {}, { sunset: "x" })]);
    await client.credits.balance();
    expect(Object.values(lines).flat()).toHaveLength(0);

    const warn = vi.fn();
    const partial = makeClient([json(200, {}, { sunset: "x" })], {
      logger: { warn },
      logLevel: "debug",
    });
    await partial.client.credits.balance();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("rejects an unknown logLevel", () => {
    expect(() => new Vaquill({ apiKey: KEY, logLevel: "loud" as never })).toThrow(TypeError);
  });

  it("a throwing logger never breaks a request", async () => {
    const { client } = makeClient([json(200, { ok: 1 })], {
      logLevel: "debug",
      logger: {
        debug() {
          throw new Error("boom");
        },
      },
    });
    await expect(client.credits.balance()).resolves.toEqual({ ok: 1 });
  });
});

describe("misc", () => {
  it("keeps connection errors as APIConnectionError", async () => {
    const { client } = makeClient([new TypeError("fetch failed")], { maxRetries: 0 });
    await expect(client.credits.balance()).rejects.toBeInstanceOf(APIConnectionError);
  });
});
