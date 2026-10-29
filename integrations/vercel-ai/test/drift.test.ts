import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TOOL_OPERATIONS, UNMAPPED_OPERATIONS, WRITE_TOOL_OPERATIONS } from "../src/index.js";

const EM_DASH = String.fromCharCode(0x2014);

const spec = JSON.parse(
  readFileSync(new URL("../../../openapi/vaquill-us.json", import.meta.url), "utf8"),
) as { paths: Record<string, Record<string, { operationId?: string }>> };

const METHODS = new Set(["get", "post", "put", "patch", "delete"]);
const operations: Array<{ id: string; method: string; path: string }> = [];
for (const [path, item] of Object.entries(spec.paths)) {
  for (const [method, op] of Object.entries(item)) {
    if (METHODS.has(method) && op.operationId) {
      operations.push({ id: op.operationId, method: method.toUpperCase(), path });
    }
  }
}
const ids = new Set(operations.map((o) => o.id));

const exposed = new Set<string>([
  ...Object.values(TOOL_OPERATIONS),
  ...Object.values(WRITE_TOOL_OPERATIONS),
]);
const unmapped = new Set(Object.keys(UNMAPPED_OPERATIONS));

describe("OpenAPI drift", () => {
  it("reads the spec", () => {
    expect(operations.length).toBeGreaterThan(30);
  });

  it("every operation is exposed as a tool or listed in UNMAPPED_OPERATIONS", () => {
    const missing = operations.filter((o) => !exposed.has(o.id) && !unmapped.has(o.id));
    expect(
      missing.map((o) => `${o.method} ${o.path} (${o.id})`),
      "New API operations need a tool in TOOL_OPERATIONS or a reason in UNMAPPED_OPERATIONS",
    ).toEqual([]);
  });

  it("no mapped operation id is stale", () => {
    for (const id of [...exposed, ...unmapped]) expect(ids.has(id), id).toBe(true);
  });

  it("no operation is both exposed and unmapped, and every reason is real", () => {
    for (const id of unmapped) expect(exposed.has(id), id).toBe(false);
    for (const [id, reason] of Object.entries(UNMAPPED_OPERATIONS)) {
      expect(reason.length, id).toBeGreaterThan(20);
      expect(reason, id).not.toContain(EM_DASH);
    }
  });

  it("read tools only map to operations that do not change server state", () => {
    const writeVerbs = new Set(["PUT", "PATCH", "DELETE"]);
    for (const id of Object.values(TOOL_OPERATIONS)) {
      const op = operations.find((o) => o.id === id);
      expect(op && writeVerbs.has(op.method), id).toBeFalsy();
      expect(id.startsWith("create_") || id.startsWith("delete_") || id.startsWith("update_")).toBe(
        false,
      );
    }
  });

  it("write tools map to the watch operations", () => {
    for (const id of Object.values(WRITE_TOOL_OPERATIONS)) {
      expect(/watch/.test(id), id).toBe(true);
    }
  });
});
