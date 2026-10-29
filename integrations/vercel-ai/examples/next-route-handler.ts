// app/api/research/route.ts
import { convertToModelMessages, isStepCount, streamText, type UIMessage } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

export const maxDuration = 60;

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();

  // Build the tools per request so each request gets its own spend cap.
  const tools = createVaquillTools({ maxCredits: 25 });

  const result = streamText({
    model: "anthropic/claude-sonnet-4.5",
    system: "You are a US legal research assistant. Verify citations before relying on them.",
    messages: await convertToModelMessages(messages),
    tools,
    stopWhen: isStepCount(8),
  });
  return result.toUIMessageStreamResponse();
}
