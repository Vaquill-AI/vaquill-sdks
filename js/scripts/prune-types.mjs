// Derives src/_generated/api.d.ts from src/_generated/schema.d.ts (openapi-typescript output).
//
// Why: the full generated file is ~1 MB because `paths`, `operations` and `components` are
// three huge interfaces. A declaration bundler cannot tree-shake members of an interface, so
// exporting or indexing any of them inlines all of it into dist/index.d.ts and slows editors.
// This script emits only what the SDK surface needs, as small top-level aliases:
//   * `OperationTypes`: per operation id, its query, JSON body and success response;
//   * every `components["schemas"]` entry reachable from those, as a named top-level type;
//   * a compact `components` interface (schemas only) so `components["schemas"]["X"]` still works.
// Error responses, response headers and `paths` are dropped. Run via `npm run gen`.
import { readFileSync, writeFileSync } from "node:fs";
import ts from "typescript";

const SRC = "src/_generated/schema.d.ts";
const OUT = "src/_generated/api.d.ts";
const text = readFileSync(SRC, "utf8");
const sf = ts.createSourceFile(SRC, text, ts.ScriptTarget.Latest, true);

const REF = /components\["schemas"\]\["([^"]+)"\]/g;
const ident = (name) => name.replace(/[^A-Za-z0-9_$]/g, "_");

const decl = (name) =>
  sf.statements.find(
    (s) => ts.isInterfaceDeclaration(s) && s.name.text === name,
  );
const members = (node) => (node?.type && ts.isTypeLiteralNode(node.type) ? node.type.members : node?.members ?? []);
const prop = (container, name) =>
  (ts.isTypeLiteralNode(container) || ts.isInterfaceDeclaration(container) ? container.members : []).find(
    (m) => ts.isPropertySignature(m) && m.name && String(m.name.text) === name,
  );
