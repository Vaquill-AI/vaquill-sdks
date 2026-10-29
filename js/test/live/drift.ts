/**
 * A small structural checker: walks a live JSON body against the OpenAPI response schema the
 * SDK types were generated from, and lists every place reality disagrees. It never throws.
 */
import { readFileSync } from "node:fs";

type Json = Record<string, unknown>;
type Any = any;

const spec: Any = JSON.parse(
  readFileSync(new URL("../../../openapi/vaquill-us.json", import.meta.url), "utf8"),
);

function deref(node: Any): Any {
  let cur = node;
  let guard = 0;
  while (cur && typeof cur === "object" && typeof cur.$ref === "string" && guard++ < 50) {
    let r: Any = spec;
    for (const k of cur.$ref.slice(2).split("/")) r = r?.[k];
    cur = r;
  }
  return cur;
}

export function responseSchema(operationId: string): Any {
  for (const methods of Object.values<Json>(spec.paths)) {
    for (const op of Object.values<Any>(methods)) {
      if (op?.operationId !== operationId) continue;
      for (const code of ["200", "201"]) {
        const sc = op.responses?.[code]?.content?.["application/json"]?.schema;
        if (sc) return sc;
      }
    }
  }
  return undefined;
}

export interface Drift {
  kind: "extra_field" | "missing_required" | "enum" | "type" | "null_not_allowed";
  path: string;
  detail: string;
}

function typeOf(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v === "number" ? (Number.isInteger(v) ? "integer" : "number") : typeof v;
}

function typeOk(t: string, actual: string): boolean {
  if (t === actual) return true;
  return t === "number" && actual === "integer";
}

/** Returns true when `value` is valid against `schema` (collecting drift only for the branch that matches best). */
function check(schema: Any, value: unknown, path: string, out: Drift[], depth = 0): void {
  const s = deref(schema);
  if (!s || depth > 14) return;
  if (s.allOf) {
    for (const part of s.allOf) check(part, value, path, out, depth + 1);
    return;
  }
  const alts: Any[] | undefined = s.anyOf ?? s.oneOf;
  if (alts) {
    const nullable = alts.some((a) => deref(a)?.type === "null");
    if (value === null) {
      if (!nullable) out.push({ kind: "null_not_allowed", path, detail: "null" });
      return;
    }
    const concrete = alts.filter((a) => deref(a)?.type !== "null");
    let best: Drift[] | undefined;
    for (const alt of concrete) {
      const sub: Drift[] = [];
      check(alt, value, path, sub, depth + 1);
      if (sub.length === 0) return;
      if (!best || sub.length < best.length) best = sub;
    }
    if (best) out.push(...best);
    return;
  }
  if (value === null) {
    if (s.nullable !== true && s.type !== "null") {
      out.push({ kind: "null_not_allowed", path, detail: "null where schema is non-nullable" });
    }
    return;
  }
  const actual = typeOf(value);
  const t: string | string[] | undefined = s.type;
  if (t && !(Array.isArray(t) ? t : [t]).some((x) => typeOk(x, actual))) {
    out.push({ kind: "type", path, detail: `schema ${JSON.stringify(t)} live ${actual}` });
    return;
  }
  if (s.enum && !s.enum.includes(value)) {
    out.push({ kind: "enum", path, detail: `live value ${JSON.stringify(value)} not in enum` });
  }
  if (actual === "array" && s.items) {
    for (const item of (value as unknown[]).slice(0, 25))
      check(s.items, item, `${path}[]`, out, depth + 1);
  } else if (actual === "object") {
    const obj = value as Json;
    const props: Json = s.properties ?? {};
    for (const req of s.required ?? []) {
      if (!(req in obj))
        out.push({ kind: "missing_required", path: `${path}.${req}`, detail: "absent" });
    }
    for (const [k, v] of Object.entries(obj)) {
      if (k in props) check(props[k], v, `${path}.${k}`, out, depth + 1);
      else if (s.additionalProperties && typeof s.additionalProperties === "object") {
        check(s.additionalProperties, v, `${path}.*`, out, depth + 1);
      } else if (!s.additionalProperties) {
        out.push({ kind: "extra_field", path: `${path}.${k}`, detail: typeOf(v) });
      }
    }
  }
}

export function drift(operationId: string, body: unknown): Drift[] {
  const schema = responseSchema(operationId);
  if (!schema)
    return [{ kind: "type", path: "$", detail: `no response schema for ${operationId}` }];
  const out: Drift[] = [];
  check(schema, body, "$", out);
  const seen = new Set<string>();
  return out.filter((d) => {
    const key = `${d.kind}|${d.path}|${d.detail}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
