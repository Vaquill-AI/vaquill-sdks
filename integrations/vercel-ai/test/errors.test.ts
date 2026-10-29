import { Vaquill } from "@vaquill-ai/sdk";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createVaquillTools, scrub, toToolFailure } from "../src/index.js";
import { exec, type Fake, startFake, TEST_KEY } from "./helpers.js";

let fake: Fake;
beforeAll(async () => {
  fake = await startFake();
});
afterAll(() => fake.close());
beforeEach(() => {
  fake.requests.length = 0;
});

const MATRIX: Array<[number, string, boolean, Record<string, unknown>?]> = [
  [400, "invalid_request", false],
  [401, "authentication", false],
  [402, "insufficient_credits", false],
  [403, "permission_denied", false],
  [404, "not_found", false],
  [422, "invalid_request", false, { errors: [{ loc: ["body", "limit"], msg: "must be <= 50" }] }],
  [429, "rate_limited", true, { retryAfterSeconds: 7 }],
  [500, "server_error", true],
  [503, "server_error", true],
];

describe("errors become a structured result the model can act on", () => {
  for (const [status, kind, retryable, extra] of MATRIX) {
    it(`HTTP ${status} -> ${kind}`, async () => {
      fake.handle(() => ({
        status,
        body: { detail: "nope", requestId: "req_123", code: "some_code", ...extra },
      }));
      const tools = createVaquillTools({ client: fake.client() });
      const result = await exec(tools.searchStatutes, { query: "x" });
      expect(result.ok).toBe(false);
      expect(result.error.kind).toBe(kind);
      expect(result.error.retryable).toBe(retryable);
      expect(result.error.status).toBe(status);
      expect(result.error.hint.length).toBeGreaterThan(10);
      expect(result.error.requestId).toBe("req_123");
      expect(Object.keys(result)).toEqual(["ok", "error"]);
      expect(JSON.stringify(result)).not.toMatch(/\bat .*\.(ts|js):\d+/);
    });
  }

  it("422 carries the field that was wrong", async () => {
    fake.handle(() => ({
      status: 422,
      body: { errors: [{ loc: ["body", "limit"], msg: "must be <= 50", type: "x" }] },
    }));
    const tools = createVaquillTools({ client: fake.client() });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(result.error.message).toContain("limit: must be <= 50");
  });

  it("429 carries retryAfterSeconds", async () => {
    fake.handle(() => ({ status: 429, body: { retryAfterSeconds: 7 } }));
    const tools = createVaquillTools({ client: fake.client() });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(result.error.retryAfterSeconds).toBe(7);
  });

  it("a daily cap is not retryable", async () => {
    fake.handle(() => ({ status: 429, body: { code: "daily_cap_exceeded" } }));
    const tools = createVaquillTools({ client: fake.client() });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(["daily_cap", "rate_limited"]).toContain(result.error.kind);
  });

  it("a timeout is retryable", async () => {
    fake.handle(() => ({ body: {}, delay: 400 }));
    const tools = createVaquillTools({ client: fake.client({ timeout: 50 }) });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(result.error).toMatchObject({ kind: "timeout", retryable: true });
  });

  it("an unreachable server is a connection error", async () => {
    const dead = await startFake();
    const url = dead.url;
    await dead.close();
    const tools = createVaquillTools({
      client: new Vaquill({ apiKey: TEST_KEY, baseURL: url, maxRetries: 0, logLevel: "off" }),
    });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(result.error).toMatchObject({ kind: "connection", retryable: true });
  });

  it("an unreadable success body is bad_response", async () => {
    fake.handle(() => ({ body: undefined, status: 200, headers: {} }));
    const raw = new Vaquill({
      apiKey: TEST_KEY,
      baseURL: fake.url,
      maxRetries: 0,
      logLevel: "off",
      fetch: async () => new Response("<html>oops</html>", { status: 200 }),
    });
    const tools = createVaquillTools({ client: raw });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(result.error.kind).toBe("bad_response");
  });

  it("never leaks the key, even when the server echoes it", async () => {
    fake.handle(() => ({
      status: 400,
      body: { detail: `bad key ${TEST_KEY} and Bearer ${TEST_KEY}`, code: TEST_KEY },
    }));
    const tools = createVaquillTools({ client: fake.client() });
    const result = await exec(tools.searchStatutes, { query: "x" });
    const text = JSON.stringify(result);
    expect(text).not.toContain(TEST_KEY);
    expect(text).not.toContain("vq_key_");
    expect(text).toContain("[redacted]");
  });

  it("a non-Vaquill exception is a generic result without its message", () => {
    const out = toToolFailure(new TypeError(`boom ${TEST_KEY}`));
    expect(out.error.kind).toBe("unexpected");
    expect(JSON.stringify(out)).not.toContain("boom");
    expect(JSON.stringify(out)).not.toContain(TEST_KEY);
    expect(toToolFailure("a string").error.kind).toBe("unexpected");
  });

  it("scrub redacts configured secrets and caps length", () => {
    expect(scrub("token abcdefgh1234 here", ["abcdefgh1234"])).toBe("token [redacted] here");
    expect(scrub("short", ["abc"])).toBe("short");
    expect(scrub("y".repeat(900)).length).toBeLessThan(510);
    expect(scrub("key vq_ws_abcDEF-123")).toBe("key [redacted]");
  });

  it("the redact option scrubs extra strings", async () => {
    fake.handle(() => ({ status: 400, body: { detail: "internal-host-42 refused" } }));
    const tools = createVaquillTools({ client: fake.client(), redact: ["internal-host-42"] });
    const result = await exec(tools.searchStatutes, { query: "x" });
    expect(JSON.stringify(result)).not.toContain("internal-host-42");
  });

  it("an abort is rethrown so the loop stops", async () => {
    fake.handle(() => ({ body: {}, delay: 300 }));
    const tools = createVaquillTools({ client: fake.client() });
    const ctl = new AbortController();
    const pending = exec(tools.creditBalance, {}, ctl.signal);
    setTimeout(() => ctl.abort(), 20);
    await expect(pending).rejects.toThrow();
  });
});

