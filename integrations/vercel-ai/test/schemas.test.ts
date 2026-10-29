import { describe, expect, it } from "vitest";
import * as s from "../src/schemas.js";

const ok = (schema: { safeParse(v: unknown): { success: boolean } }, v: unknown) =>
  expect(schema.safeParse(v).success).toBe(true);
const bad = (schema: { safeParse(v: unknown): { success: boolean } }, v: unknown) =>
  expect(schema.safeParse(v).success).toBe(false);

describe("input schemas", () => {
  it("searchStatutes", () => {
    ok(s.searchStatutesInput, { query: "x" });
    ok(s.searchStatutesInput, { query: "x", state: ["ca", "ny"], corpusType: ["USC", "CFR"] });
    ok(s.searchStatutesInput, { query: "x", limit: 50, offset: 10000, changedSince: "2025-01-31" });
    bad(s.searchStatutesInput, {});
    bad(s.searchStatutesInput, { query: "" });
    bad(s.searchStatutesInput, { query: "x", limit: 51 });
    bad(s.searchStatutesInput, { query: "x", limit: 0 });
    bad(s.searchStatutesInput, { query: "x", limit: 1.5 });
    bad(s.searchStatutesInput, { query: "x", state: "california" });
    bad(s.searchStatutesInput, { query: "x", corpusType: "BOOKS" });
    bad(s.searchStatutesInput, { query: "x", changedSince: "yesterday" });
    bad(s.searchStatutesInput, { query: "x", yearFrom: 1200 });
    bad(s.searchStatutesInput, { query: "x", state: [] });
  });

  it("section tools require an actId", () => {
    for (const schema of [
      s.getStatuteSectionInput,
      s.getStatuteSectionTextInput,
      s.sectionChangesInput,
      s.citedByInput,
      s.definitionsInput,
      s.neighborsInput,
    ]) {
      ok(schema, { actId: "A1" });
      bad(schema, {});
      bad(schema, { actId: "" });
    }
    bad(s.neighborsInput, { actId: "A1", limit: 11 });
    bad(s.citedByInput, { actId: "A1", limit: 101 });
    bad(s.sectionChangesInput, { actId: "A1", changeKind: ["deleted"] });
    bad(s.getStatuteSectionTextInput, { actId: "A1", format: "pdf" });
    bad(s.getStatuteSectionTextInput, { actId: "A1", asOf: "2020/01/01" });
  });

  it("citation tools", () => {
    ok(s.resolveCitationInput, { cite: "42 U.S.C. 1983" });
    bad(s.resolveCitationInput, { cite: "" });
    bad(s.resolveCitationInput, { cite: "x", corpusType: "USC" });
    ok(s.resolveCitationsInput, { citations: ["a"] });
    bad(s.resolveCitationsInput, { citations: [] });
    bad(s.resolveCitationsInput, { citations: Array.from({ length: 101 }, () => "a") });
    ok(s.extractCitationsInput, { text: "x", state: "tx" });
    bad(s.extractCitationsInput, { text: "x", state: "federal" });
    bad(s.extractCitationsInput, { text: "x".repeat(50001) });
  });

  it("browse and count", () => {
    ok(s.listDivisionsInput, { corpusType: "USC" });
    bad(s.listDivisionsInput, {});
    bad(s.listDivisionsInput, { corpusType: "STATE_AG_OPINION" });
    ok(s.countSectionsInput, {});
    bad(s.countSectionsInput, { titleNumber: 0 });
  });

  it("session laws", () => {
    ok(s.searchSessionLawsInput, { query: "x", instrumentType: ["act"], limit: 25 });
    bad(s.searchSessionLawsInput, { query: "x", limit: 26 });
    bad(s.searchSessionLawsInput, { query: "x", offset: 60 });
    bad(s.searchSessionLawsInput, { query: "x", instrumentType: ["law"] });
    ok(s.getSessionLawInput, { sessionLawId: "us1_a" });
    bad(s.getSessionLawInput, {});
    ok(s.creditBalanceInput, {});
  });

  it("watches", () => {
    ok(s.createWatchInput, { corpusType: "USC", scope: { title: "21" } });
    bad(s.createWatchInput, { corpusType: "USC", scope: { title: 21 } });
    bad(s.createWatchInput, { corpusType: "USC", channel: "sms" });
    ok(s.updateWatchInput, { watchId: "w", isActive: false });
    bad(s.updateWatchInput, {});
    ok(s.deleteWatchInput, { watchId: "w" });
    bad(s.deleteWatchInput, {});
    ok(s.testWatchInput, { watchId: "w" });
    bad(s.testWatchInput, {});
    bad(s.testWatchInput, { watchId: "" });
    ok(s.listWatchesInput, { limit: 100 });
    bad(s.listWatchesInput, { limit: 101 });
  });
});
