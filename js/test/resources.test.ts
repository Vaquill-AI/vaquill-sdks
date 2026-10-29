import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Vaquill } from "../src/index.js";
import { json, makeClient } from "./helpers.js";

/* biome-ignore lint/suspicious/noExplicitAny: the spec is read as plain JSON */
const spec: any = JSON.parse(
  readFileSync(new URL("../../openapi/vaquill-us.json", import.meta.url), "utf8"),
);

interface Op {
  method: string;
  template: string;
  params: { name: string; in: string }[];
  bodySchema?: string;
}
const ops = new Map<string, Op>();
for (const [template, item] of Object.entries<Record<string, any>>(spec.paths)) {
  for (const [method, o] of Object.entries<any>(item)) {
    const ref = o.requestBody?.content?.["application/json"]?.schema?.$ref as string | undefined;
    ops.set(o.operationId, {
      method: method.toUpperCase(),
      template,
      params: o.parameters ?? [],
      bodySchema: ref?.split("/").pop(),
    });
  }
}

type Case = {
  op: string;
  call: (c: Vaquill) => Promise<unknown>;
  path?: Record<string, string>;
  query?: Record<string, string>;
  body?: Record<string, unknown>;
};

const ACT = "TX_PE_22.01";
const cases: Case[] = [
  {
    op: "search_statutes",
    call: (c) => c.statutes.search({ query: "murder", limit: 5 }),
    body: { query: "murder", limit: 5 },
  },
  { op: "get_section", call: (c) => c.statutes.getSection(ACT), path: { act_id: ACT } },
  {
    op: "get_section_body",
    call: (c) => c.statutes.getSectionBody(ACT, { format: "plain", asOf: "2020-01-01" }),
    path: { act_id: ACT },
    query: { format: "plain", asOf: "2020-01-01" },
  },
  {
    op: "get_section_neighbors",
    call: (c) => c.statutes.getSectionNeighbors(ACT, { limit: 3 }),
    path: { act_id: ACT },
    query: { limit: "3" },
  },
  {
    op: "get_sections_batch",
    call: (c) => c.statutes.getSections({ actIds: [ACT], includeBody: true }),
    body: { actIds: [ACT], includeBody: true },
  },
  {
    op: "count_statute_sections",
    call: (c) => c.statutes.count({ query: "x" } as never),
    body: { query: "x" },
  },
  {
    op: "list_statutes_coverage",
    call: (c) => c.statutes.coverage({ state: "tx" } as never),
    query: { state: "tx" },
  },
  {
    op: "list_statute_divisions",
    call: (c) => c.statutes.listDivisions({ corpusType: "STATE", state: "tx" } as never),
    query: { corpusType: "STATE", state: "tx" },
  },
  {
    op: "get_section_changes",
    call: (c) => c.statutes.getSectionChanges(ACT, { limit: 2, order: "asc" }),
    path: { act_id: ACT },
    query: { limit: "2", order: "asc" },
  },
  {
    op: "get_section_enactments",
    call: (c) => c.statutes.getSectionEnactments(ACT),
    path: { act_id: ACT },
  },
  {
    op: "get_section_rulemaking",
    call: (c) => c.statutes.getSectionRulemaking(ACT),
    path: { act_id: ACT },
  },
  {
    op: "get_part_rulemaking",
    call: (c) => c.statutes.getPartRulemaking(17, "240", { years: 2 }),
    path: { title: "17", part: "240" },
    query: { years: "2" },
  },
  {
    op: "get_section_cited_by",
    call: (c) => c.statutes.getSectionCitedBy(ACT, { limit: 4 }),
    path: { act_id: ACT },
    query: { limit: "4" },
  },
  {
    op: "get_section_definitions",
    call: (c) => c.statutes.getSectionDefinitions(ACT),
    path: { act_id: ACT },
  },
  {
    op: "get_section_cross_state",
    call: (c) => c.statutes.getSectionCrossState(ACT, { limit: 4 }),
    path: { act_id: ACT },
    query: { limit: "4" },
  },
  {
    op: "resolve_statute_citation",
    call: (c) => c.statutes.resolve({ cite: "Tex. Penal Code 22.01" }),
    query: { cite: "Tex. Penal Code 22.01" },
  },
  {
    op: "resolve_statute_citations_batch",
    call: (c) => c.statutes.resolveBatch({ citations: ["a"] } as never),
    body: { citations: ["a"] },
  },
  {
    op: "extract_statute_citations",
    call: (c) => c.statutes.extractCitations({ text: "see 18 U.S.C. 1" } as never),
    body: { text: "see 18 U.S.C. 1" },
  },
  {
    op: "search_session_laws",
    call: (c) => c.sessionLaws.search({ query: "tax", limit: 2 }),
    body: { query: "tax", limit: 2 },
  },
  {
    op: "list_session_laws",
    call: (c) => c.sessionLaws.list({ jurisdiction: "wa", limit: 5 }),
    query: { jurisdiction: "wa", limit: "5" },
  },
  {
    op: "get_session_law",
    call: (c) => c.sessionLaws.get("us1_abc", { jurisdiction: "wa" }),
    path: { session_law_id: "us1_abc" },
    query: { jurisdiction: "wa" },
  },
  {
    op: "get_session_law_body",
    call: (c) => c.sessionLaws.getBody("us1_abc", { startChar: 10 }),
    path: { session_law_id: "us1_abc" },
    query: { startChar: "10" },
  },
  {
    op: "get_session_law_versions",
    call: (c) => c.sessionLaws.getVersions("us1_abc"),
    path: { session_law_id: "us1_abc" },
  },
  {
    op: "get_session_law_changes",
    call: (c) => c.sessionLaws.getChanges({ sinceId: 4, limit: 10 }),
    query: { sinceId: "4", limit: "10" },
  },
  {
    op: "get_session_laws_batch",
    call: (c) => c.sessionLaws.getBatch({ ids: ["a"] } as never),
    body: { ids: ["a"] },
  },
  {
    op: "list_watches",
    call: (c) => c.watches.list({ limit: 5, offset: 10 }),
    query: { limit: "5", offset: "10" },
  },
  {
    op: "create_watch",
    call: (c) =>
      c.watches.create({
        corpusType: "state",
        state: "wa",
        channel: "webhook",
        webhookUrl: "https://e.test/h",
      } as never),
    body: { corpusType: "state", state: "wa", channel: "webhook", webhookUrl: "https://e.test/h" },
  },
  {
    op: "update_watch",
    call: (c) => c.watches.update("w 1", { isActive: false } as never),
    path: { watch_id: "w 1" },
    body: { isActive: false },
  },
  { op: "delete_watch", call: (c) => c.watches.delete("w1"), path: { watch_id: "w1" } },
  { op: "test_watch", call: (c) => c.watches.test("w1"), path: { watch_id: "w1" } },
  {
    op: "list_watch_changes",
    call: (c) => c.watches.listChanges("w1", { limit: 3, since: "2026-01-01" } as never),
    path: { watch_id: "w1" },
    query: { limit: "3", since: "2026-01-01" },
  },
  {
    op: "get_watch_change_diff",
    call: (c) => c.watches.getChangeDiff("w1", 77),
    path: { watch_id: "w1", change_id: "77" },
  },
  {
    op: "list_watch_deliveries",
    call: (c) => c.watches.listDeliveries("w1", { limit: 3 }),
    path: { watch_id: "w1" },
    query: { limit: "3" },
  },
  {
    op: "list_boards",
    call: (c) => c.boards.list({ state: "wa", limit: 2 } as never),
    query: { state: "wa", limit: "2" },
  },
  { op: "get_credit_balance", call: (c) => c.credits.balance() },
  {
    op: "get_pricing",
    call: (c) => c.pricing.get({ region: "US" } as never),
    query: { region: "US" },
  },
];

