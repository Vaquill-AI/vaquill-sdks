import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  isWebhookEvent,
  PageIterator,
  SpendGuardExceededError,
  signWebhook,
  unwrapWebhook,
  verifyWebhook,
  type WebhookEvent,
  WebhookVerificationError,
} from "../src/index.js";
import { json, makeClient } from "./helpers.js";

const SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw";
const ID = "msg_p5jXN8AQM9LWM0D4loKWxJek";
const TS = 1614265330;

describe("PageIterator truncated and stuck", () => {
  const pager = (pages: number[][], next: (i: number) => number | undefined) =>
    new PageIterator(
      0,
      async (i) => pages[i] ?? [],
      (p) => p,
      (_p, i) => next(i),
      {},
    );

  it("flags truncation by maxPages and maxItems only when data was left", async () => {
    const mk = (limits: { maxPages?: number; maxItems?: number }) =>
      new PageIterator(
        0,
        async (i) => [i * 2, i * 2 + 1],
        (p) => p,
        (_p, i) => (i < 2 ? i + 1 : undefined),
        limits,
      );
    const a = mk({ maxPages: 2 });
    expect(await a.toArray()).toHaveLength(4);
    expect(a.truncated).toBe(true);
    const b = mk({ maxPages: 3 });
    await b.toArray();
    expect(b.truncated).toBe(false);
    const c = mk({ maxItems: 3 });
    expect(await c.toArray()).toHaveLength(3);
    expect(c.truncated).toBe(true);
    const d = mk({ maxItems: 6 });
    expect(await d.toArray()).toHaveLength(6);
    expect(d.truncated).toBe(false);
    const e = mk({ maxItems: 1 });
    await e.toArray();
    expect(e.truncated).toBe(true);
  });

  it("stops on a cursor cycle A, B, A and sets stuck", async () => {
    const calls: string[] = [];
    const graph: Record<string, string> = { A: "B", B: "A" };
    const it = new PageIterator<string, string, string>(
      "A",
      async (c) => {
        calls.push(c);
        return c;
      },
      (p) => [p],
      (p) => graph[p],
    );
    expect(await it.toArray()).toEqual(["A", "B"]);
    expect(calls).toEqual(["A", "B"]);
    expect(it.stuck).toBe(true);
    expect(it.truncated).toBe(false);
  });

  it("stops on a repeated offset and resets flags on the next walk", async () => {
    const it = pager([[1], [2]], () => 0);
    expect(await it.toArray()).toEqual([1]);
    expect(it.stuck).toBe(true);
    const ok = pager([[1]], () => undefined);
    await ok.toArray();
    expect(ok.stuck).toBe(false);
  });
});

describe("watches.listAll", () => {
  const w = (n: number, hasMore?: boolean) =>
    json(200, {
      data: { watches: Array.from({ length: n }, (_, i) => ({ id: `w${i}` })) },
      meta: hasMore === undefined ? {} : { hasMore },
    });

  it("keeps going past a short page, stopping on an empty one", async () => {
    const { client, calls } = makeClient([w(3), w(2), w(0)]);
    const got = await client.watches.listAll({ limit: 5 }).toArray();
    expect(got).toHaveLength(5);
    expect(calls.map((c) => c.url.searchParams.get("offset"))).toEqual(["0", "3", "5"]);
  });

  it("stops without an extra request when hasMore is false", async () => {
    const { client, calls } = makeClient([w(3, true), w(2, false), w(0)]);
    expect(await client.watches.listAll().toArray()).toHaveLength(5);
    expect(calls).toHaveLength(2);
  });
});

