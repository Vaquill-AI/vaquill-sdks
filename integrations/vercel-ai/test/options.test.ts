import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createVaquillTools, vaquillTools } from "../src/index.js";
import { exec, type Fake, startFake, TEST_KEY } from "./helpers.js";

const EM_DASH = String.fromCharCode(0x2014);

let fake: Fake;
beforeAll(async () => {
  fake = await startFake();
});
afterAll(() => fake.close());

const READ = [
  "searchStatutes",
  "getStatuteSection",
  "getStatuteSectionText",
  "resolveCitation",
  "resolveCitations",
  "extractCitations",
  "countSections",
  "listDivisions",
  "sectionChanges",
  "citedBy",
  "definitions",
  "neighbors",
  "searchSessionLaws",
  "getSessionLaw",
  "creditBalance",
];
const WRITE = ["listWatches", "createWatch", "updateWatch", "deleteWatch", "testWatch"];

describe("tool selection", () => {
  it("is read-only by default and exposes exactly the documented tools", () => {
    const tools = createVaquillTools({ client: fake.client() });
    expect(Object.keys(tools).sort()).toEqual([...READ].sort());
  });

  it("allowWrites adds the watch tools", () => {
    const tools = createVaquillTools({ client: fake.client(), allowWrites: true });
    expect(Object.keys(tools).sort()).toEqual([...READ, ...WRITE].sort());
  });

  it("include keeps only the named tools", () => {
    const tools = createVaquillTools({
      client: fake.client(),
      include: ["searchStatutes", "creditBalance"],
    });
    expect(Object.keys(tools).sort()).toEqual(["creditBalance", "searchStatutes"]);
  });

  it("exclude drops tools, after include", () => {
    const tools = createVaquillTools({
      client: fake.client(),
      include: ["searchStatutes", "creditBalance"],
      exclude: ["creditBalance"],
    });
    expect(Object.keys(tools)).toEqual(["searchStatutes"]);
    const all = createVaquillTools({ client: fake.client(), exclude: ["extractCitations"] });
    expect(all.extractCitations).toBeUndefined();
    expect(all.searchStatutes).toBeDefined();
  });

  it("asking for a write tool without allowWrites throws", () => {
    expect(() => createVaquillTools({ client: fake.client(), include: ["deleteWatch"] })).toThrow(
      /allowWrites/,
    );
  });

  it("excluding a write tool with allowWrites keeps the others", () => {
    const tools = createVaquillTools({
      client: fake.client(),
      allowWrites: true,
      include: ["createWatch", "deleteWatch"],
      exclude: ["deleteWatch"],
    });
    expect(Object.keys(tools)).toEqual(["createWatch"]);
  });

  it("unknown names throw with the list of known tools", () => {
    expect(() => createVaquillTools({ client: fake.client(), include: ["nope" as never] })).toThrow(
      /unknown tool "nope".*searchStatutes/,
    );
    expect(() => createVaquillTools({ client: fake.client(), exclude: ["nope" as never] })).toThrow(
      TypeError,
    );
  });

  it("every tool has a model-facing description and an input schema", () => {
    const tools = createVaquillTools({ client: fake.client(), allowWrites: true });
    for (const [name, t] of Object.entries(tools)) {
      const tool = t as { description?: string; inputSchema?: unknown };
      expect(tool.description?.length, name).toBeGreaterThan(40);
      expect(tool.inputSchema, name).toBeDefined();
      expect(tool.description, name).not.toContain(EM_DASH);
    }
  });

  it("every credit-charging tool says so, and the free ones say FREE", () => {
    const tools = createVaquillTools({ client: fake.client(), allowWrites: true }) as Record<
      string,
      { description: string }
    >;
    const free = new Set([
      "creditBalance",
      "listWatches",
      "createWatch",
      "updateWatch",
      "deleteWatch",
      "testWatch",
    ]);
    for (const [name, t] of Object.entries(tools)) {
      if (free.has(name)) continue;
      expect(t.description, name).toMatch(/COSTS CREDITS/);
    }
    expect(tools.creditBalance?.description).toMatch(/FREE/);
  });
});

describe("vaquillTools", () => {
  it("reads VAQUILL_API_KEY and VAQUILL_BASE_URL from the environment", async () => {
    const saved = { k: process.env.VAQUILL_API_KEY, u: process.env.VAQUILL_BASE_URL };
    process.env.VAQUILL_API_KEY = TEST_KEY;
    process.env.VAQUILL_BASE_URL = fake.url;
    try {
      fake.requests.length = 0;
      const tools = vaquillTools();
      const result = await exec(tools.creditBalance, {});
      expect(result.ok).toBe(true);
      expect(fake.requests[0]?.headers.authorization).toBe(`Bearer ${TEST_KEY}`);
    } finally {
      for (const [name, v] of [
        ["VAQUILL_API_KEY", saved.k],
        ["VAQUILL_BASE_URL", saved.u],
      ] as const) {
        if (v === undefined) delete process.env[name];
        else process.env[name] = v;
      }
    }
  });

  it("an explicit apiKey is sent", async () => {
    fake.requests.length = 0;
    const prev = process.env.VAQUILL_BASE_URL;
    process.env.VAQUILL_BASE_URL = fake.url;
    try {
      const tools = createVaquillTools({ apiKey: "vq_key_explicit_0123456789" });
      await exec(tools.creditBalance, {});
      expect(fake.requests[0]?.headers.authorization).toBe("Bearer vq_key_explicit_0123456789");
    } finally {
      if (prev === undefined) delete process.env.VAQUILL_BASE_URL;
      else process.env.VAQUILL_BASE_URL = prev;
    }
  });
});
