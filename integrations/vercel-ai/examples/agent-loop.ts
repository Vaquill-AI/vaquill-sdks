import { ToolLoopAgent, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const researcher = new ToolLoopAgent({
  model: "anthropic/claude-sonnet-4.5",
  instructions:
    "You are a legal research assistant. Verify every citation with resolveCitation before relying on it. " +
    "Quote statute text only from getStatuteSectionText. Never cite a section you did not retrieve. " +
    "If a tool returns spend_limit, stop and answer from what you have.",
  tools: createVaquillTools({
    maxCredits: 100,
    // Read tools only; leave out the expensive ones if you do not need them.
    exclude: ["extractCitations", "listDivisions"],
  }),
  stopWhen: isStepCount(10),
});

const { text } = await researcher.generate({
  prompt: "Compare how California and New York define 'trade secret'.",
});