describe("spend guard", () => {
  it("stops charged calls once maxCredits is reached and sends no request", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 3 } }));
    const tools = createVaquillTools({ client: fake.client(), maxCredits: 5 });
    const r1 = await exec(tools.searchStatutes, { query: "a" });
    const r2 = await exec(tools.searchStatutes, { query: "b" });
    expect(r1.ok && r2.ok).toBe(true);
    expect(r2.creditsSpentSoFar).toBe(6);
    const before = fake.requests.length;
    const r3 = await exec(tools.getStatuteSection, { actId: "A1" });
    expect(r3.ok).toBe(false);
    expect(r3.error).toMatchObject({ kind: "spend_limit", retryable: false });
    expect(r3.error.hint).toMatch(/Do not call any more tools that cost credits/);
    expect(fake.requests).toHaveLength(before);
  });

  it("does not block free calls", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 9 } }));
    const tools = createVaquillTools({ client: fake.client(), maxCredits: 1 });
    await exec(tools.searchStatutes, { query: "a" });
    const free = await exec(tools.creditBalance, {});
    expect(free.ok).toBe(true);
  });

  it("parallel tool calls cannot overshoot the cap", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 4 }, delay: 20 }));
    const tools = createVaquillTools({ client: fake.client(), maxCredits: 4 });
    const results = await Promise.all(
      Array.from({ length: 6 }, (_, i) => exec(tools.searchStatutes, { query: `q${i}` })),
    );
    expect(results.filter((r) => r.ok)).toHaveLength(1);
    expect(fake.requests).toHaveLength(1);
  });

  it("applies a default cap when this package builds the client", async () => {
    const prev = process.env.VAQUILL_BASE_URL;
    process.env.VAQUILL_BASE_URL = fake.url;
    try {
      fake.handle(() => ({ body: { creditsConsumed: 150 } }));
      const tools = createVaquillTools({ apiKey: TEST_KEY });
      await exec(tools.searchStatutes, { query: "a" });
      await exec(tools.searchStatutes, { query: "b" });
      const third = await exec(tools.searchStatutes, { query: "c" });
      expect(third.error?.kind).toBe("spend_limit");
    } finally {
      if (prev === undefined) delete process.env.VAQUILL_BASE_URL;
      else process.env.VAQUILL_BASE_URL = prev;
    }
  });

  it("maxCredits: Infinity switches the cap off", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 1000 } }));
    const tools = createVaquillTools({
      client: fake.client(),
      maxCredits: Number.POSITIVE_INFINITY,
    });
    await exec(tools.searchStatutes, { query: "a" });
    const again = await exec(tools.searchStatutes, { query: "b" });
    expect(again.ok).toBe(true);
  });
});