const typeText = (p) => (p?.type ? p.type.getText(sf) : undefined);
const dedent = (s) => s.replace(/\n {8}/g, "\n");
// Keep what editors show on hover (description, default, deprecation) and drop the generated
// title line, @example and @enum blocks, which are most of the bytes.
const MAX_DOC = 64;
// Long prose is the bulk of the generated file (the full text lives in the API docs), so keep
// the first sentence, capped at MAX_DOC characters.
const firstSentence = (d) => {
  const m = d.match(/^(.*?[.!?])(\s|$)/);
  let out = m && m[1].length <= MAX_DOC ? m[1] : d;
  if (out.length > MAX_DOC) out = `${out.slice(0, MAX_DOC).replace(/\s+\S*$/, "")}...`;
  return out;
};
const compactDoc = (block) => {
  const lines = block
    .replace(/^\s*\/\*\*|\*\/\s*$/g, "")
    .split("\n")
    .map((l) => l.replace(/^\s*\* ?/, ""));
  const keep = [];
  let tag = null;
  const tagged = { description: [], default: [], deprecated: [] };
  for (const l of lines) {
    const m = l.match(/^@(\w+)\s?(.*)$/);
    if (m) {
      tag = m[1];
      if (tag in tagged) tagged[tag].push(m[2]);
    } else if (tag === null) {
      // generated title line: dropped
    } else if (tag in tagged) {
      tagged[tag].push(l);
    }
  }
  const clean = (a) => a.join(" ").replace(/\s+/g, " ").trim();
  const desc = firstSentence(clean(tagged.description));
  if (desc) keep.push(desc);
  if (tagged.default.length) keep.push(`@default ${clean(tagged.default)}`);
  if (tagged.deprecated.length) keep.push(`@deprecated ${clean(tagged.deprecated)}`);
  if (!keep.length) return "";
  return `/** ${keep.join(" ")} */`;
};
const compact = (src) =>
  src
    .replace(/\/\*\*[\s\S]*?\*\//g, (b) => compactDoc(b))
    .replace(/^[ \t]*\n/gm, "")
    .replace(/^( +)/gm, (sp) => " ".repeat(Math.ceil(sp.length / 2)));
const isNever = (t) => t === undefined || t === "never";

const ops = decl("operations");
const comps = decl("components");
if (!ops || !comps) throw new Error("operations/components interfaces not found");

const schemaNodes = new Map();
for (const m of prop(comps, "schemas").type.members) {
  if (ts.isPropertySignature(m)) schemaNodes.set(String(m.name.text), m);
}

const isStrLit = (t) => ts.isLiteralTypeNode(t) && ts.isStringLiteral(t.literal);
const isNullish = (t) =>
  t.kind === ts.SyntaxKind.NullKeyword ||
  t.kind === ts.SyntaxKind.UndefinedKeyword ||
  (ts.isLiteralTypeNode(t) && t.literal.kind === ts.SyntaxKind.NullKeyword);

// Source text of a type node. With `lenient`, every union of string literals (response enums)
// also accepts any other string, so a value the server adds later does not fail to type-check,
// while autocompletion still offers the known values.
const textOf = (node, lenient) => {
  const base = node.getStart(sf);
  const cuts = [];
  const visit = (n) => {
    if (lenient && ts.isUnionTypeNode(n)) {
      const lits = n.types.filter(isStrLit);
      if (lits.length >= 2 && lits.length + n.types.filter(isNullish).length === n.types.length) {
        cuts.push(lits[lits.length - 1].end - base);
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(node);
  let t = node.getText(sf);
  for (const c of cuts.sort((x, y) => y - x)) t = `${t.slice(0, c)} | (string & {})${t.slice(c)}`;
  return t;
};

const REFS = (t) => [...t.matchAll(REF)].map((m) => m[1]);
const rewrite = (t) =>
  t.replace(REF, (_m, n) => {
    if (!schemaNodes.has(n)) throw new Error(`unknown schema ${n}`);
    return ident(n);
  });
const json = (node) => {
  const content = node?.type && ts.isTypeLiteralNode(node.type) ? prop(node.type, "content") : undefined;
  return content?.type && ts.isTypeLiteralNode(content.type) ? prop(content.type, "application/json") : undefined;
};

// Phase 1: pick the pieces of every operation (raw text, schema refs still in openapi form).
const picked = [];
for (const op of ops.members) {
  if (!ts.isPropertySignature(op)) continue;
  const lit = op.type;
  const params = prop(lit, "parameters");
  const qp = params?.type && ts.isTypeLiteralNode(params.type) ? prop(params.type, "query") : undefined;
  const query = qp?.type && typeText(qp) !== "never" ? qp.type : undefined;
  const rb = prop(lit, "requestBody");
  const body = rb && !rb.questionToken ? json(rb)?.type : undefined;
  const responses = prop(lit, "responses");
  let response;
  for (const code of ["200", "201"]) {
    const r = responses?.type && ts.isTypeLiteralNode(responses.type) ? prop(responses.type, code) : undefined;
    if (json(r)) {
      response = json(r).type;
      break;
    }
  }
  picked.push({ id: String(op.name.text), query, body, response });
}

// Schemas reachable from requests stay strict (a typo in a request enum should not compile);
// the rest, reachable only from responses, get lenient enums.
const closure = (seeds) => {
  const seen = new Set();
  const queue = [...seeds];
  while (queue.length) {
    const n = queue.pop();
    if (seen.has(n)) continue;
    seen.add(n);
    queue.push(...REFS(schemaNodes.get(n).type.getText(sf)));
  }
  return seen;
};
const reqSeeds = picked.flatMap((o) => [o.query, o.body].filter(Boolean).flatMap((n) => REFS(n.getText(sf))));
const strict = closure(reqSeeds);
const respSeeds = picked.flatMap((o) => (o.response ? REFS(o.response.getText(sf)) : []));
const reachable = closure([...reqSeeds, ...respSeeds]);

// Long enums repeated verbatim (the 50-state list) become one named alias.
const dupes = new Map();
const hoist = (t) =>
  t.replace(/\(?(?:"[^"\n]*"(?: \| \(string & \{\}\))? \| ){7,}"[^"\n]*"(?: \| \(string & \{\}\))?\)?/g, (m) => {
    if (m.length < 200) return m;
    if (!dupes.has(m)) dupes.set(m, { n: 0, name: `Enum${dupes.size + 1}` });
    dupes.get(m).n++;
    return dupes.get(m).name;
  });

const fix = (node, lenient) => (node ? hoist(rewrite(dedent(textOf(node, lenient)))) : "never");
const opLines = picked.map(
  (o) =>
    `    ${o.id}: {\n      query: ${fix(o.query, false)};\n      body: ${fix(o.body, false)};\n      response: ${
      o.response ? fix(o.response, true) : "undefined"
    };\n    };`,
);

const bodies = new Map();
for (const n of reachable) {
  const node = schemaNodes.get(n);
  const body = hoist(rewrite(dedent(textOf(node.type, !strict.has(n)))));
  const ranges = ts.getLeadingCommentRanges(text, node.getFullStart()) ?? [];
  const doc = ranges.map((r) => text.slice(r.pos, r.end).replace(/^ {8}/gm, "")).join("\n");
  bodies.set(n, { doc, body });
}
// Keep only aliases used at least twice; a single use is inlined back.
const unhoist = (t) => {
  for (const [m, d] of dupes) if (d.n < 2) t = t.replaceAll(d.name, m);
  return t;
};
for (const b of bodies.values()) b.body = unhoist(b.body);
for (let i = 0; i < opLines.length; i++) opLines[i] = unhoist(opLines[i]);
if (/components\[/.test([...bodies.values()].map((b) => b.body).join("") + opLines.join(""))) {
  throw new Error("unrewritten components[...] reference left in output");
}

const names = [...bodies.keys()].sort();
const out = compact([
  "/**",
  " * Derived from schema.d.ts by scripts/prune-types.mjs. Do not edit; run `npm run gen`.",
  " * Holds only the schemas reachable from the SDK's operations, as tree-shakable aliases.",
  " */",
  "",
  ...[...dupes].filter(([, d]) => d.n >= 2).map(([m, d]) => `export type ${d.name} = ${m.replace(/^\(|\)$/g, "")};\n`),
  ...names.map((n) => {
    const { doc, body } = bodies.get(n);
    return `${doc ? `${doc}\n` : ""}export type ${ident(n)} = ${body};\n`;
  }),
  "/** Query, JSON body and success response of every operation, keyed by operation id. */",
  "export interface OperationTypes {",
  ...opLines,
  "}",
  "",
  "/** Same shape as the openapi-typescript `components`, limited to the schemas the SDK uses. */",
  "export interface components {",
  "  schemas: {",
  ...names.map((n) => `    ${JSON.stringify(n)}: ${ident(n)};`),
  "  };",
  "}",
  "",
].join("\n"));
writeFileSync(OUT, out);
console.log(`${OUT}: ${out.length} bytes, ${names.length}/${schemaNodes.size} schemas, ${opLines.length} operations`);
