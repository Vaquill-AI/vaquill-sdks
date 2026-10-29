import { streamText, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const result = streamText({
  model: "anthropic/claude-sonnet-4.5",
  tools: createVaquillTools({ maxCredits: 50 }),
  stopWhen: isStepCount(6),
  prompt: "Does 12 CFR 1026.3 still say what it said in 2020?",
});

for await (const chunk of result.textStream) process.stdout.write(chunk);
