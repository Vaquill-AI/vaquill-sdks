import { Vaquill } from "@vaquill-ai/sdk";
import type { ToolOptions } from "./run.js";
import {
  citedByTool,
  countSectionsTool,
  createWatchTool,
  creditBalanceTool,
  definitionsTool,
  deleteWatchTool,
  extractCitationsTool,
  getSessionLawTool,
  getStatuteSectionTextTool,
  getStatuteSectionTool,
  listDivisionsTool,
  listWatchesTool,
  neighborsTool,
  resolveCitationsTool,
  resolveCitationTool,
  searchSessionLawsTool,
  searchStatutesTool,
  sectionChangesTool,
  testWatchTool,
  updateWatchTool,
} from "./tools.js";

export type { ToolErrorKind, ToolFailure } from "./errors.js";
export { scrub, toToolFailure } from "./errors.js";
export { TOOL_OPERATIONS, UNMAPPED_OPERATIONS, WRITE_TOOL_OPERATIONS } from "./operations.js";
export type { ToolOptions, ToolResult, ToolSuccess, ToolTruncated } from "./run.js";
export { DEFAULT_MAX_RESULT_CHARS } from "./run.js";
export * from "./tools.js";

/** Default spend guard when this package builds the client: stops a runaway loop. */
export const DEFAULT_MAX_CREDITS = 200;

const FACTORIES = {
  searchStatutes: searchStatutesTool,
  getStatuteSection: getStatuteSectionTool,
  getStatuteSectionText: getStatuteSectionTextTool,
  resolveCitation: resolveCitationTool,
  resolveCitations: resolveCitationsTool,
  extractCitations: extractCitationsTool,
  countSections: countSectionsTool,
  listDivisions: listDivisionsTool,
  sectionChanges: sectionChangesTool,
  citedBy: citedByTool,
  definitions: definitionsTool,
  neighbors: neighborsTool,
  searchSessionLaws: searchSessionLawsTool,
  getSessionLaw: getSessionLawTool,
  creditBalance: creditBalanceTool,
} as const;

const WRITE_FACTORIES = {
  listWatches: listWatchesTool,
  createWatch: createWatchTool,
  updateWatch: updateWatchTool,
  deleteWatch: deleteWatchTool,
  testWatch: testWatchTool,
} as const;

type Factories = typeof FACTORIES;
type WriteFactories = typeof WRITE_FACTORIES;

export type ReadToolName = keyof Factories;
export type WriteToolName = keyof WriteFactories;
export type VaquillToolName = ReadToolName | WriteToolName;

/** The tools returned by `createVaquillTools`. Which keys are present depends on the options. */
export type VaquillToolSet = {
  [K in ReadToolName]?: ReturnType<Factories[K]>;
} & {
  [K in WriteToolName]?: ReturnType<WriteFactories[K]>;
};

export interface CreateVaquillToolsOptions extends ToolOptions {
  /** Defaults to the `VAQUILL_API_KEY` environment variable. Must start with `vq_key_`. Ignored when `client` is set. */
  apiKey?: string;
  /** Use your own configured `Vaquill` client (base URL, retries, fetch). */
  client?: Vaquill;
  /**
   * Hard cap on credits this process may spend through these tools. Once responses have reported
   * this many credits, every further charged call fails with a `spend_limit` result and sends no
   * request. Default 200 (`DEFAULT_MAX_CREDITS`). Pass `Infinity` to switch it off. With `client`,
   * the cap is applied to a derived client that shares the original's spend counter.
   *
   * Charged calls run one at a time while a cap is set, so parallel tool calls cannot overshoot it.
   */
  maxCredits?: number;
  /** Only these tools (by name). Names that do not exist throw. */
  include?: readonly VaquillToolName[];
  /** Everything except these tools (by name). Applied after `include`. */
  exclude?: readonly VaquillToolName[];
  /**
   * Also expose the tools that change state: createWatch, updateWatch, deleteWatch, testWatch
   * (and listWatches). Default false. Without it the returned tools are read-only.
   */
  allowWrites?: boolean;
}

function check(label: string, names: readonly string[] | undefined, known: ReadonlySet<string>) {
  for (const name of names ?? []) {
    if (!known.has(name)) {
      throw new TypeError(
        `createVaquillTools: unknown tool "${name}" in ${label}. Known tools: ${[...known].join(", ")}.`,
      );
    }
  }
}

/**
 * Builds the Vaquill tools for the Vercel AI SDK.
 *
 * ```ts
 * const tools = createVaquillTools({ maxCredits: 100 });
 * const { text } = await generateText({ model, tools, prompt });
 * ```
 *
 * Read-only by default. Most tools COST CREDITS; see `maxCredits`.
 */
export function createVaquillTools(options: CreateVaquillToolsOptions = {}): VaquillToolSet {
  const { include, exclude, allowWrites = false } = options;
  const known = new Set<string>([...Object.keys(FACTORIES), ...Object.keys(WRITE_FACTORIES)]);
  check("include", include, known);
  check("exclude", exclude, known);
  if (!allowWrites) {
    const writes = new Set<string>(Object.keys(WRITE_FACTORIES));
    const asked = (include ?? []).filter((n) => writes.has(n));
    if (asked.length) {
      throw new TypeError(
        `createVaquillTools: ${asked.join(", ")} change state and need allowWrites: true.`,
      );
    }
  }

  const maxCredits = options.maxCredits ?? DEFAULT_MAX_CREDITS;
  const cap = Number.isFinite(maxCredits) ? maxCredits : undefined;
  let client: Vaquill;
  if (options.client) {
    client = cap === undefined ? options.client : options.client.withOptions({ maxCredits: cap });
  } else {
    // With no apiKey the SDK reads VAQUILL_API_KEY itself (and throws a clear error if it is unset).
    client = new Vaquill({
      ...(options.apiKey ? { apiKey: options.apiKey } : {}),
      maxCredits: cap,
    });
  }

  const toolOptions: ToolOptions = {
    redact: [...(options.redact ?? []), ...(options.apiKey ? [options.apiKey] : [])],
    ...(options.maxResultChars === undefined ? {} : { maxResultChars: options.maxResultChars }),
  };

  const wanted = (name: string) =>
    (include === undefined || include.includes(name as VaquillToolName)) &&
    !exclude?.includes(name as VaquillToolName);

  const out: Record<string, unknown> = {};
  for (const [name, make] of Object.entries(FACTORIES)) {
    if (wanted(name)) out[name] = make(client, toolOptions);
  }
  if (allowWrites) {
    for (const [name, make] of Object.entries(WRITE_FACTORIES)) {
      if (wanted(name)) out[name] = make(client, toolOptions);
    }
  }
  return out as VaquillToolSet;
}

/**
 * The same tools with defaults, reading `VAQUILL_API_KEY` from the environment when called.
 * Read-only, capped at `DEFAULT_MAX_CREDITS`.
 */
export function vaquillTools(): VaquillToolSet {
  return createVaquillTools();
}
