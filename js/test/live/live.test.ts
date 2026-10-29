/**
 * Live suite against production. Opt-in: `VAQUILL_LIVE=1 npm run test:live`.
 * The key is read by the SDK from VAQUILL_API_KEY and never touched here.
 * Findings are written to test/live/.out/results.json (git-ignored by convention, key-free).
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  APIConnectionError,
  APIStatusError,
  APITimeoutError,
  APIUserAbortError,
  AuthenticationError,
  NotFoundError,
  SpendGuardExceededError,
  UnprocessableEntityError,
  Vaquill,
} from "../../src/index.js";
import { type Drift, drift } from "./drift.js";

const LIVE = process.env.VAQUILL_LIVE === "1";
const OUT =
  process.env.VAQUILL_LIVE_OUT ?? new URL("./.out/results.json", import.meta.url).pathname;
const SOFT_CAP = 1500;
const ANCHOR = "USC_T17_C1_S107";
const ANCHOR_CITE = "17 U.S.C. 107";

type Rec = Record<string, any>;
const p = (x: unknown) => x as never;
const R = (x: unknown) => x as Rec;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface Row {
  name: string;
  op?: string;
  ok: boolean;
  charged: boolean;
  bodyCredits?: number;
  sdkCredits?: number;
  balanceDelta?: number;
  reconciled?: boolean;
  status?: number;
  requestId?: string | null;
  note?: string;
  error?: string;
}

const rows: Row[] = [];
const drifts: Record<string, Drift[]> = {};
const headerSeen = new Map<string, { count: number; sample: string }>();
const state: Rec = { requests: 0, notes: [] as string[] };
const SKIP_HEADERS = new Set([
  "set-cookie",
  "authorization",
  "report-to",
  "nel",
  "content-security-policy",
]);

let lastCall = 0;
const MIN_GAP_MS = 2300; // plan limit is 30 requests a minute
async function throttledFetch(
  input: string | URL | Request,
  init?: RequestInit,
): Promise<Response> {
  const wait = lastCall + MIN_GAP_MS - Date.now();
  if (wait > 0) await sleep(wait);
  lastCall = Date.now();
  state.requests++;
  const res = await fetch(input, init);
  for (const [k, v] of res.headers.entries()) {
    if (SKIP_HEADERS.has(k)) continue;
    const cur = headerSeen.get(k);
    headerSeen.set(k, { count: (cur?.count ?? 0) + 1, sample: cur?.sample ?? v.slice(0, 80) });
  }
  return res;
}

const client = new Vaquill({ fetch: throttledFetch, maxCredits: 1400, maxRetries: 2 });

function errSummary(e: unknown): string {
  if (e instanceof APIStatusError) {
    const body =
      typeof e.body === "string" ? e.body.slice(0, 200) : JSON.stringify(e.body)?.slice(0, 300);
    return `${e.name} ${e.status} code=${e.code} msg=${e.message.slice(0, 160)} body=${body}`;
  }
  return `${(e as Error)?.name}: ${(e as Error)?.message}`.slice(0, 300);
}

async function balance(): Promise<number> {
  const b = await client.credits.balance();
  return b.creditsRemaining as number;
}

/** Run one operation, bracket it with balance reads, and record the reconciliation. */
async function measure(
  name: string,
  op: string | undefined,
  charged: boolean,
  fn: () => { withResponse(): Promise<{ data: unknown; meta: Rec }> },
  note?: string,
): Promise<{ data?: Rec; ok: boolean }> {
  const before = charged ? await balance() : undefined;
  const sdkBefore = client.creditsSpent;
  const row: Row = { name, op, ok: false, charged, note };
  let data: Rec | undefined;
  try {
    const r = await fn().withResponse();
    data = R(r.data);
    row.ok = true;
    row.status = r.meta.status;
    row.requestId = r.meta.requestId;
    row.bodyCredits = r.meta.creditsConsumed;
    if (op) {
      const d = drift(op, r.data);
      if (d.length) drifts[name] = d;
    }
  } catch (e) {
    row.error = errSummary(e);
    if (e instanceof APIStatusError) row.status = e.status;
  }
  row.sdkCredits = client.creditsSpent - sdkBefore;
  if (before !== undefined) {
    row.balanceDelta = before - (await balance());
    row.reconciled = row.balanceDelta === row.sdkCredits;
  }
  rows.push(row);
  flush();
  return { data, ok: row.ok };
}

