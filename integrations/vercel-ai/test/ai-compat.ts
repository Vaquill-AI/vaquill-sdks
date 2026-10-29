/**
 * The only place the tests touch the parts of the AI SDK that differ between majors, so the same
 * suite runs against `ai` 5, 6 and 7 (CI matrix). The package source itself needs no shim:
 * `tool({ description, inputSchema, execute })` is identical in all three.
 *
 *   ai 7: isStepCount, ToolLoopAgent, MockLanguageModelV4 (finishReason { unified, raw })
 *   ai 6: stepCountIs, ToolLoopAgent, MockLanguageModelV3 (finishReason { unified, raw })
 *   ai 5: stepCountIs, Experimental_Agent, MockLanguageModelV2 (finishReason string)
 */
import * as ai from "ai";
import * as aiTest from "ai/test";

const a = ai as any;
const t = aiTest as any;

export const generateText: typeof ai.generateText = a.generateText;
export const streamText: typeof ai.streamText = a.streamText;
export const simulateReadableStream: typeof ai.simulateReadableStream = a.simulateReadableStream;

/** `isStepCount` on ai 7, `stepCountIs` before. */
export const stepLimit = (n: number): any => (a.isStepCount ?? a.stepCountIs)(n);

/** `ToolLoopAgent` on ai 6 and 7, `Experimental_Agent` on ai 5. */
export const AgentClass: new (
  settings: any,
) => { generate(input: any): Promise<{ text: string }> } = a.ToolLoopAgent ?? a.Experimental_Agent;

export const MockModel: new (settings: any) => ai.LanguageModel & { doGenerateCalls: any[] } =
  t.MockLanguageModelV4 ?? t.MockLanguageModelV3 ?? t.MockLanguageModelV2;

/** The spec generation the installed `ai` uses for models: 2 (ai 5), 3 (ai 6) or 4 (ai 7). */
export const SPEC = t.MockLanguageModelV4 ? 4 : t.MockLanguageModelV3 ? 3 : 2;

export const usage =
  SPEC === 2
    ? { inputTokens: 5, outputTokens: 5, totalTokens: 10 }
    : {
        inputTokens: { total: 5, noCache: 5, cacheRead: undefined, cacheWrite: undefined },
        outputTokens: { total: 5, text: 5, reasoning: undefined },
      };

export const finish = (unified: "stop" | "tool-calls") =>
  SPEC === 2 ? unified : { unified, raw: undefined };
