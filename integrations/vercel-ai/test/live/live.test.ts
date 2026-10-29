/**
 * Live smoke against api.vaquill.ai. Skipped unless VAQUILL_LIVE=1 and VAQUILL_API_KEY is set.
 * Run it with `VAQUILL_LIVE=1 VAQUILL_API_KEY=... npm run test:live`.
 * Spends at most 5 credits: the client is capped at 5 and only one tiny search is paid.
 * The key is read from the environment and never printed.
 */
import { describe, expect, it } from "vitest";
import { createVaquillTools } from "../../src/index.js";
import { exec } from "../helpers.js";

const LIVE = process.env.VAQUILL_LIVE === "1" && !!process.env.VAQUILL_API_KEY;

describe.skipIf(!LIVE)("live smoke (at most 5 credits)", () => {
  const tools = createVaquillTools({ maxCredits: 5 });

  it("creditBalance is free and answers", async () => {
    const result = await exec(tools.creditBalance, {});
    expect(result.ok).toBe(true);
    expect(typeof result.data.creditsRemaining).toBe("number");
  });

  it("one small search returns a section", async () => {
    const result = await exec(tools.searchStatutes, {
      query: "42 U.S.C. 1983",
      state: "federal",
      limit: 1,
    });
    expect(result.ok).toBe(true);
    expect(JSON.stringify(result)).not.toContain(process.env.VAQUILL_API_KEY as string);
    expect(result.creditsSpentSoFar).toBeLessThanOrEqual(5);
  });
});