describe("webhooks hardening", () => {
  const body = '{"event":"board.updated","firedAt":"2026-01-01T00:00:00Z","deliveryId":"w:1"}';

  it("considers every element of a multi-valued signature header", async () => {
    const good = await signWebhook(ID, TS, body, SECRET);
    const bad = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    const base = { "webhook-id": ID, "webhook-timestamp": String(TS) };
    await verifyWebhook(body, { ...base, "webhook-signature": [bad, good] }, SECRET, { now: TS });
    await verifyWebhook(body, { ...base, "webhook-signature": [good, bad] }, SECRET, { now: TS });
    await expect(
      verifyWebhook(body, { ...base, "webhook-signature": [bad] }, SECRET, { now: TS }),
    ).rejects.toBeInstanceOf(WebhookVerificationError);
    // A Headers object folds repeated values with ", ".
    const h = new Headers(base);
    h.append("webhook-signature", bad);
    h.append("webhook-signature", good);
    await verifyWebhook(body, h, SECRET, { now: TS });
  });

  it("refuses conflicting repeated id headers", async () => {
    const sig = await signWebhook(ID, TS, body, SECRET);
    await expect(
      verifyWebhook(
        body,
        {
          "webhook-id": [ID, "msg_other"],
          "webhook-timestamp": String(TS),
          "webhook-signature": sig,
        },
        SECRET,
        { now: TS },
      ),
    ).rejects.toThrow(/Conflicting/);
  });

  it("throws on an empty, blank or bare-prefix secret instead of verifying forgeries", async () => {
    const forged = await signWebhook(ID, TS, body, "x");
    const headers = {
      "webhook-id": ID,
      "webhook-timestamp": String(TS),
      "webhook-signature": forged,
    };
    for (const s of ["", "   ", "whsec_", ["a", " "], [], undefined as unknown as string]) {
      await expect(verifyWebhook(body, headers, s, { now: TS })).rejects.toThrow(
        /No webhook secret/,
      );
    }
    await expect(signWebhook(ID, TS, body, "")).rejects.toBeInstanceOf(WebhookVerificationError);
  });

  it("unwraps to a typed event and keeps the generic escape hatch", async () => {
    const sig = await signWebhook(ID, TS, body, SECRET);
    const headers = { "webhook-id": ID, "webhook-timestamp": String(TS), "webhook-signature": sig };
    const ev: WebhookEvent = await unwrapWebhook(body, headers, SECRET, { now: TS });
    expect(ev.event).toBe("board.updated");
    expect(isWebhookEvent(ev)).toBe(true);
    if (ev.event === "board.updated") expect(ev.firedAt).toBe("2026-01-01T00:00:00Z");
    const custom = await unwrapWebhook<{ event: string; deliveryId: string }>(
      body,
      headers,
      SECRET,
      { now: TS },
    );
    expect(custom.deliveryId).toBe("w:1");
    expect(isWebhookEvent({ nope: 1 })).toBe(false);
  });

  it("rejects a signed body that is not a JSON object", async () => {
    const arr = "[1]";
    const sig = await signWebhook(ID, TS, arr, SECRET);
    await expect(
      unwrapWebhook(
        arr,
        { "webhook-id": ID, "webhook-timestamp": String(TS), "webhook-signature": sig },
        SECRET,
        { now: TS },
      ),
    ).rejects.toThrow(/JSON object/);
  });
});

describe("batch helpers", () => {
  const cites = (n: number) => Array.from({ length: n }, (_, i) => `c${i}`);
  const resolveReply = (c: unknown) =>
    json(200, { results: (c as { citations: string[] }).citations.map((x) => ({ citation: x })) });

  it("resolveBatchAll chunks at 500, de-duplicates and flattens in order", async () => {
    const { client, calls } = makeClient([() => resolveReply(calls.at(-1)?.body)]);
    const input = [...cites(1100), "c0", "c5"];
    const out = await client.statutes.resolveBatchAll(input, { state: "tx" } as never);
    expect(calls.map((c) => (c.body as { citations: string[] }).citations.length)).toEqual([
      500, 500, 100,
    ]);
    expect(out).toHaveLength(1100);
    expect((out[1099] as unknown as { citation: string }).citation).toBe("c1099");
    expect((calls[1]?.body as { state: string } | undefined)?.state).toBe("tx");
  });

  it("getSectionsAll chunks at 50 and sends nothing for empty input", async () => {
    const { client, calls } = makeClient([
      () => json(200, { sections: [{ actId: "a" }] }),
      () => json(200, { sections: [{ actId: "b" }] }),
    ]);
    const ids = Array.from({ length: 51 }, (_, i) => `id${i}`);
    const out = await client.statutes.getSectionsAll(ids);
    expect(calls.map((c) => (c.body as { actIds: string[] }).actIds.length)).toEqual([50, 1]);
    expect(out).toHaveLength(2);
    expect(await client.statutes.getSectionsAll([])).toEqual([]);
    expect(calls).toHaveLength(2);
  });

  it("getBatchAll chunks at 200 and suffixes the caller's idempotency key after chunk 0", async () => {
    const { client, calls } = makeClient([json(200, { laws: [{ sessionLawId: "x" }] })]);
    const ids = Array.from({ length: 401 }, (_, i) => `sl${i}`);
    const out = await client.sessionLaws.getBatchAll(ids, undefined, {
      idempotencyKey: "my-key-0123456789",
    });
    expect(calls.map((c) => (c.body as { ids: string[] }).ids.length)).toEqual([200, 200, 1]);
    expect(calls.map((c) => c.headers.get("idempotency-key"))).toEqual([
      "my-key-0123456789",
      "my-key-0123456789-1",
      "my-key-0123456789-2",
    ]);
    expect(out).toHaveLength(3);
  });

  it("stops between chunks when the spend guard is reached", async () => {
    const { client, calls } = makeClient([json(200, { results: [], creditsConsumed: 10 })], {
      maxCredits: 10,
    });
    await expect(client.statutes.resolveBatchAll(cites(600))).rejects.toBeInstanceOf(
      SpendGuardExceededError,
    );
    expect(calls).toHaveLength(1);
  });
});

