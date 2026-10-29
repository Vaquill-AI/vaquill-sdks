import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createVaquillTools } from "../src/index.js";
import { exec, type Fake, startFake } from "./helpers.js";

let fake: Fake;
beforeAll(async () => {
  fake = await startFake();
});
afterAll(() => fake.close());
beforeEach(() => {
  fake.requests.length = 0;
  fake.handle(() => ({ body: { creditsConsumed: 2, marker: "payload" } }));
});

interface Case {
  tool: string;
  input: Record<string, unknown>;
  method: string;
  path: string;
  query?: Record<string, string>;
  body?: Record<string, unknown>;
}

const CASES: Case[] = [
  {
    tool: "searchStatutes",
    input: { query: "adverse possession", state: "tx", corpusType: "STATE" },
    method: "POST",
    path: "/api/v1/us/statutes/search",
    body: { query: "adverse possession", state: "tx", corpusType: "STATE", limit: 5 },
  },
  {
    tool: "getStatuteSection",
    input: { actId: "USC_42_1983" },
    method: "GET",
    path: "/api/v1/us/statutes/section/USC_42_1983",
  },
  {
    tool: "getStatuteSectionText",
    input: { actId: "USC/42 1983", pinpoint: "(a)" },
    method: "GET",
    path: "/api/v1/us/statutes/section/USC%2F42%201983/body",
    query: { format: "plain", pinpoint: "(a)" },
  },
  {
    tool: "resolveCitation",
    input: { cite: "42 U.S.C. 1983", state: "federal" },
    method: "GET",
    path: "/api/v1/us/statutes/resolve",
    query: { cite: "42 U.S.C. 1983", state: "federal" },
  },
  {
    tool: "resolveCitations",
    input: { citations: ["42 U.S.C. 1983", "12 CFR 1026.3"] },
    method: "POST",
    path: "/api/v1/us/statutes/resolve",
    body: { citations: ["42 U.S.C. 1983", "12 CFR 1026.3"] },
  },
  {
    tool: "extractCitations",
    input: { text: "See 42 U.S.C. 1983.", resolve: false },
    method: "POST",
    path: "/api/v1/us/statutes/extract-citations",
    body: { text: "See 42 U.S.C. 1983.", resolve: false },
  },
  {
    tool: "countSections",
    input: { state: "ca", titleNumber: 5 },
    method: "POST",
    path: "/api/v1/us/statutes/count",
    body: { state: "ca", titleNumber: 5 },
  },
  {
    tool: "listDivisions",
    input: { corpusType: "STATE", state: "tx", code: "tx_pe" },
    method: "GET",
    path: "/api/v1/us/statutes/divisions",
    query: { corpusType: "STATE", state: "tx", code: "tx_pe" },
  },
  {
    tool: "sectionChanges",
    input: { actId: "A1", order: "asc" },
    method: "GET",
    path: "/api/v1/us/statutes/section/A1/changes",
    query: { limit: "20", order: "asc" },
  },
  {
    tool: "citedBy",
    input: { actId: "A1" },
    method: "GET",
    path: "/api/v1/us/statutes/section/A1/cited-by",
    query: { limit: "10" },
  },
  {
    tool: "definitions",
    input: { actId: "A1" },
    method: "GET",
    path: "/api/v1/us/statutes/section/A1/definitions",
  },
  {
    tool: "neighbors",
    input: { actId: "A1", limit: 2 },
    method: "GET",
    path: "/api/v1/us/statutes/section/A1/related",
    query: { limit: "2" },
  },
  {
    tool: "searchSessionLaws",
    input: { query: "appropriations", jurisdiction: "tx" },
    method: "POST",
    path: "/api/v1/us/session-laws/search",
    body: { query: "appropriations", jurisdiction: "tx", limit: 5 },
  },
  {
    tool: "getSessionLaw",
    input: { sessionLawId: "us1_abc", jurisdiction: "tx" },
    method: "GET",
    path: "/api/v1/us/session-laws/us1_abc",
    query: { jurisdiction: "tx" },
  },
  {
    tool: "creditBalance",
    input: {},
    method: "GET",
    path: "/api/v1/credits/balance",
  },
  {
    tool: "listWatches",
    input: { limit: 5 },
    method: "GET",
    path: "/api/v1/watches",
    query: { limit: "5" },
  },
  {
    tool: "createWatch",
    input: { corpusType: "USC", channel: "email", emailAddress: "a@example.com" },
    method: "POST",
    path: "/api/v1/watches",
    body: { corpusType: "USC", channel: "email", emailAddress: "a@example.com" },
  },
  {
    tool: "updateWatch",
    input: { watchId: "w1", isActive: false },
    method: "PATCH",
    path: "/api/v1/watches/w1",
    body: { isActive: false },
  },
  {
    tool: "testWatch",
    input: { watchId: "w1" },
    method: "POST",
    path: "/api/v1/watches/w1/test",
  },
];

