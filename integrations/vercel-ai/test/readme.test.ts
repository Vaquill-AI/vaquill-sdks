import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Every TypeScript block in the README is a file under examples/, and `npm run typecheck:examples`
 * compiles those files against the real package types and the installed `ai`. This test keeps
 * the two identical, so a README snippet cannot drift from code that compiles.
 */
const readme = readFileSync(new URL("../README.md", import.meta.url), "utf8");
const blocks = [...readme.matchAll(/```ts\n([\s\S]*?)```/g)].map((m) => m[1] as string);
const dir = new URL("../examples/", import.meta.url);
const files = readdirSync(dir).filter((f) => f.endsWith(".ts"));

describe("README snippets", () => {
  it("has TypeScript snippets, including the Next.js route handler", () => {
    expect(blocks.length).toBeGreaterThanOrEqual(5);
    expect(blocks.some((b) => b.includes("export async function POST(req: Request)"))).toBe(true);
  });

  it("every README ts block is an examples/ file, verbatim", () => {
    const onDisk = new Set(files.map((f) => readFileSync(new URL(f, dir), "utf8")));
    for (const block of blocks) {
      expect(onDisk.has(block), `README block not in examples/:\n${block.slice(0, 120)}`).toBe(
        true,
      );
    }
  });

  it("every examples/ file is shown in the README", () => {
    const shown = new Set(blocks);
    for (const f of files) {
      expect(shown.has(readFileSync(new URL(f, dir), "utf8")), f).toBe(true);
    }
  });
});