describe("sessionLaws.iterBody", () => {
  const page = (over: object) =>
    json(200, { available: true, text: "t", totalChars: 100, totalPages: 1, ...over });

  it("follows nextCursor, drops startChar after the first page, and stops at pageEnd", async () => {
    const { client, calls } = makeClient([
      page({ hasMore: true, nextCursor: "c1", pageEnd: 40 }),
      page({ hasMore: true, nextCursor: "c2", pageEnd: 100 }),
      page({ hasMore: false, nextCursor: null }),
    ]);
    const pages = await client.sessionLaws.iterBody("us1_x", { startChar: 5 }).toArray();
    expect(pages).toHaveLength(2);
    expect(calls).toHaveLength(2);
    expect(calls[0]?.url.searchParams.get("startChar")).toBe("5");
    expect(calls[1]?.url.searchParams.get("cursor")).toBe("c1");
    expect(calls[1]?.url.searchParams.has("startChar")).toBe(false);
  });

  it("ignores totalPages, stops on a falsy cursor, and flags maxPages truncation", async () => {
    const a = makeClient([page({ hasMore: true, nextCursor: "", totalPages: 9, pageEnd: 10 })]);
    expect(await a.client.sessionLaws.iterBody("x").toArray()).toHaveLength(1);
    const b = makeClient([
      page({ hasMore: true, nextCursor: "c1", pageEnd: 10 }),
      page({ hasMore: true, nextCursor: "c2", pageEnd: 20 }),
    ]);
    const it = b.client.sessionLaws.iterBody("x", undefined, { maxPages: 1 });
    expect(await it.toArray()).toHaveLength(1);
    expect(it.truncated).toBe(true);
  });
});

describe("schema aliases", () => {
  const spec = JSON.parse(readFileSync("../openapi/vaquill-us.json", "utf8")) as {
    components: { schemas: Record<string, unknown> };
  };
  const source = readFileSync("src/schemas.ts", "utf8");
  const api = readFileSync("src/_generated/api.d.ts", "utf8");
  const aliased = new Set(
    [...source.matchAll(/^export type (\w+) = components\["schemas"\]\["([^"]+)"\];$/gm)].map(
      (m) => m[2] as string,
    ),
  );
  const pruned = (n: string) =>
    !api.slice(api.indexOf("export interface components")).includes(`"${n}":`);

  it("has an alias for every schema that api.d.ts carries", () => {
    const missing = Object.keys(spec.components.schemas).filter(
      (n) => !aliased.has(n) && !pruned(n),
    );
    expect(missing, "run `npm run gen:aliases`").toEqual([]);
  });

  it("aliases nothing the spec no longer has", () => {
    const stale = [...aliased].filter((n) => !(n in spec.components.schemas));
    expect(stale, "run `npm run gen:aliases`").toEqual([]);
  });

  it("is re-exported from the package entry", () => {
    expect(readFileSync("src/index.ts", "utf8")).toContain('export * from "./schemas.js"');
  });
});