describe("every tool runs through execute against the fake server", () => {
  for (const c of CASES) {
    it(c.tool, async () => {
      const tools = createVaquillTools({ client: fake.client(), allowWrites: true }) as Record<
        string,
        unknown
      >;
      const result = await exec(tools[c.tool], c.input);
      expect(result.ok).toBe(true);
      expect(result.data).toMatchObject({ marker: "payload" });
      expect(result.creditsSpentSoFar).toBeGreaterThanOrEqual(0);

      expect(fake.requests).toHaveLength(1);
      const req = fake.requests[0];
      if (!req) throw new Error("no request reached the fake server");
      expect(req.method).toBe(c.method);
      expect(req.path).toBe(c.path);
      if (c.query) expect(req.query).toMatchObject(c.query);
      if (c.body) expect(req.body).toMatchObject(c.body);
      // The bearer key goes to the server, never into the tool result.
      expect(JSON.stringify(result)).not.toContain("vq_key_");
    });
  }

  it("deleteWatch resolves to a confirmation on 204", async () => {
    fake.handle(() => ({ status: 204 }));
    const tools = createVaquillTools({ client: fake.client(), allowWrites: true });
    const result = await exec(tools.deleteWatch, { watchId: "w9" });
    expect(result).toMatchObject({ ok: true, data: { deleted: true, watchId: "w9" } });
    expect(fake.requests[0]).toMatchObject({ method: "DELETE", path: "/api/v1/watches/w9" });
  });

  it("covers every tool name", () => {
    const tools = createVaquillTools({ client: fake.client(), allowWrites: true });
    const covered = new Set([...CASES.map((c) => c.tool), "deleteWatch"]);
    expect(new Set(Object.keys(tools))).toEqual(covered);
  });

  it("reports credits the server charged", async () => {
    const client = fake.client();
    const tools = createVaquillTools({ client });
    const a = await exec(tools.searchStatutes, { query: "x" });
    const b = await exec(tools.searchStatutes, { query: "y" });
    expect(a.creditsSpentSoFar).toBe(2);
    expect(b.creditsSpentSoFar).toBe(4);
  });

  it("replaces an oversized result with a preview and a note", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 1, content: "x".repeat(5000) } }));
    const tools = createVaquillTools({ client: fake.client(), maxResultChars: 1000 });
    const result = await exec(tools.getStatuteSectionText, { actId: "A1" });
    expect(result).toMatchObject({ ok: true, truncated: true });
    expect(result.totalChars).toBeGreaterThan(5000);
    expect(String(result.preview).length).toBeLessThanOrEqual(2000);
    expect(result.note).toMatch(/narrow/);
    expect(result.data).toBeUndefined();
  });

  it("passes the abort signal to the request", async () => {
    fake.handle(() => ({ body: { creditsConsumed: 0 }, delay: 300 }));
    const tools = createVaquillTools({ client: fake.client() });
    const ctl = new AbortController();
    const pending = exec(tools.creditBalance, {}, ctl.signal);
    setTimeout(() => ctl.abort(), 30);
    await expect(pending).rejects.toBeTruthy();
  });
});
