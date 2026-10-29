import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createVaquillTools } from "../src/index.js";
import {
  AgentClass,
  finish,
  generateText,
  MockModel,
  simulateReadableStream,
  stepLimit,
  streamText,
  usage,
} from "./ai-compat.js";
import { type Fake, startFake } from "./helpers.js";

let fake: Fake;
beforeAll(async () => {
  fake = await startFake();
  fake.handle((req) =>
    req.path.endsWith("/search")
      ? {
          body: {
            creditsConsumed: 2,
            results: [{ actId: "USC_42_1983", citation: "42 USC 1983" }],
          },
        }
      : undefined,
  );
});
afterAll(() => fake.close());

/** A model that calls one tool, then answers. */
function scriptedModel(toolName: string, input: unknown) {
  let turn = 0;
  let streamTurn = 0;
  return new MockModel({
    doStream: async () => {
      streamTurn += 1;
      const chunks: any[] =
        streamTurn === 1
          ? [
              { type: "stream-start" as const, warnings: [] },
              {
                type: "tool-call" as const,
                toolCallId: "call_1",
                toolName,
                input: JSON.stringify(input),
              },
              {
                type: "finish" as const,
                finishReason: finish("tool-calls") as any,
                usage,
              },
            ]
          : [
              { type: "stream-start" as const, warnings: [] },
              { type: "text-start" as const, id: "t1" },
              { type: "text-delta" as const, id: "t1", delta: "Done." },
              { type: "text-end" as const, id: "t1" },
              {
                type: "finish" as const,
                finishReason: finish("stop") as any,
                usage,
              },
            ];
      return { stream: simulateReadableStream({ chunks }) };
    },
    doGenerate: async () => {
      turn += 1;
      if (turn === 1) {
        return {
          content: [
            {
              type: "tool-call" as const,
              toolCallId: "call_1",
              toolName,
              input: JSON.stringify(input),
            },
          ],
          finishReason: finish("tool-calls") as any,
          usage,
          warnings: [],
        };
      }
      return {
        content: [{ type: "text" as const, text: "Done." }],
        finishReason: finish("stop") as any,
        usage,
        warnings: [],
      };
    },
  });
}

describe("with the AI SDK", () => {
  it("generateText runs a Vaquill tool and feeds the result back", async () => {
    fake.requests.length = 0;
    const model = scriptedModel("searchStatutes", { query: "civil rights" });
    const result = await generateText({
      model,
      tools: createVaquillTools({ client: fake.client() }),
      stopWhen: stepLimit(3),
      prompt: "Find the civil rights statute.",
    });
    expect(result.text).toBe("Done.");
    expect(fake.requests).toHaveLength(1);
    const toolResult = result.steps[0]?.toolResults[0];
    expect(toolResult?.toolName).toBe("searchStatutes");
    expect(toolResult?.output).toMatchObject({
      ok: true,
      data: { results: [{ actId: "USC_42_1983" }] },
    });
    // The tool schemas reach the model as JSON Schema.
    const advertised = model.doGenerateCalls[0]?.tools?.map((t: { name: string }) => t.name) ?? [];
    expect(advertised).toContain("searchStatutes");
    expect(advertised).not.toContain("createWatch");
  });

  it("invalid model arguments never reach the API", async () => {
    fake.requests.length = 0;
    const result = await generateText({
      model: scriptedModel("searchStatutes", { query: "x", limit: 500 }),
      tools: createVaquillTools({ client: fake.client() }),
      stopWhen: stepLimit(3),
      prompt: "go",
    });
    expect(fake.requests).toHaveLength(0);
    expect(JSON.stringify(result.steps[0]?.content)).toMatch(/tool-error|error/i);
  });

  it("a failed call becomes a normal tool result and the loop continues", async () => {
    const failing = await startFake();
    failing.handle(() => ({ status: 404, body: { detail: "no such section" } }));
    const result = await generateText({
      model: scriptedModel("getStatuteSection", { actId: "MISSING" }),
      tools: createVaquillTools({ client: failing.client() }),
      stopWhen: stepLimit(3),
      prompt: "go",
    });
    await failing.close();
    expect(result.text).toBe("Done.");
    expect(result.steps[0]?.toolResults[0]?.output).toMatchObject({
      ok: false,
      error: { kind: "not_found" },
    });
  });

  it("streamText and agents accept the tools", async () => {
    const tools = createVaquillTools({ client: fake.client() });
    const streamed = streamText({
      model: scriptedModel("creditBalance", {}),
      tools,
      stopWhen: stepLimit(3),
      prompt: "balance?",
    });
    expect(await streamed.text).toBe("Done.");

    const agent = new AgentClass({
      model: scriptedModel("creditBalance", {}),
      tools,
      stopWhen: stepLimit(3),
    });
    const out = await agent.generate({ prompt: "balance?" });
    expect(out.text).toBe("Done.");
  });
});
