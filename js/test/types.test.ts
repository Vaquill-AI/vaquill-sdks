import { describe, expect, expectTypeOf, it } from "vitest";
import type { BodyOf, components, QueryOf, ResponseOf, Vaquill } from "../src/index.js";

// These assertions run through `tsc --noEmit` (the `typecheck` script), which is what proves
// the types; the runtime half of each test only keeps vitest from reporting an empty file.

type SearchParams = Parameters<Vaquill["statutes"]["search"]>[0];
type SearchResult = Awaited<ReturnType<Vaquill["statutes"]["search"]>>;

describe("statutes.search types", () => {
  it("takes the documented request keys", () => {
    expectTypeOf<SearchParams>().toEqualTypeOf<BodyOf<"search_statutes">>();
    expectTypeOf<SearchParams>().toHaveProperty("query").toEqualTypeOf<string>();
    expectTypeOf<SearchParams>().toHaveProperty("limit");
    expectTypeOf<SearchParams>().toHaveProperty("offset");
    expectTypeOf<SearchParams>().toHaveProperty("state");
    expectTypeOf<SearchParams>().toHaveProperty("corpusType");
    expectTypeOf<SearchParams>().toHaveProperty("matchType");
    expectTypeOf<keyof SearchParams>().toEqualTypeOf<keyof BodyOf<"search_statutes">>();
    expect(true).toBe(true);
  });

  it("requires query and rejects unknown request keys", () => {
    const ok: SearchParams = { query: "adverse possession", limit: 5, state: "tx" };
    expect(ok.query).toBe("adverse possession");
    // @ts-expect-error query is required
    const missing: SearchParams = { limit: 5 };
    // @ts-expect-error unknown keys are a typo, not a feature
    const typo: SearchParams = { query: "x", limitt: 5 };
    expect([missing, typo]).toHaveLength(2);
  });

  it("keeps request enums strict so a typo does not compile", () => {
    // @ts-expect-error not a known matchType
    const bad: SearchParams = { query: "x", matchType: "fuzzy" };
    expect(bad).toBeDefined();
  });

  it("returns a response with the documented keys", () => {
    expectTypeOf<SearchResult>().toEqualTypeOf<ResponseOf<"search_statutes">>();
    expectTypeOf<SearchResult>().toHaveProperty("results");
    expectTypeOf<SearchResult>().toHaveProperty("total");
    expectTypeOf<SearchResult>().toHaveProperty("nextOffset");
    expectTypeOf<SearchResult>().toHaveProperty("hasMore");
    expectTypeOf<SearchResult>().toHaveProperty("processingTimeMs");
    expect(true).toBe(true);
  });

  it("types creditsConsumed as a number", () => {
    expectTypeOf<SearchResult["creditsConsumed"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<NonNullable<SearchResult["creditsConsumed"]>>().toBeNumber();
    expectTypeOf<ResponseOf<"get_section">>().toHaveProperty("creditsConsumed");
    expect(true).toBe(true);
  });
});

describe("lenient response enums", () => {
  it("accepts a value the server adds later, and still suggests the known ones", () => {
    type Quality = NonNullable<SearchResult["matchQuality"]>;
    expectTypeOf<"exact">().toExtend<Quality>();
    expectTypeOf<"a-quality-added-in-2027">().toExtend<Quality>();
    const future: Quality = "a-quality-added-in-2027";
    expect(future).toBeTypeOf("string");
  });

  it("exposes schemas through components", () => {
    expectTypeOf<components["schemas"]["StatuteSearchRequest"]>().toEqualTypeOf<SearchParams>();
    expectTypeOf<components["schemas"]["StatuteSearchResponse"]>().toEqualTypeOf<SearchResult>();
    expect(true).toBe(true);
  });
});

describe("other operations", () => {
  it("derive query types from the same table", () => {
    expectTypeOf<QueryOf<"get_pricing">>().toHaveProperty("region");
    expectTypeOf<QueryOf<"list_boards">>().not.toBeNever();
    expect(true).toBe(true);
  });
});
