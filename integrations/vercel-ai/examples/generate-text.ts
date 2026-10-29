import { generateText, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const { text } = await generateText({
  model: "anthropic/claude-sonnet-4.5",
  tools: createVaquillTools({ maxCredits: 50 }),
  stopWhen: isStepCount(6),
  prompt: "What is the statute of limitations for medical malpractice in Texas? Cite the section.",
});