function flush() {
  mkdirSync(new URL("./.out/", import.meta.url).pathname, { recursive: true });
  writeFileSync(
    OUT,
    JSON.stringify(
      {
        rows,
        drifts,
        headers: Object.fromEntries(headerSeen),
        state: { requests: state.requests, notes: state.notes, ...state.summary },
      },
      null,
      1,
    ),
  );
}

describe.skipIf(!LIVE)("live production API", () => {
  it("1. credits.balance, pricing.get, statutes.coverage", async () => {
    state.balanceStart = await balance();
    const b = await measure("credits.balance", "get_credit_balance", false, () =>
      client.credits.balance(),
    );
    expect(b.ok).toBe(true);
    const pr = await measure("pricing.get", "get_pricing", false, () => client.pricing.get());
    expect(pr.ok).toBe(true);
    state.pricing = Object.fromEntries(
      (R(pr.data).costs as Rec[]).map((c) => [c.endpoint, c.credits]),
    );
    const cv = await measure("statutes.coverage", "list_statutes_coverage", false, () =>
      client.statutes.coverage(),
    );
    expect(cv.ok).toBe(true);
    state.corpusTypes = (R(cv.data).data?.corpusTypes ?? []).map((c: Rec) => c.token);
    flush();
  });

  it("2a. statutes.searchAll, two pages", async () => {
    const before = client.creditsSpent;
    const balBefore = await balance();
    const ids: string[] = [];
    let pages = 0;
    const it2 = client.statutes.searchAll(
      p({ query: "assault with a deadly weapon", state: "tx", limit: 3 }),
      { maxPages: 2 },
    );
    const row: Row = {
      name: "statutes.searchAll (2 pages x 3)",
      op: "search_statutes",
      ok: false,
      charged: true,
    };
    try {
      for await (const page of it2.pages()) {
        pages++;
        const pr = R(page);
        for (const r of pr.results ?? []) ids.push(r.actId);
        const d = drift("search_statutes", page);
        if (d.length) drifts["statutes.searchAll"] = d;
        state.firstSearch ??= pr;
      }
      row.ok = pages === 2 && new Set(ids).size === ids.length;
      row.note = `pages=${pages} rows=${ids.length} unique=${new Set(ids).size}`;
      state.txActId = ids[0];
      state.txActIds = ids;
    } catch (e) {
      row.error = errSummary(e);
    }
    row.sdkCredits = client.creditsSpent - before;
    row.balanceDelta = balBefore - (await balance());
    row.reconciled = row.balanceDelta === row.sdkCredits;
    rows.push(row);
    expect(row.error).toBeUndefined();
    expect(pages).toBe(2);
    flush();
  });

  // Charged operations, cheapest first. Each is bracketed by balance reads.
  it("2b. charged statutes operations in isolation", async () => {
    const tx = state.txActId ?? "TX_PE_22.01";
    await measure("statutes.resolve", "resolve_statute_citation", true, () =>
      client.statutes.resolve(p({ cite: ANCHOR_CITE })),
    );
    await measure("statutes.getSection", "get_section", true, () =>
      client.statutes.getSection(ANCHOR),
    );
    await measure("statutes.getSections (batch of 2)", "get_sections_batch", true, () =>
      client.statutes.getSections(p({ actIds: [ANCHOR, tx] })),
    );
    await measure("statutes.getSectionNeighbors", "get_section_neighbors", true, () =>
      client.statutes.getSectionNeighbors(ANCHOR, p({ limit: 2 })),
    );
    await measure("statutes.getSectionCitedBy", "get_section_cited_by", true, () =>
      client.statutes.getSectionCitedBy(ANCHOR, p({ limit: 3 })),
    );
    await measure("statutes.getSectionChanges", "get_section_changes", true, () =>
      client.statutes.getSectionChanges(ANCHOR, p({ limit: 3 })),
    );
    await measure("statutes.getSectionEnactments", "get_section_enactments", true, () =>
      client.statutes.getSectionEnactments(tx),
    );
    await measure("statutes.count", "count_statute_sections", true, () =>
      client.statutes.count(p({ corpusType: "USC", titleNumber: 17 })),
    );
    await measure("statutes.search (single)", "search_statutes", true, () =>
      client.statutes.search(
        p({ query: "fair use of copyrighted work", corpusType: "USC", limit: 3 }),
      ),
    );
    await measure("statutes.getSectionDefinitions", "get_section_definitions", true, () =>
      client.statutes.getSectionDefinitions(ANCHOR),
    );
    const div = await measure(
      "statutes.listDivisions (page 1)",
      "list_statute_divisions",
      true,
      () => client.statutes.listDivisions(p({ corpusType: "STATE", state: "tx" })),
    );
    state.divPage1 = div.data;
    await measure("statutes.extractCitations", "extract_statute_citations", true, () =>
      client.statutes.extractCitations(
        p({
          text: "Plaintiff sued under 42 U.S.C. § 1983(b). The court applied 17 U.S.C. § 107.",
        }),
      ),
    );
    await measure("statutes.resolveBatch (2)", "resolve_statute_citations_batch", true, () =>
      client.statutes.resolveBatch(p({ citations: [ANCHOR_CITE, "42 U.S.C. 1983"] })),
    );
    await measure("statutes.getSectionBody", "get_section_body", true, () =>
      client.statutes.getSectionBody(ANCHOR, p({ pinpoint: "(a)" })),
    );
    await measure("statutes.getSectionCrossState", "get_section_cross_state", true, () =>
      client.statutes.getSectionCrossState(tx, p({ limit: 3 })),
    );
    flush();
  });

  it("2c. divisions cursor pagination (two pages) and changes iterator", async () => {
    const before = client.creditsSpent;
    const pagesSeen: Rec[] = [];
    try {
      for await (const page of client.statutes
        .listDivisionsAll(p({ corpusType: "STATE", state: "tx" }), { maxPages: 2 })
        .pages()) {
        pagesSeen.push(R(page));
      }
    } catch (e) {
      state.notes.push(`listDivisionsAll error: ${errSummary(e)}`);
    }
    rows.push({
      name: "statutes.listDivisionsAll (maxPages 2)",
      op: "list_statute_divisions",
      ok: pagesSeen.length >= 1,
      charged: true,
      sdkCredits: client.creditsSpent - before,
      note: `pages=${pagesSeen.length} nextCursor=${pagesSeen.map((x) => x.nextCursor ?? x.meta?.nextCursor ?? null).join(",")}`.slice(
        0,
        200,
      ),
    });
    const before2 = client.creditsSpent;
    let n = 0;
    try {
      for await (const _ of client.statutes.getSectionChangesAll(ANCHOR, p({ limit: 2 }), {
        maxPages: 2,
        maxItems: 4,
      }))
        n++;
    } catch (e) {
      state.notes.push(`getSectionChangesAll error: ${errSummary(e)}`);
    }
    rows.push({
      name: "statutes.getSectionChangesAll (maxPages 2)",
      op: "get_section_changes",
      ok: true,
      charged: true,
      sdkCredits: client.creditsSpent - before2,
      note: `items=${n}`,
    });
    flush();
  });

  it("2d. session laws: list, search, get, body, versions, changes, batch", async () => {
    let j = "mn";
    let list = await measure("sessionLaws.list", "list_session_laws", true, () =>
      client.sessionLaws.list(p({ jurisdiction: j, limit: 3 })),
    );
    if (!list.ok) {
      j = "MN";
      state.notes.push("sessionLaws.list with lowercase jurisdiction failed; retried uppercase");
      list = await measure("sessionLaws.list (uppercase MN)", "list_session_laws", true, () =>
        client.sessionLaws.list(p({ jurisdiction: j, limit: 3 })),
      );
    }
    const rowsList: Rec[] =
      R(list.data).data?.laws ?? R(list.data).results ?? R(list.data).items ?? [];
    state.slListKeys = Object.keys(R(list.data));
    const ids = rowsList.map((x) => x.sessionLawId).filter(Boolean);
    const id = ids[0] ?? "SSL_MN_2025R_G_Y2025_C1";
    state.slId = id;
    const s = await measure("sessionLaws.search", "search_session_laws", true, () =>
      client.sessionLaws.search(p({ query: "appropriations", jurisdiction: j, limit: 3 })),
    );
    const sIds = (R(s.data).results ?? []).map((x: Rec) => x.sessionLawId).filter(Boolean);
    await measure("sessionLaws.get", "get_session_law", true, () =>
      client.sessionLaws.get(id, p({ jurisdiction: j })),
    );
    await measure("sessionLaws.getVersions", "get_session_law_versions", true, () =>
      client.sessionLaws.getVersions(id),
    );
    await measure("sessionLaws.getChanges", "get_session_law_changes", true, () =>
      client.sessionLaws.getChanges(p({ jurisdiction: j, limit: 3 })),
    );
    await measure("sessionLaws.getBatch (2)", "get_session_laws_batch", true, () =>
      client.sessionLaws.getBatch(
        p({ ids: [...new Set([id, ...sIds, ...ids])].slice(0, 2), jurisdiction: j }),
      ),
    );
    await measure("sessionLaws.getBody", "get_session_law_body", true, () =>
      client.sessionLaws.getBody(id, p({})),
    );
    // searchAll over two pages
    const b0 = client.creditsSpent;
    let pg = 0;
    try {
      for await (const _ of client.sessionLaws
        .searchAll(p({ query: "appropriations", jurisdiction: j, limit: 2 }), { maxPages: 2 })
        .pages())
        pg++;
    } catch (e) {
      state.notes.push(`sessionLaws.searchAll error: ${errSummary(e)}`);
    }
    rows.push({
      name: "sessionLaws.searchAll (2 pages)",
      op: "search_session_laws",
      ok: pg === 2,
      charged: true,
      sdkCredits: client.creditsSpent - b0,
      note: `pages=${pg}`,
    });
    flush();
  });

  it("3. free watch and board reads, watch diff if any change exists", async () => {
    await measure("boards.list", "list_boards", false, () => client.boards.list(p({ limit: 5 })));
    const w = await measure("watches.list", "list_watches", false, () =>
      client.watches.list(p({ limit: 5 })),
    );
    const watches: Rec[] = R(w.data).data?.watches ?? [];
    state.watchCount = watches.length;
    const first = watches[0];
    if (first?.id) {
      const ch = await measure("watches.listChanges", "list_watch_changes", false, () =>
        client.watches.listChanges(first.id, p({ limit: 2 })),
      );
      await measure("watches.listDeliveries", "list_watch_deliveries", false, () =>
        client.watches.listDeliveries(first.id, p({ limit: 2 })),
      );
      const change = (R(ch.data).data?.changes ?? [])[0];
      if (change?.id !== undefined) {
        await measure("watches.getChangeDiff", "get_watch_change_diff", true, () =>
          client.watches.getChangeDiff(first.id, change.id),
        );
      } else state.notes.push("no watch change available: watches.getChangeDiff not exercised");
    } else
      state.notes.push(
        "account has no watches: listChanges, listDeliveries, getChangeDiff not exercised",
      );
    // create without any delivery channel details: expected to be refused, never sends anything
    try {
      const created = await client.watches.create(p({ corpusType: "USC" }));
      state.notes.push(
        `watches.create with no channel details WORKED: ${JSON.stringify(created).slice(0, 200)}`,
      );
      const id = R(created).data?.id ?? R(created).data?.watch?.id;
      if (id) await client.watches.delete(id);
    } catch (e) {
      state.notes.push(`watches.create with no channel details refused: ${errSummary(e)}`);
    }
    flush();
  });

  it("4. error mapping", async () => {
    // invalid key
    const bad = new Vaquill({
      apiKey: `vq_key_${Array.from({ length: 32 }, () => "abcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(Math.random() * 36)]).join("")}`,
      fetch: throttledFetch,
      maxRetries: 0,
    });
    try {
      await bad.credits.balance();
      rows.push({ name: "error: invalid key", ok: false, charged: false, error: "did not throw" });
    } catch (e) {
      const ok = e instanceof AuthenticationError;
      rows.push({
        name: "error: invalid key",
        ok,
        charged: false,
        status: (e as APIStatusError).status,
        note: errSummary(e),
      });
    }
    // nonexistent act id
    const bal0 = await balance();
    const s0 = client.creditsSpent;
    try {
      await client.statutes.getSection("USC_T99_C99_S99999");
      rows.push({
        name: "error: nonexistent act_id",
        ok: false,
        charged: true,
        error: "did not throw",
      });
    } catch (e) {
      const ok = e instanceof NotFoundError;
      const body = R((e as APIStatusError).body);
      rows.push({
        name: "error: nonexistent act_id (getSection)",
        ok,
        charged: true,
        status: (e as APIStatusError).status,
        requestId: (e as APIStatusError).requestId,
        sdkCredits: client.creditsSpent - s0,
        balanceDelta: bal0 - (await balance()),
        note: `bodyKeys=${Object.keys(body ?? {}).join(",")} detailKeys=${Object.keys(R(body?.detail) ?? {}).join(",")} code=${(e as APIStatusError).code} detail=${JSON.stringify(body?.detail)?.slice(0, 240)}`,
      });
    }
    // 422
    const bal1 = await balance();
    try {
      await client.statutes.search(p({ query: 12345, limit: "many" }));
      rows.push({
        name: "error: invalid params",
        ok: false,
        charged: true,
        error: "did not throw",
      });
    } catch (e) {
      const ok = e instanceof UnprocessableEntityError;
      const ee = e as APIStatusError;
      rows.push({
        name: "error: invalid params (search body)",
        ok,
        charged: true,
        status: ee.status,
        balanceDelta: bal1 - (await balance()),
        note: `errorsParsed=${Array.isArray(ee.errors)} first=${JSON.stringify(ee.errors?.[0] ?? ee.detail)?.slice(0, 200)} code=${ee.code}`,
      });
    }
    flush();
  });

  it("5. idempotency: same Idempotency-Key twice", async () => {
    const key = `sdk-live-test-${crypto.randomUUID()}`;
    const bal0 = await balance();
    const a = await client.statutes
      .resolve(p({ cite: ANCHOR_CITE }), { idempotencyKey: key })
      .withResponse();
    const bal1 = await balance();
    const b = await client.statutes
      .resolve(p({ cite: ANCHOR_CITE }), { idempotencyKey: key })
      .withResponse();
    const bal2 = await balance();
    rows.push({
      name: "idempotency: same key twice (resolve)",
      op: undefined,
      ok: true,
      charged: true,
      bodyCredits: (a.meta.creditsConsumed ?? 0) + (b.meta.creditsConsumed ?? 0),
      balanceDelta: bal0 - bal2,
      note: `first charged ${bal0 - bal1}, second charged ${bal1 - bal2}, replayedHeader=${a.meta.idempotentReplayed}/${b.meta.idempotentReplayed}, sameBody=${JSON.stringify(a.data) === JSON.stringify(b.data)}`,
    });
    state.idemTwice = {
      first: bal0 - bal1,
      second: bal1 - bal2,
      replayed: b.meta.idempotentReplayed,
    };
    flush();
  });

  it("6. withResponse headers vs parsed meta", async () => {
    const r = await client.pricing.get().withResponse();
    const m = r.meta;
    state.metaParsed = { requestId: m.requestId, rateLimit: m.rateLimit, status: m.status };
    expect(m.status).toBe(200);
    state.headerRaw = {
      "x-request-id": r.response.headers.get("x-request-id"),
      "x-ratelimit-limit": r.response.headers.get("x-ratelimit-limit"),
      "x-ratelimit-remaining": r.response.headers.get("x-ratelimit-remaining"),
      "x-ratelimit-limit-day": r.response.headers.get("x-ratelimit-limit-day"),
      "x-ratelimit-remaining-day": r.response.headers.get("x-ratelimit-remaining-day"),
      "x-ratelimit-reset": r.response.headers.get("x-ratelimit-reset"),
      "retry-after": r.response.headers.get("retry-after"),
      "idempotent-replayed": r.response.headers.get("idempotent-replayed"),
    };
    flush();
  });

  it("7. guards: maxCredits, retry path, abort, timeout", async () => {
    // maxCredits
    let sent = 0;
    const counting = (i: string | URL | Request, init?: RequestInit) => {
      sent++;
      return throttledFetch(i, init);
    };
    const g = new Vaquill({ fetch: counting, maxCredits: 2 });
    await g.statutes.resolve(p({ cite: ANCHOR_CITE }));
    const sentAfterFirst = sent;
    let guardOk = false;
    try {
      await g.statutes.resolve(p({ cite: ANCHOR_CITE }));
    } catch (e) {
      guardOk = e instanceof SpendGuardExceededError && sent === sentAfterFirst;
    }
    state.guardCredits = g.creditsSpent;
    rows.push({
      name: "maxCredits guard",
      ok: guardOk,
      charged: true,
      sdkCredits: g.creditsSpent,
      note: `requests sent after guard: ${sent - sentAfterFirst}`,
    });

    // unroutable local port: retries, then APIConnectionError, no external traffic
    const dead = new Vaquill({ baseURL: "http://127.0.0.1:9", maxRetries: 2 });
    let t0 = Date.now();
    let retryOk = false;
    let note = "";
    try {
      await dead.pricing.get();
    } catch (e) {
      retryOk = e instanceof APIConnectionError && !(e instanceof APITimeoutError);
      note = `${(e as Error).name} after ${Date.now() - t0}ms cause=${(((e as Error).cause as Error)?.cause as Error)?.message ?? ((e as Error).cause as Error)?.message}`;
    }
    rows.push({
      name: "retry path to dead local port (free GET, maxRetries 2)",
      ok: retryOk && Date.now() - t0 >= 700,
      charged: false,
      note,
    });
    t0 = Date.now();
    try {
      await dead.statutes.resolve(p({ cite: ANCHOR_CITE }), { idempotencyKey: false });
    } catch (e) {
      rows.push({
        name: "no retry for charged call with idempotencyKey:false",
        ok: e instanceof APIConnectionError && Date.now() - t0 < 400,
        charged: false,
        note: `${(e as Error).name} after ${Date.now() - t0}ms`,
      });
    }

    // abort before send and mid-flight
    const ac = new AbortController();
    ac.abort();
    try {
      await client.pricing.get(undefined, { signal: ac.signal });
      rows.push({
        name: "abort (pre-aborted signal)",
        ok: false,
        charged: false,
        error: "did not throw",
      });
    } catch (e) {
      rows.push({
        name: "abort (pre-aborted signal)",
        ok: e instanceof APIUserAbortError,
        charged: false,
        note: (e as Error).name,
      });
    }
    const ac2 = new AbortController();
    const slow = client.statutes.coverage(undefined, { signal: ac2.signal });
    setTimeout(() => ac2.abort(), 5);
    try {
      await slow;
      rows.push({
        name: "abort (mid-flight)",
        ok: false,
        charged: false,
        error: "completed before abort",
      });
    } catch (e) {
      rows.push({
        name: "abort (mid-flight)",
        ok: e instanceof APIUserAbortError,
        charged: false,
        note: (e as Error).name,
      });
    }
    try {
      await client.pricing.get(undefined, { timeout: 1, maxRetries: 0 });
      rows.push({ name: "timeout (1ms)", ok: false, charged: false, error: "did not time out" });
    } catch (e) {
      rows.push({
        name: "timeout (1ms)",
        ok: e instanceof APITimeoutError,
        charged: false,
        note: (e as Error).name,
      });
    }
    flush();
  });

  it("8. rate-limit headers: 10 rapid free calls", async () => {
    await sleep(65_000);
    const raw = new Vaquill({ maxRetries: 0 });
    const seen: string[] = [];
    let limited = 0;
    for (let i = 0; i < 10; i++) {
      try {
        const r = await raw.pricing.get(p({})).withResponse();
        seen.push(`${r.meta.rateLimit.remaining}/${r.meta.rateLimit.remainingDay}`);
      } catch (e) {
        limited++;
        seen.push(`ERR ${(e as APIStatusError).status}`);
      }
    }
    rows.push({
      name: "10 rapid free calls (remaining min/day)",
      ok: limited === 0,
      charged: false,
      note: seen.join(" "),
    });
    flush();
    await sleep(30_000);
  });

  it("9. totals", async () => {
    const end = await balance();
    state.summary = {
      balanceStart: state.balanceStart,
      balanceEnd: end,
      balanceDeltaTotal: state.balanceStart - end,
      sdkCreditsSpent: client.creditsSpent,
      guardClientCredits: state.guardCredits,
      pricing: state.pricing,
      corpusTypes: state.corpusTypes,
      slListKeys: state.slListKeys,
      watchCount: state.watchCount,
      idemTwice: state.idemTwice,
      headerRaw: state.headerRaw,
      metaParsed: state.metaParsed,
    };
    flush();
    expect(state.balanceStart - end).toBeLessThan(SOFT_CAP);
  });
});