describe("resource methods match the OpenAPI spec", () => {
  it("covers every operationId in the spec exactly once", () => {
    expect(cases.map((c) => c.op).sort()).toEqual([...ops.keys()].sort());
    expect(ops.size).toBe(36);
  });

  it.each(cases)("$op", async ({ op, call, path = {}, query = {}, body }) => {
    const def = ops.get(op);
    if (!def) throw new Error(`unknown operation ${op}`);
    const status = op === "delete_watch" ? 204 : op === "create_watch" ? 201 : 200;
    const { client, calls } = makeClient([
      status === 204 ? new Response(null, { status }) : json(status, { ok: true }),
    ]);
    await call(client);
    const sent = calls[0];
    expect(calls).toHaveLength(1);

    // method and path
    const expectedPath = def.template.replace(/\{(\w+)\}/g, (_m, k: string) => {
      const v = path[k];
      if (v === undefined) throw new Error(`test gave no value for {${k}}`);
      return encodeURIComponent(v);
    });
    expect(sent?.method).toBe(def.method);
    expect(sent?.url.pathname).toBe(expectedPath);

    // query: exactly what was passed, and every name is a real spec query parameter
    const specQuery = def.params.filter((p) => p.in === "query").map((p) => p.name);
    for (const k of Object.keys(query)) expect(specQuery).toContain(k);
    expect(Object.fromEntries(sent?.url.searchParams ?? [])).toEqual(query);

    // body: exactly what was passed, and every key is declared by the request schema
    expect(sent?.body).toEqual(body);
    if (body) {
      expect(def.bodySchema).toBeDefined();
      const props = Object.keys(spec.components.schemas[def.bodySchema as string].properties);
      for (const k of Object.keys(body)) expect(props).toContain(k);
    } else {
      expect(def.bodySchema).toBeUndefined();
    }

    // charged <=> the spec declares an Idempotency-Key header; the client sends one
    const charged = def.params.some((p) => p.in === "header" && p.name === "Idempotency-Key");
    expect(sent?.headers.has("idempotency-key")).toBe(charged);
    expect(sent?.headers.get("authorization")).toMatch(/^Bearer vq_key_/);
  });
});
