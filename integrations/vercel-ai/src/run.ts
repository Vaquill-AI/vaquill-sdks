import type { Vaquill } from "@vaquill-ai/sdk";
import { isAbort, scrub, type ToolFailure, toToolFailure } from "./errors.js";

/** Options every tool factory accepts. */
export interface ToolOptions {
  /**
   * A result whose JSON is longer than this many characters is replaced by a short preview and a
   * note telling the model to narrow the request, so one huge section cannot fill the context.
   * Default 60000.
   */
  maxResultChars?: number;
  /** Extra strings to scrub from error messages (the API key is always scrubbed). */
  redact?: readonly string[];
}

export const DEFAULT_MAX_RESULT_CHARS = 60_000;
const PREVIEW_CHARS = 2_000;

export interface ToolSuccess<T> {
  ok: true;
  data: T;
  /** Credits this API key has spent in this process so far (all Vaquill calls on the client). */
  creditsSpentSoFar: number;
}

export interface ToolTruncated {
  ok: true;
  truncated: true;
  totalChars: number;
  preview: string;
  note: string;
  creditsSpentSoFar: number;
}

export type ToolResult<T = unknown> = ToolSuccess<T> | ToolTruncated | ToolFailure;

export function secretsFor(options: ToolOptions | undefined): string[] {
  return [...(options?.redact ?? [])];
}

/**
 * Runs one SDK call and shapes its outcome for the model: data on success, a structured failure
 * otherwise. Only an abort is rethrown, so the surrounding agent loop actually stops.
 */
export async function run(
  client: Vaquill,
  options: ToolOptions | undefined,
  call: () => PromiseLike<unknown>,
): Promise<ToolResult> {
  try {
    const data = await call();
    const creditsSpentSoFar = client.creditsSpent;
    const max = options?.maxResultChars ?? DEFAULT_MAX_RESULT_CHARS;
    const json = JSON.stringify(data) ?? "null";
    if (json.length > max) {
      return {
        ok: true,
        truncated: true,
        totalChars: json.length,
        preview: json.slice(0, PREVIEW_CHARS),
        note: "The result was too large to return in full (credits were still spent). Repeat the request narrower: a smaller limit, more filters, or a more specific section.",
        creditsSpentSoFar,
      };
    }
    return { ok: true, data, creditsSpentSoFar };
  } catch (err) {
    if (isAbort(err)) throw err;
    return toToolFailure(err, secretsFor(options));
  }
}

export { scrub };
