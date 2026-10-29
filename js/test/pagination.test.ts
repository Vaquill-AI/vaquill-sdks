import { describe, expect, it } from "vitest";
import { json, makeClient } from "./helpers.js";

describe("offset pagination (statutes.searchAll)", () => {
  const pages = [
    json(200, { results: [{ n: 1 }, { n: 2 }], count: 2, hasMore: true, nextOffset: 2, offset: 0 }),
    json(200, { results: [{ n: 3 }, { n: 4 }], count: 2, hasMore: true, offset: 2 }),
    json(200, { results: [{ n: 5 }], count: 1, hasMore: false, offset: 4 }),
  ];

  it("follows nextOffset, then offset + count, and sends the offset in the body", async () => {
    const { client, calls } = makeClient(pages);
    const got = await client.statutes.searchAll({ query: "q", limit: 2 }).toArray();
    expect(got.map((r) => (r as unknown as { n: number }).n)).toEqual([1, 2, 3, 4, 5]);
    expect(calls.map((c) => (c.body as { offset: number }).offset)).toEqual([0, 2, 4]);
  });

  it("honours maxPages and maxItems", async () => {
    const a = makeClient(pages);
    const items = await a.client.statutes.searchAll({ query: "q" }, { maxPages: 2 }).toArray();
    expect(items).toHaveLength(4);
    expect(a.calls).toHaveLength(2);

    const b = makeClient(pages);
    const got: unknown[] = [];
    for await (const r of b.client.statutes.searchAll({ query: "q" }, { maxItems: 3 })) got.push(r);
    expect(got).toHaveLength(3);
    expect(b.calls).toHaveLength(2);
  });

  it("pages() yields whole pages", async () => {
    const { client } = makeClient(pages);
    const out = [];
    for await (const p of client.statutes.searchAll({ query: "q" }).pages()) out.push(p.count);
    expect(out).toEqual([2, 2, 1]);
  });

  it("stops rather than loop when hasMore is true but the page is empty", async () => {
    const { client, calls } = makeClient([json(200, { results: [], count: 0, hasMore: true })]);
    expect(await client.statutes.searchAll({ query: "q" }).toArray()).toEqual([]);
    expect(calls).toHaveLength(1);
  });
});

describe("cursor pagination", () => {
  it("follows nextCursor on divisions until null", async () => {
    const { client, calls } = makeClient([
      json(200, { divisions: [{ a: 1 }], nextCursor: "c2" }),
      json(200, { divisions: [{ a: 2 }], nextCursor: null }),
    ]);
    const got = await client.statutes.listDivisionsAll({ corpusType: "USC" }).toArray();
    expect(got).toHaveLength(2);
    expect(calls[0]?.url.searchParams.has("cursor")).toBe(false);
    expect(calls[1]?.url.searchParams.get("cursor")).toBe("c2");
  });

  it("follows nextCursor on the session-law registry while hasMore", async () => {
    const { client, calls } = makeClient([
      json(200, { results: [1], hasMore: true, nextCursor: "n1" }),
      json(200, { results: [2], hasMore: false, nextCursor: null }),
    ]);
    const got = await client.sessionLaws.listAll({ jurisdiction: "wa" }).toArray();
    expect(got).toEqual([1, 2]);
    expect(calls[1]?.url.searchParams.get("cursor")).toBe("n1");
  });
});

describe("sinceId / beforeId pagination", () => {
  it("walks a section's history newest first with beforeId", async () => {
    const { client, calls } = makeClient([
      json(200, { changes: [{ id: 30 }, { id: 20 }], hasMore: true, cursor: 30 }),
      json(200, { changes: [{ id: 10 }], hasMore: false, cursor: 10 }),
    ]);
    const got = await client.statutes.getSectionChangesAll("A1").toArray();
    expect(got).toHaveLength(3);
    expect(calls[0]?.url.searchParams.has("beforeId")).toBe(false);
    expect(calls[1]?.url.searchParams.get("beforeId")).toBe("20");
  });

  it("walks forward with sinceId when order is asc", async () => {
    const { client, calls } = makeClient([
      json(200, { changes: [{ id: 1 }, { id: 2 }], hasMore: true, cursor: 2 }),
      json(200, { changes: [{ id: 3 }], hasMore: false, cursor: 3 }),
    ]);
    await client.statutes.getSectionChangesAll("A1", { order: "asc" }).toArray();
    expect(calls[1]?.url.searchParams.get("sinceId")).toBe("2");
    expect(calls[1]?.url.searchParams.get("order")).toBe("asc");
  });

  it("session-law changes feed forward from a given sinceId", async () => {
    const { client, calls } = makeClient([
      json(200, { changes: [{ id: 6 }], hasMore: true, cursor: 6 }),
      json(200, { changes: [], hasMore: false, cursor: null }),
    ]);
    await client.sessionLaws.getChangesAll({ sinceId: 5 }).toArray();
    expect(calls.map((c) => c.url.searchParams.get("sinceId"))).toEqual(["5", "6"]);
  });

  it("watch changes use meta.cursor and meta.hasMore", async () => {
    const { client, calls } = makeClient([
      json(200, { data: { changes: [{ id: 9 }, { id: 8 }] }, meta: { hasMore: true, cursor: 9 } }),
      json(200, { data: { changes: [{ id: 7 }] }, meta: { hasMore: false, cursor: 9 } }),
    ]);
    const got = await client.watches.listChangesAll("w1").toArray();
    expect(got).toHaveLength(3);
    expect(calls[1]?.url.searchParams.get("beforeId")).toBe("8");
  });
});

describe("offset-only lists", () => {
  it("pages watches by offset until an empty page (a short page does not end it)", async () => {
    const { client, calls } = makeClient([
      json(200, { data: { watches: [{ id: "a" }, { id: "b" }] } }),
      json(200, { data: { watches: [{ id: "c" }] } }),
      json(200, { data: { watches: [] } }),
    ]);
    const got = await client.watches.listAll({ limit: 2 }).toArray();
    expect(got).toHaveLength(3);
    expect(calls.map((c) => c.url.searchParams.get("offset"))).toEqual(["0", "2", "3"]);
  });

  it("pages boards with hasMore", async () => {
    const { client, calls } = makeClient([
      json(200, { data: { boards: [1, 2], hasMore: true } }),
      json(200, { data: { boards: [3], hasMore: false } }),
    ]);
    expect(await client.boards.listAll().toArray()).toHaveLength(3);
    expect(calls[1]?.url.searchParams.get("offset")).toBe("2");
  });
});
